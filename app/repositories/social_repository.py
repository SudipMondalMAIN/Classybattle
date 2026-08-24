"""
Repository layer for the Social System — Phase 15A.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.social import (
    ActivityFeedEntry,
    Follow,
    Friendship,
    FriendshipStatus,
    PlayerProfile,
    ProfileVisibility,
)
from app.models.user import User
from app.repositories.base import BaseRepository


class PlayerProfileRepository(BaseRepository[PlayerProfile]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PlayerProfile)

    async def get_by_user_id(self, user_id: UUID) -> Optional[PlayerProfile]:
        stmt = select(PlayerProfile).where(
            PlayerProfile.user_id == user_id, PlayerProfile.deleted_at.is_(None)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def touch_presence_if_stale(
        self, user_id: UUID, *, min_interval_seconds: int = 60
    ) -> None:
        """Marks a user online + refreshes last_seen_at, but only writes when
        the last heartbeat is older than min_interval_seconds (or missing).
        This lets callers invoke it on *every* authenticated request cheaply
        -- most calls become a no-op WHERE match with zero rows updated,
        instead of writing on every single API call. Silently does nothing
        if the user has no PlayerProfile yet (profiles are created lazily);
        we deliberately don't force-create one here to keep this fast and
        side-effect-light on the hot auth path."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=min_interval_seconds)
        stmt = (
            update(PlayerProfile)
            .where(
                PlayerProfile.user_id == user_id,
                PlayerProfile.deleted_at.is_(None),
                or_(
                    PlayerProfile.last_seen_at.is_(None),
                    PlayerProfile.last_seen_at < cutoff,
                    PlayerProfile.is_online.is_(False),
                ),
            )
            .values(is_online=True, last_seen_at=now)
        )
        result = await self.session.execute(stmt)
        if result.rowcount:
            await self.session.commit()

    async def count_online(self, *, stale_after_minutes: int = 5) -> int:
        """Counts users currently marked online. is_online is set by the
        client via POST /presence/online and never auto-expires, so a
        crashed/killed app can leave it stuck true -- guard against that
        by also requiring a recent last_seen_at heartbeat."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_after_minutes)
        stmt = (
            select(func.count())
            .select_from(PlayerProfile)
            .join(User, User.id == PlayerProfile.user_id)
            .where(
                PlayerProfile.is_online.is_(True),
                PlayerProfile.deleted_at.is_(None),
                PlayerProfile.last_seen_at.is_not(None),
                PlayerProfile.last_seen_at >= cutoff,
                User.deleted_at.is_(None),
            )
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def list_online(
        self,
        *,
        page: int,
        page_size: int,
        search: Optional[str] = None,
        stale_after_minutes: int = 5,
    ) -> tuple[Sequence[User], int]:
        """Paginated list of users currently online (same definition as
        count_online: is_online flag + a recent last_seen_at heartbeat),
        for the admin panel's 'Active users' view. Optional search matches
        name/UID same as the main user search."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_after_minutes)
        base_filters = [
            PlayerProfile.is_online.is_(True),
            PlayerProfile.deleted_at.is_(None),
            PlayerProfile.last_seen_at.is_not(None),
            PlayerProfile.last_seen_at >= cutoff,
            User.deleted_at.is_(None),
        ]

        stmt = (
            select(User)
            .join(PlayerProfile, PlayerProfile.user_id == User.id)
            .where(*base_filters)
        )
        count_stmt = (
            select(func.count(User.id))
            .select_from(User)
            .join(PlayerProfile, PlayerProfile.user_id == User.id)
            .where(*base_filters)
        )
        if search:
            like = f"%{search.strip().lower()}%"
            search_filter = or_(
                func.lower(User.full_name).like(like),
                func.lower(User.player_uid).like(like),
                func.lower(User.email).like(like),
                func.lower(PlayerProfile.display_name).like(like),
            )
            stmt = stmt.where(search_filter)
            count_stmt = count_stmt.where(search_filter)

        stmt = (
            stmt.order_by(PlayerProfile.last_seen_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        total = (await self.session.execute(count_stmt)).scalar_one()
        rows = (await self.session.execute(stmt)).scalars().all()
        return rows, total

    async def search(
        self,
        *,
        query: Optional[str],
        page: int,
        page_size: int,
        sort_by: str,
        sort_order: str,
    ) -> tuple[Sequence[tuple[Optional[PlayerProfile], User]], int]:
        """Searches by user (name/UID) with the profile joined in when it
        exists. Uses an OUTER join deliberately: a PlayerProfile row is only
        ever created lazily (first time a user's profile is fetched/edited),
        so an INNER join would silently hide every user who hasn't opened
        their profile yet -- i.e. most of the user base -- from search
        results entirely, by name AND by UID.
        """
        sortable = {
            "created_at": User.created_at,
            "display_name": func.coalesce(PlayerProfile.display_name, User.full_name),
            "friends_count": func.coalesce(PlayerProfile.friends_count, 0),
            "followers_count": func.coalesce(PlayerProfile.followers_count, 0),
        }
        order_col = sortable.get(sort_by, User.created_at)
        order_expr = order_col.desc() if sort_order.lower() == "desc" else order_col.asc()

        base_filters = [
            User.deleted_at.is_(None),
            or_(PlayerProfile.deleted_at.is_(None), PlayerProfile.id.is_(None)),
            or_(
                PlayerProfile.visibility.is_(None),
                PlayerProfile.visibility == ProfileVisibility.PUBLIC,
            ),
        ]

        stmt = (
            select(User, PlayerProfile)
            .outerjoin(PlayerProfile, PlayerProfile.user_id == User.id)
            .where(*base_filters)
        )
        count_stmt = (
            select(func.count(User.id))
            .select_from(User)
            .outerjoin(PlayerProfile, PlayerProfile.user_id == User.id)
            .where(*base_filters)
        )
        if query:
            like = f"%{query.strip().lower()}%"
            search_filter = or_(
                func.lower(User.full_name).like(like),
                func.lower(User.player_uid).like(like),
                func.lower(PlayerProfile.display_name).like(like),
            )
            stmt = stmt.where(search_filter)
            count_stmt = count_stmt.where(search_filter)

        stmt = stmt.order_by(order_expr).offset((page - 1) * page_size).limit(page_size)

        total = (await self.session.execute(count_stmt)).scalar_one()
        rows = (await self.session.execute(stmt)).all()
        # Return (profile, user) to match the existing (PlayerProfile, User)
        # contract used by callers -- profile may be None for users who
        # haven't had one lazily created yet.
        return [(r[1], r[0]) for r in rows], total


class FriendshipRepository(BaseRepository[Friendship]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Friendship)

    @staticmethod
    def _pair_filter(user_a: UUID, user_b: UUID):
        return or_(
            and_(Friendship.requester_id == user_a, Friendship.addressee_id == user_b),
            and_(Friendship.requester_id == user_b, Friendship.addressee_id == user_a),
        )

    async def get_between(self, user_a: UUID, user_b: UUID, *, include_deleted: bool = False) -> Optional[Friendship]:
        stmt = select(Friendship).where(self._pair_filter(user_a, user_b))
        if not include_deleted:
            stmt = stmt.where(Friendship.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_between_any(self, user_a: UUID, user_b: UUID) -> Optional[Friendship]:
        """Looks up the single row for this pair regardless of soft-delete
        state — there is only ever one physical row per (requester,
        addressee) pair due to the unique constraint, so any operation
        that creates/revives a row must check this first."""
        return await self.get_between(user_a, user_b, include_deleted=True)

    async def list_accepted_friend_ids(self, user_id: UUID) -> Sequence[UUID]:
        stmt = select(Friendship).where(
            or_(Friendship.requester_id == user_id, Friendship.addressee_id == user_id),
            Friendship.status == FriendshipStatus.ACCEPTED,
            Friendship.deleted_at.is_(None),
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [f.addressee_id if f.requester_id == user_id else f.requester_id for f in rows]

    async def list_friends_paginated(
        self, user_id: UUID, *, page: int, page_size: int, search: Optional[str] = None
    ) -> tuple[Sequence[User], int]:
        friend_ids = await self.list_accepted_friend_ids(user_id)
        if not friend_ids:
            return [], 0
        stmt = select(User).where(User.id.in_(friend_ids), User.deleted_at.is_(None))
        count_stmt = select(func.count(User.id)).where(
            User.id.in_(friend_ids), User.deleted_at.is_(None)
        )
        if search:
            like = f"%{search.strip().lower()}%"
            stmt = stmt.where(func.lower(User.full_name).like(like))
            count_stmt = count_stmt.where(func.lower(User.full_name).like(like))
        stmt = stmt.order_by(User.full_name.asc()).offset((page - 1) * page_size).limit(page_size)
        total = (await self.session.execute(count_stmt)).scalar_one()
        rows = (await self.session.execute(stmt)).scalars().all()
        return rows, total

    async def list_pending_incoming(self, user_id: UUID) -> Sequence[Friendship]:
        stmt = select(Friendship).where(
            Friendship.addressee_id == user_id,
            Friendship.status == FriendshipStatus.PENDING,
            Friendship.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def list_pending_outgoing(self, user_id: UUID) -> Sequence[Friendship]:
        stmt = select(Friendship).where(
            Friendship.requester_id == user_id,
            Friendship.status == FriendshipStatus.PENDING,
            Friendship.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def is_blocked(self, user_a: UUID, user_b: UUID) -> bool:
        stmt = select(Friendship.id).where(
            self._pair_filter(user_a, user_b),
            Friendship.status == FriendshipStatus.BLOCKED,
            Friendship.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def count_friends(self, user_id: UUID) -> int:
        ids = await self.list_accepted_friend_ids(user_id)
        return len(ids)


class FollowRepository(BaseRepository[Follow]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Follow)

    async def get(self, follower_id: UUID, followee_id: UUID) -> Optional[Follow]:
        stmt = select(Follow).where(
            Follow.follower_id == follower_id,
            Follow.followee_id == followee_id,
            Follow.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_followers(
        self, user_id: UUID, *, page: int, page_size: int
    ) -> tuple[Sequence[User], int]:
        stmt = (
            select(User)
            .join(Follow, Follow.follower_id == User.id)
            .where(Follow.followee_id == user_id, Follow.deleted_at.is_(None), User.deleted_at.is_(None))
        )
        count_stmt = (
            select(func.count(User.id))
            .join(Follow, Follow.follower_id == User.id)
            .where(Follow.followee_id == user_id, Follow.deleted_at.is_(None), User.deleted_at.is_(None))
        )
        stmt = stmt.order_by(Follow.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        total = (await self.session.execute(count_stmt)).scalar_one()
        rows = (await self.session.execute(stmt)).scalars().all()
        return rows, total

    async def list_following(
        self, user_id: UUID, *, page: int, page_size: int
    ) -> tuple[Sequence[User], int]:
        stmt = (
            select(User)
            .join(Follow, Follow.followee_id == User.id)
            .where(Follow.follower_id == user_id, Follow.deleted_at.is_(None), User.deleted_at.is_(None))
        )
        count_stmt = (
            select(func.count(User.id))
            .join(Follow, Follow.followee_id == User.id)
            .where(Follow.follower_id == user_id, Follow.deleted_at.is_(None), User.deleted_at.is_(None))
        )
        stmt = stmt.order_by(Follow.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        total = (await self.session.execute(count_stmt)).scalar_one()
        rows = (await self.session.execute(stmt)).scalars().all()
        return rows, total

    async def count_followers(self, user_id: UUID) -> int:
        stmt = select(func.count(Follow.id)).where(
            Follow.followee_id == user_id, Follow.deleted_at.is_(None)
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def count_following(self, user_id: UUID) -> int:
        stmt = select(func.count(Follow.id)).where(
            Follow.follower_id == user_id, Follow.deleted_at.is_(None)
        )
        return (await self.session.execute(stmt)).scalar_one()


class ActivityFeedRepository(BaseRepository[ActivityFeedEntry]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ActivityFeedEntry)

    async def get_by_event_key(self, event_key: str) -> Optional[ActivityFeedEntry]:
        stmt = select(ActivityFeedEntry).where(ActivityFeedEntry.event_key == event_key)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_feed(
        self, actor_ids: Sequence[UUID], *, page: int, page_size: int
    ) -> tuple[Sequence[ActivityFeedEntry], int]:
        if not actor_ids:
            return [], 0
        stmt = select(ActivityFeedEntry).where(
            ActivityFeedEntry.actor_id.in_(actor_ids), ActivityFeedEntry.deleted_at.is_(None)
        )
        count_stmt = select(func.count(ActivityFeedEntry.id)).where(
            ActivityFeedEntry.actor_id.in_(actor_ids), ActivityFeedEntry.deleted_at.is_(None)
        )
        stmt = (
            stmt.order_by(ActivityFeedEntry.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        total = (await self.session.execute(count_stmt)).scalar_one()
        rows = (await self.session.execute(stmt)).scalars().all()
        return rows, total