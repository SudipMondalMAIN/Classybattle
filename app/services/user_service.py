"""
User profile service.
"""
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException, ValidationException
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserProfileUpdate
from app.utils.avatars import is_valid_avatar


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_repo = UserRepository(session)

    async def get_user_by_id(self, user_id: UUID) -> User:
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise NotFoundException("User not found")
        return user

    async def update_profile(self, user_id: UUID, payload: UserProfileUpdate) -> User:
        user = await self.get_user_by_id(user_id)

        update_data = payload.model_dump(exclude_unset=True)

        if "avatar_id" in update_data and update_data["avatar_id"] is not None:
            if not is_valid_avatar(update_data["avatar_id"]):
                raise ValidationException("Invalid avatar selected")

        user = await self.user_repo.update(user, **update_data)
        await self.session.commit()
        return user
