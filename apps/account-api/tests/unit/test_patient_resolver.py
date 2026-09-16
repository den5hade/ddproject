from uuid import uuid4

import pytest
from app.domain.organization import InvalidPatientIdentityError
from app.models.account import Account
from app.models.medical_record import MedicalRecord
from app.models.patient import Patient
from app.models.person import Person
from app.repositories.account import AccountRepository
from app.services.patient_resolver import OrganizationPatientResolver
from sqlalchemy import func, select


async def test_resolves_new_email_creating_pending_account_and_medical_record(
    db_session,
):
    resolver = OrganizationPatientResolver(db_session)

    resolved = await resolver.resolve_by_email("anna@clinic.example")

    assert resolved.patient_id is not None
    account = await db_session.scalar(
        select(Account).where(Account.email_normalized == "anna@clinic.example")
    )
    assert account is not None
    assert account.status.value == "pending"
    persons = await db_session.scalar(select(func.count()).select_from(Person))
    patients = await db_session.scalar(select(func.count()).select_from(Patient))
    records = await db_session.scalar(select(func.count()).select_from(MedicalRecord))
    assert persons == 1
    assert patients == 1
    assert records == 1


async def test_resolve_is_idempotent_for_same_email(db_session):
    resolver = OrganizationPatientResolver(db_session)

    first = await resolver.resolve_by_email("anna@clinic.example")
    second = await resolver.resolve_by_email("anna@clinic.example")

    assert first.patient_id == second.patient_id
    assert first.medical_record_id == second.medical_record_id
    assert first.account_id == second.account_id
    accounts = await db_session.scalar(select(func.count()).select_from(Account))
    patients = await db_session.scalar(select(func.count()).select_from(Patient))
    assert accounts == 1
    assert patients == 1


async def test_resolve_normalizes_email_case_and_whitespace(db_session):
    resolver = OrganizationPatientResolver(db_session)

    resolved = await resolver.resolve_by_email("  Anna@Clinic.EXAMPLE  ")

    account = await db_session.scalar(
        select(Account).where(Account.email_normalized == "anna@clinic.example")
    )
    assert account.id == resolved.account_id
    assert account.email == "anna@clinic.example"


async def test_resolve_reuses_existing_account(db_session):
    existing = Account(
        id=uuid4(),
        email="known@clinic.example",
        email_normalized="known@clinic.example",
    )
    db_session.add(existing)
    await db_session.flush()

    resolver = OrganizationPatientResolver(db_session)
    resolved = await resolver.resolve_by_email("known@clinic.example")

    assert resolved.account_id == existing.id
    accounts = await db_session.scalar(select(func.count()).select_from(Account))
    assert accounts == 1


async def test_resolve_rejects_phone_identity(db_session):
    resolver = OrganizationPatientResolver(db_session)

    with pytest.raises(InvalidPatientIdentityError):
        await resolver.resolve_by_email("+79991234567")


async def test_resolve_rejects_malformed_identity(db_session):
    resolver = OrganizationPatientResolver(db_session)

    with pytest.raises(InvalidPatientIdentityError):
        await resolver.resolve_by_email("not-an-identity")


async def test_resolve_distinct_emails_get_distinct_patients(db_session):
    resolver = OrganizationPatientResolver(db_session)

    a = await resolver.resolve_by_email("anna@clinic.example")
    b = await resolver.resolve_by_email("boris@clinic.example")

    assert a.patient_id != b.patient_id
    assert a.account_id != b.account_id


async def test_account_creation_race_recovers(db_factory, monkeypatch):
    async with db_factory() as seeder:
        existing = Account(
            id=uuid4(),
            email="race@clinic.example",
            email_normalized="race@clinic.example",
        )
        seeder.add(existing)
        await seeder.commit()

    original = AccountRepository.get_by_identity
    calls = {"n": 0}

    async def flaky_get(self, identity):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return await original(self, identity)

    monkeypatch.setattr(AccountRepository, "get_by_identity", flaky_get)

    async with db_factory() as session:
        resolver = OrganizationPatientResolver(session)
        resolved = await resolver.resolve_by_email("race@clinic.example")

    assert resolved.account_id == existing.id
    assert calls["n"] == 2
    accounts = await session.scalar(select(func.count()).select_from(Account))
    assert accounts == 1