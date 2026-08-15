import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.user_type import UserType
from app.models.user import User

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_or_create_by_identity(
        self, identity: str, user_type: UserType = UserType.USER
    ) -> tuple[User, bool]:
        """Return (user, created) looking up by email or phone."""
        if EMAIL_RE.match(identity):
            column, field = User.email, "email"
        else:
            column, field = User.phone, "phone"

        result = await self._session.execute(select(User).where(column == identity))
        user = result.scalar_one_or_none()
        if user is not None:
            return user, False

        user = User(user_type=user_type)
        setattr(user, field, identity)
        self._session.add(user)
        await self._session.flush()
        return user, True