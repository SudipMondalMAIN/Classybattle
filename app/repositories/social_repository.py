"""
Repository layer for the Social System — Phase 15A.
"""
from __future__ import annotations

from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.social import (
    ActivityFeedEntry,
    Follow,
    Friendship,
    FriendshipStatus,
    PlayerProfile,
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

    async def search(
        self,
        *,
        query: Optional[str],
        page: int,
        page_size: int,
        sort_by: str,
        sort_order: str,
    ) -> tuple[Sequence[tuple[PlayerProfile, User]], int]:
        sortable = {
            "created_at": PlayerProfile.created_at,
            "display_name": PlayerProfile.display_name,
            "friends_count": PlayerProfile.friends_count,
            "followers_count": PlayerProfile.followers_count,
        }
        order_col = sortable.get(sort_by, PlayerProfile.created_at)
        order_expr = order_col.desc() if sort_order.lower() == "desc" else order_col.asc()

        stmt = (
            select(PlayerProfile, User)
            .join(User, User.id == PlayerProfile.user_id)
            .where(PlayerProfile.deleted_at.is_(None), User.deleted_at.is_(None))
        )
        count_stmt = (
            select(func.count(PlayerProfile.id))
            .join(User, User.id == PlayerProfile.user_id)
            .where(PlayerProfile.deleted_at.is_(None), User.deleted_at.is_(None))
        )
        if query:
            like = f"%{query.strip().lower()}%"
            search_filter = or_(
                func.lower(User.full_name).like(like),
                func.lower(PlayerProfile.display_name).like(like),
            )
            stmt = stmt.where(search_filter)
            count_stmt = count_stmt.where(search_filter)

        stmt = stmt.order_by(order_expr).offset((page - 1) * page_size).limit(page_size)

        total = (await self.session.execute(count_stmt)).scalar_one()
        rows = (await self.session.execute(stmt)).all()
        return [(r[0], r[1]) for r in rows], total


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
