from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.person import Person


class PersonRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, person_id: UUID) -> Person | None:
        return await self._session.get(Person, person_id)

    async def save(self, person: Person) -> Person:
        self._session.add(person)
        await self._session.flush()
        return person