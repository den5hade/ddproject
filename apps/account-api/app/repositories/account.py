from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.account import IdentityKind
from app.domain.identity import Identity
from app.models.account import Account


class AccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, account_id: UUID) -> Account | None:
        return await self._session.get(Account, account_id)

    async def get_by_identity(self, identity: str) -> Account | None:
        parsed = Identity.parse(identity)
        if parsed.kind.value == "email":
            where = or_(
                Account.email == parsed.canonical,
                Account.email_normalized == parsed.canonical,
            )
        else:
            where = or_(
                Account.phone == parsed.canonical,
                Account.phone_e164 == parsed.canonical,
            )
        result = await self._session.execute(select(Account).where(where))
        return result.scalar_one_or_none()

    async def get_or_create_by_identity(
        self, identity: str
    ) -> tuple[Account, bool]:
        """Return (account, created) looking up by email or phone."""
        parsed = Identity.parse(identity)
        account = await self.get_by_identity(identity)
        if account is not None:
            return account, False

        account = Account()
        if parsed.kind is IdentityKind.EMAIL:
            account.email = parsed.canonical
            account.email_normalized = parsed.canonical
        else:
            account.phone = parsed.canonical
            account.phone_e164 = parsed.canonical
        self._session.add(account)
        await self._session.flush()
        return account, True
