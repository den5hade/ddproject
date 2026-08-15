import re
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(value: str) -> str:
    return value.strip().lower()


class AccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, account_id: UUID) -> Account | None:
        return await self._session.get(Account, account_id)

    async def get_by_identity(self, identity: str) -> Account | None:
        if EMAIL_RE.match(identity):
            where = or_(
                Account.email == identity,
                Account.email_normalized == normalize_email(identity),
            )
        else:
            where = or_(Account.phone == identity, Account.phone_e164 == identity)
        result = await self._session.execute(select(Account).where(where))
        return result.scalar_one_or_none()

    async def get_or_create_by_identity(
        self, identity: str
    ) -> tuple[Account, bool]:
        """Return (account, created) looking up by email or phone."""
        account = await self.get_by_identity(identity)
        if account is not None:
            return account, False

        account = Account()
        if EMAIL_RE.match(identity):
            account.email = identity
            account.email_normalized = normalize_email(identity)
        else:
            account.phone = identity
            account.phone_e164 = identity
        self._session.add(account)
        await self._session.flush()
        return account, True