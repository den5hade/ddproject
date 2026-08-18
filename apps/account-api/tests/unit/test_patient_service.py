from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.domain.access import GrantStatus
from app.domain.medical import (
    PatientAlreadyExistsError,
    Sex,
)
from app.models.access_grant import PatientAccessGrant
from app.models.account import Account
from app.models.medical_record import MedicalRecord
from app.models.patient import Patient
from app.models.person import Person
from app.schemas.patient import PatientCreateRequest
from app.schemas.profile import PersonUpdate
from app.services.patient import PatientService


async def _account(db_session) -> Account:
    account = Account(id=uuid4())
    db_session.add(account)
    await db_session.flush()
    return account


async def _grant(db_session, patient_id, account_id, **kwargs) -> PatientAccessGrant:
    grant = PatientAccessGrant(patient_id=patient_id, account_id=account_id, **kwargs)
    db_session.add(grant)
    await db_session.commit()
    return grant


async def test_ensure_patient_for_account_is_idempotent(db_session):
    service = PatientService(db_session)
    account = await _account(db_session)

    first = await service.ensure_patient_for_account(account)
    second = await service.ensure_patient_for_account(account)

    assert first.patient.id == second.patient.id
    assert first.person.id == account.person_id

    persons = await db_session.scalar(select(func.count()).select_from(Person))
    patients = await db_session.scalar(select(func.count()).select_from(Patient))
    records = await db_session.scalar(select(func.count()).select_from(MedicalRecord))
    assert persons == 1
    assert patients == 1
    assert records == 1


async def test_patient_implies_medical_record(db_session):
    service = PatientService(db_session)
    account = await _account(db_session)

    context = await service.create_patient(account)

    count = await db_session.scalar(
        select(func.count())
        .select_from(MedicalRecord)
        .where(MedicalRecord.patient_id == context.patient.id)
    )
    assert count == 1


async def test_create_patient_twice_raises(db_session):
    service = PatientService(db_session)
    account = await _account(db_session)
    await service.create_patient(account)

    with pytest.raises(PatientAlreadyExistsError):
        await service.create_patient(account)


async def test_create_patient_applies_person_data(db_session):
    service = PatientService(db_session)
    account = await _account(db_session)

    context = await service.create_patient(
        account,
        PatientCreateRequest(
            person=PersonUpdate(
                first_name="Anna",
                last_name="Smith",
                middle_name="V.",
                date_of_birth=date(1990, 1, 1),
                sex=Sex.FEMALE,
            )
        ),
    )
    assert context.person.first_name == "Anna"
    assert context.person.last_name == "Smith"
    assert context.person.middle_name == "V."
    assert context.person.date_of_birth == date(1990, 1, 1)
    assert context.person.sex == Sex.FEMALE


async def test_update_person_persists_and_clears_nullable(db_session):
    service = PatientService(db_session)
    account = await _account(db_session)

    context = await service.update_person(
        account, PersonUpdate(first_name="Alex", date_of_birth=date(1995, 5, 5))
    )
    assert context.person.first_name == "Alex"
    assert context.person.date_of_birth == date(1995, 5, 5)

    context = await service.update_person(account, PersonUpdate(date_of_birth=None))
    assert context.person.first_name == "Alex"
    assert context.person.date_of_birth is None

    person = await db_session.get(Person, context.person.id)
    assert person.date_of_birth is None
    assert person.first_name == "Alex"


async def test_get_patient_for_view_owner(db_session):
    service = PatientService(db_session)
    account = await _account(db_session)
    context = await service.ensure_patient_for_account(account)

    viewed = await service.get_patient_for_view(account, context.patient.id)
    assert viewed is not None
    assert viewed.patient.id == context.patient.id


async def test_get_patient_for_view_hides_from_stranger(db_session):
    service = PatientService(db_session)
    account = await _account(db_session)
    stranger = await _account(db_session)
    context = await service.ensure_patient_for_account(account)

    assert await service.get_patient_for_view(stranger, context.patient.id) is None


async def test_get_patient_for_view_unknown_patient_returns_none(db_session):
    service = PatientService(db_session)
    account = await _account(db_session)

    assert await service.get_patient_for_view(account, uuid4()) is None


async def test_get_patient_for_view_active_grant(db_session):
    service = PatientService(db_session)
    owner = await _account(db_session)
    specialist = await _account(db_session)
    context = await service.ensure_patient_for_account(owner)

    await _grant(db_session, context.patient.id, specialist.id, status=GrantStatus.ACTIVE)

    viewed = await service.get_patient_for_view(specialist, context.patient.id)
    assert viewed is not None


async def test_get_patient_for_view_revoked_or_expired_grant(db_session):
    service = PatientService(db_session)
    owner = await _account(db_session)
    context = await service.ensure_patient_for_account(owner)

    revoked_specialist = await _account(db_session)
    await _grant(
        db_session,
        context.patient.id,
        revoked_specialist.id,
        status=GrantStatus.REVOKED,
    )
    assert (
        await service.get_patient_for_view(revoked_specialist, context.patient.id)
        is None
    )

    expired_specialist = await _account(db_session)
    await _grant(
        db_session,
        context.patient.id,
        expired_specialist.id,
        status=GrantStatus.ACTIVE,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    assert (
        await service.get_patient_for_view(expired_specialist, context.patient.id)
        is None
    )