"""
Social System services — Phase 15A (Player Profiles & Social System).

ProfileService     — profile CRUD, settings, presence, public/private view.
FriendshipService   — friend requests, accept/reject/cancel/remove, block.
FollowService       — follow/unfollow, followers/following listings.
ActivityFeedService — idempotent activity recording + feed assembly.
SocialSearchService — player/profile search with pagination/filter/sort.

All services reuse `AuditService` for sensitive mutations and
`NotificationDispatchService` for user-facing notifications, matching
the pattern established by Team/Tournament/Wallet services. Duplicate
friend requests / follows / activity entries are prevented at the DB
level via unique constraints (see app.models.social), the same
belt-and-suspenders approach used by Team invite codes.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ConflictException, ForbiddenException, NotFoundException
from app.models.audit_log import AuditAction
from app.models.notification import NotificationEventType
from app.models.social import (
    ActivityFeedEntry,
    ActivityType,
    Follow,
    Friendship,
    FriendshipStatus,
    PlayerProfile,
    ProfileVisibility,
)
from app.models.user import User
from app.notifications.dispatch_service import NotificationDispatchService
from app.repositories.social_repository import (
    ActivityFeedRepository,
    FollowRepository,
    FriendshipRepository,
    PlayerProfileRepository,
)
from app.repositories.user_repository import UserRepository
from app.services.audit_service import AuditService


def _paginate(total: int, page: int, page_size: int) -> int:
    return math.ceil(total / page_size) if total else 0


class ProfileService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = PlayerProfileRepository(session)
        self.user_repo = UserRepository(session)
        self.friend_repo = FriendshipRepository(session)
        self.follow_repo = FollowRepository(session)
        self.audit = AuditService(session)

    async def get_or_create(self, user: User) -> PlayerProfile:
        profile = await self.repo.get_by_user_id(user.id)
        if profile is not None:
            return profile
        try:
            profile = await self.repo.create(user_id=user.id, display_name=user.full_name)
        except IntegrityError:
            await self.session.rollback()
            profile = await self.repo.get_by_user_id(user.id)
        await self.session.commit()
        return profile

    async def update_profile(self, user: User, payload) -> PlayerProfile:
        profile = await self.get_or_create(user)
        old_values = {
            "display_name": profile.display_name,
            "bio": profile.bio,
            "avatar_url": profile.avatar_url,
            "cover_image_url": profile.cover_image_url,
        }
        data = payload.model_dump(exclude_unset=True)
        profile = await self.repo.update(profile, **data)
        await self.audit.record(
            entity="player_profile",
            action=AuditAction.UPDATE,
            entity_id=profile.id,
            actor=user,
            old_values=old_values,
            new_values=data,
        )
        await self.session.commit()
        return profile

    async def update_settings(self, user: User, payload) -> PlayerProfile:
        profile = await self.get_or_create(user)
        data = payload.model_dump(exclude_unset=True)
        profile = await self.repo.update(profile, **data)
        await self.audit.record(
            entity="player_profile",
            action=AuditAction.UPDATE,
            entity_id=profile.id,
            actor=user,
            new_values=data,
            description="Profile settings updated",
        )
        await self.session.commit()
        return profile

    async def touch_presence(self, user: User, *, online: bool) -> PlayerProfile:
        profile = await self.get_or_create(user)
        profile = await self.repo.update(
            profile, is_online=online, last_seen_at=datetime.now(timezone.utc)
        )
        await self.session.commit()
        return profile

    async def get_profile_for_viewer(
        self, *, target_user_id: UUID, viewer: Optional[User]
    ) -> tuple[PlayerProfile, User, str]:
        """Returns (profile, user, relationship_status). Enforces visibility."""
        target_user = await self.user_repo.get_by_id(target_user_id)
        if target_user is None:
            raise NotFoundException("Player not found")

        profile = await self.repo.get_by_user_id(target_user_id)
        if profile is None:
            profile = await self.repo.create(user_id=target_user_id, display_name=target_user.full_name)
            await self.session.commit()

        relationship = "none"
        if viewer is not None and viewer.id == target_user_id:
            relationship = "self"
        elif viewer is not None:
            if await self.friend_repo.is_blocked(viewer.id, target_user_id):
                relationship = "blocked"
            else:
                existing = await self.friend_repo.get_between(viewer.id, target_user_id)
                if existing is not None and existing.status == FriendshipStatus.ACCEPTED:
                    relationship = "friend"
                elif existing is not None and existing.status == FriendshipStatus.PENDING:
                    relationship = "pending"

        if relationship not in ("self", "friend") and profile.visibility == ProfileVisibility.PRIVATE:
            raise ForbiddenException("This profile is private")
        if (
            relationship not in ("self", "friend")
            and profile.visibility == ProfileVisibility.FRIENDS_ONLY
        ):
            raise ForbiddenException("This profile is only visible to friends")

        return profile, target_user, relationship

    async def is_following(self, viewer_id: Optional[UUID], target_user_id: UUID) -> bool:
        if viewer_id is None:
            return False
        follow = await self.follow_repo.get(viewer_id, target_user_id)
        return follow is not None

    async def search(
        self,
        *,
        query: Optional[str],
        page: int,
        page_size: int,
        sort_by: str,
        sort_order: str,
    ) -> tuple[list[tuple[PlayerProfile, User]], int]:
        rows, total = await self.repo.search(
            query=query, page=page, page_size=page_size, sort_by=sort_by, sort_order=sort_order
        )
        # Public search only ever surfaces public profiles.
        public_rows = [(p, u) for p, u in rows if p.visibility == ProfileVisibility.PUBLIC]
        return public_rows, total


class FriendshipService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = FriendshipRepository(session)
        self.profile_repo = PlayerProfileRepository(session)
        self.user_repo = UserRepository(session)
        self.audit = AuditService(session)
        self.dispatch = NotificationDispatchService(session)

    async def _sync_friend_counts(self, user_id: UUID) -> None:
        count = await self.repo.count_friends(user_id)
        profile = await self.profile_repo.get_by_user_id(user_id)
        if profile is None:
            user = await self.user_repo.get_by_id(user_id)
            if user is None:
                return
            try:
                await self.profile_repo.create(
                    user_id=user_id, display_name=user.full_name, friends_count=count
                )
            except IntegrityError:
                await self.session.rollback()
                profile = await self.profile_repo.get_by_user_id(user_id)
                if profile is not None:
                    await self.profile_repo.update(profile, friends_count=count)
            return
        await self.profile_repo.update(profile, friends_count=count)

    async def send_request(self, requester: User, addressee_id: UUID) -> Friendship:
        if requester.id == addressee_id:
            raise BadRequestException("You cannot send a friend request to yourself")

        addressee = await self.user_repo.get_by_id(addressee_id)
        if addressee is None:
            raise NotFoundException("Player not found")

        existing = await self.repo.get_between_any(requester.id, addressee_id)
        if existing is not None and existing.deleted_at is None:
            if existing.status == FriendshipStatus.BLOCKED:
                raise ForbiddenException("You cannot send a friend request to this player")
            if existing.status == FriendshipStatus.ACCEPTED:
                raise ConflictException("You are already friends with this player")
            if existing.status == FriendshipStatus.PENDING:
                raise ConflictException("A friend request is already pending")
            # Previously rejected/cancelled -> allow a fresh request by reopening.
            friendship = await self.repo.update(
                existing,
                requester_id=requester.id,
                addressee_id=addressee_id,
                status=FriendshipStatus.PENDING,
                action_by_id=requester.id,
                responded_at=None,
            )
        elif existing is not None and existing.deleted_at is not None:
            # A previously removed friendship/unblock row -> revive it.
            friendship = await self.repo.update(
                existing,
                requester_id=requester.id,
                addressee_id=addressee_id,
                status=FriendshipStatus.PENDING,
                action_by_id=requester.id,
                responded_at=None,
                deleted_at=None,
            )
        else:
            try:
                friendship = await self.repo.create(
                    requester_id=requester.id,
                    addressee_id=addressee_id,
                    status=FriendshipStatus.PENDING,
                    action_by_id=requester.id,
                )
            except IntegrityError:
                await self.session.rollback()
                raise ConflictException("A friend request already exists between these players")

        await self.audit.record(
            entity="friendship",
            action=AuditAction.CREATE,
            entity_id=friendship.id,
            actor=requester,
            new_values={"addressee_id": str(addressee_id), "status": "pending"},
        )
        await self.session.commit()

        await self.dispatch.dispatch(
            user=addressee,
            event_type=NotificationEventType.GENERAL,
            title="New friend request",
            body=f"{requester.full_name} sent you a friend request.",
            event_key=f"friend_request:{friendship.id}",
        )
        return friendship

    async def _get_pending_for_addressee(self, addressee: User, friendship_id: UUID) -> Friendship:
        friendship = await self.repo.get_by_id(friendship_id)
        if friendship is None or friendship.addressee_id != addressee.id:
            raise NotFoundException("Friend request not found")
        if friendship.status != FriendshipStatus.PENDING:
            raise ConflictException("This friend request is no longer pending")
        return friendship

    async def accept_request(self, addressee: User, friendship_id: UUID) -> Friendship:
        friendship = await self._get_pending_for_addressee(addressee, friendship_id)
        friendship = await self.repo.update(
            friendship,
            status=FriendshipStatus.ACCEPTED,
            action_by_id=addressee.id,
            responded_at=datetime.now(timezone.utc),
        )
        await self._sync_friend_counts(friendship.requester_id)
        await self._sync_friend_counts(friendship.addressee_id)
        await self.audit.record(
            entity="friendship",
            action=AuditAction.STATUS_CHANGE,
            entity_id=friendship.id,
            actor=addressee,
            new_values={"status": "accepted"},
        )
        await self.session.commit()

        requester = await self.user_repo.get_by_id(friendship.requester_id)
        if requester is not None:
            await self.dispatch.dispatch(
                user=requester,
                event_type=NotificationEventType.GENERAL,
                title="Friend request accepted",
                body=f"{addressee.full_name} accepted your friend request.",
                event_key=f"friend_request_accepted:{friendship.id}",
            )
        return friendship

    async def reject_request(self, addressee: User, friendship_id: UUID) -> Friendship:
        friendship = await self._get_pending_for_addressee(addressee, friendship_id)
        friendship = await self.repo.update(
            friendship,
            status=FriendshipStatus.REJECTED,
            action_by_id=addressee.id,
            responded_at=datetime.now(timezone.utc),
        )
        await self.audit.record(
            entity="friendship",
            action=AuditAction.STATUS_CHANGE,
            entity_id=friendship.id,
            actor=addressee,
            new_values={"status": "rejected"},
        )
        await self.session.commit()
        return friendship

    async def cancel_request(self, requester: User, friendship_id: UUID) -> Friendship:
        friendship = await self.repo.get_by_id(friendship_id)
        if friendship is None or friendship.requester_id != requester.id:
            raise NotFoundException("Friend request not found")
        if friendship.status != FriendshipStatus.PENDING:
            raise ConflictException("Only pending requests can be cancelled")
        friendship = await self.repo.update(
            friendship, status=FriendshipStatus.CANCELLED, action_by_id=requester.id
        )
        await self.audit.record(
            entity="friendship",
            action=AuditAction.STATUS_CHANGE,
            entity_id=friendship.id,
            actor=requester,
            new_values={"status": "cancelled"},
        )
        await self.session.commit()
        return friendship

    async def remove_friend(self, user: User, friend_user_id: UUID) -> None:
        friendship = await self.repo.get_between(user.id, friend_user_id)
        if friendship is None or friendship.status != FriendshipStatus.ACCEPTED:
            raise NotFoundException("Friendship not found")
        await self.repo.soft_delete(friendship)
        await self._sync_friend_counts(friendship.requester_id)
        await self._sync_friend_counts(friendship.addressee_id)
        await self.audit.record(
            entity="friendship",
            action=AuditAction.DELETE,
            entity_id=friendship.id,
            actor=user,
        )
        await self.session.commit()

    async def block_user(self, user: User, target_user_id: UUID) -> Friendship:
        if user.id == target_user_id:
            raise BadRequestException("You cannot block yourself")
        target = await self.user_repo.get_by_id(target_user_id)
        if target is None:
            raise NotFoundException("Player not found")

        existing = await self.repo.get_between_any(user.id, target_user_id)
        if existing is not None:
            friendship = await self.repo.update(
                existing,
                status=FriendshipStatus.BLOCKED,
                action_by_id=user.id,
                responded_at=datetime.now(timezone.utc),
                requester_id=existing.requester_id,
                addressee_id=existing.addressee_id,
                deleted_at=None,
            )
        else:
            try:
                friendship = await self.repo.create(
                    requester_id=user.id,
                    addressee_id=target_user_id,
                    status=FriendshipStatus.BLOCKED,
                    action_by_id=user.id,
                    responded_at=datetime.now(timezone.utc),
                )
            except IntegrityError:
                await self.session.rollback()
                raise ConflictException("Unable to block this player right now")

        await self._sync_friend_counts(user.id)
        await self._sync_friend_counts(target_user_id)
        await self.audit.record(
            entity="friendship",
            action=AuditAction.STATUS_CHANGE,
            entity_id=friendship.id,
            actor=user,
            new_values={"status": "blocked", "blocked_user_id": str(target_user_id)},
        )
        await self.session.commit()
        return friendship

    async def unblock_user(self, user: User, target_user_id: UUID) -> None:
        friendship = await self.repo.get_between(user.id, target_user_id)
        if friendship is None or friendship.status != FriendshipStatus.BLOCKED:
            raise NotFoundException("This player is not blocked")
        if friendship.action_by_id != user.id:
            raise ForbiddenException("Only the user who placed the block can remove it")
        await self.repo.soft_delete(friendship)
        await self.audit.record(
            entity="friendship",
            action=AuditAction.STATUS_CHANGE,
            entity_id=friendship.id,
            actor=user,
            new_values={"status": "unblocked"},
        )
        await self.session.commit()

    async def list_friends(
        self, user: User, *, page: int, page_size: int, search: Optional[str]
    ) -> tuple[Sequence[User], int]:
        return await self.repo.list_friends_paginated(user.id, page=page, page_size=page_size, search=search)

    async def list_incoming_requests(self, user: User) -> Sequence[Friendship]:
        return await self.repo.list_pending_incoming(user.id)

    async def list_outgoing_requests(self, user: User) -> Sequence[Friendship]:
        return await self.repo.list_pending_outgoing(user.id)

    async def mutual_friends(self, user: User, other_user_id: UUID) -> Sequence[User]:
        user_friend_ids = set(await self.repo.list_accepted_friend_ids(user.id))
        other_friend_ids = set(await self.repo.list_accepted_friend_ids(other_user_id))
        mutual_ids = user_friend_ids & other_friend_ids
        if not mutual_ids:
            return []
        users = []
        for uid in mutual_ids:
            u = await self.user_repo.get_by_id(uid)
            if u is not None:
                users.append(u)
        return users

    async def suggest_friends(self, user: User, *, limit: int = 10) -> Sequence[User]:
        """Friends-of-friends not already connected, blocked, or self."""
        direct_friend_ids = set(await self.repo.list_accepted_friend_ids(user.id))
        excluded = direct_friend_ids | {user.id}

        suggestions: dict[UUID, int] = {}
        for friend_id in direct_friend_ids:
            fof_ids = await self.repo.list_accepted_friend_ids(friend_id)
            for candidate_id in fof_ids:
                if candidate_id in excluded:
                    continue
                if await self.repo.is_blocked(user.id, candidate_id):
                    continue
                suggestions[candidate_id] = suggestions.get(candidate_id, 0) + 1

        ranked = sorted(suggestions.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        result = []
        for uid, _score in ranked:
            u = await self.user_repo.get_by_id(uid)
            if u is not None:
                result.append(u)
        return result


class FollowService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = FollowRepository(session)
        self.profile_repo = PlayerProfileRepository(session)
        self.user_repo = UserRepository(session)
        self.friend_repo = FriendshipRepository(session)
        self.dispatch = NotificationDispatchService(session)

    async def _ensure_profile_count(self, user_id: UUID, **counts) -> None:
        profile = await self.profile_repo.get_by_user_id(user_id)
        if profile is not None:
            await self.profile_repo.update(profile, **counts)
            return
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            return
        try:
            await self.profile_repo.create(user_id=user_id, display_name=user.full_name, **counts)
        except IntegrityError:
            await self.session.rollback()
            profile = await self.profile_repo.get_by_user_id(user_id)
            if profile is not None:
                await self.profile_repo.update(profile, **counts)

    async def _sync_counts(self, follower_id: UUID, followee_id: UUID) -> None:
        await self._ensure_profile_count(
            follower_id, following_count=await self.repo.count_following(follower_id)
        )
        await self._ensure_profile_count(
            followee_id, followers_count=await self.repo.count_followers(followee_id)
        )

    async def follow(self, follower: User, followee_id: UUID) -> Follow:
        if follower.id == followee_id:
            raise BadRequestException("You cannot follow yourself")
        followee = await self.user_repo.get_by_id(followee_id)
        if followee is None:
            raise NotFoundException("Player not found")
        if await self.friend_repo.is_blocked(follower.id, followee_id):
            raise ForbiddenException("You cannot follow this player")

        existing = await self.repo.get(follower.id, followee_id)
        if existing is not None:
            raise ConflictException("You are already following this player")
        try:
            follow = await self.repo.create(follower_id=follower.id, followee_id=followee_id)
        except IntegrityError:
            await self.session.rollback()
            raise ConflictException("You are already following this player")

        await self._sync_counts(follower.id, followee_id)
        await self.session.commit()

        await self.dispatch.dispatch(
            user=followee,
            event_type=NotificationEventType.GENERAL,
            title="New follower",
            body=f"{follower.full_name} started following you.",
            event_key=f"follow:{follow.id}",
        )
        return follow

    async def unfollow(self, follower: User, followee_id: UUID) -> None:
        follow = await self.repo.get(follower.id, followee_id)
        if follow is None:
            raise NotFoundException("You are not following this player")
        await self.repo.soft_delete(follow)
        await self._sync_counts(follower.id, followee_id)
        await self.session.commit()

    async def list_followers(self, user_id: UUID, *, page: int, page_size: int):
        return await self.repo.list_followers(user_id, page=page, page_size=page_size)

    async def list_following(self, user_id: UUID, *, page: int, page_size: int):
        return await self.repo.list_following(user_id, page=page, page_size=page_size)


class ActivityFeedService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ActivityFeedRepository(session)
        self.friend_repo = FriendshipRepository(session)
        self.follow_repo = FollowRepository(session)

    async def record(
        self,
        *,
        actor: User,
        activity_type: ActivityType,
        title: str,
        event_key: str,
        meta_data: Optional[dict] = None,
    ) -> Optional[ActivityFeedEntry]:
        """Idempotent: returns None (no-op) if `event_key` was already recorded."""
        existing = await self.repo.get_by_event_key(event_key)
        if existing is not None:
            return existing
        try:
            entry = await self.repo.create(
                actor_id=actor.id,
                activity_type=activity_type,
                title=title,
                meta_data=meta_data,
                event_key=event_key,
            )
        except IntegrityError:
            await self.session.rollback()
            return await self.repo.get_by_event_key(event_key)
        await self.session.commit()
        return entry

    async def get_feed_for_user(
        self, user: User, *, page: int, page_size: int
    ) -> tuple[Sequence[ActivityFeedEntry], int]:
        friend_ids = await self.friend_repo.list_accepted_friend_ids(user.id)
        following_rows, _ = await self.follow_repo.list_following(user.id, page=1, page_size=1000)
        following_ids = [u.id for u in following_rows]
        actor_ids = list({*friend_ids, *following_ids, user.id})
        return await self.repo.list_feed(actor_ids, page=page, page_size=page_size)
