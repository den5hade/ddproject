from datetime import date
from uuid import uuid4

import pytest
from app.domain.medical import (
    PatientAlreadyExistsError,
    Sex,
)
from app.models.account import Account
from app.models.medical_record import MedicalRecord
from app.models.patient import Patient
from app.models.person import Person
from app.schemas.patient import PatientCreateRequest
from app.schemas.profile import PersonUpdate
from app.services.patient import PatientService
from sqlalchemy import func, select


async def _account(db_session) -> Account:
    account = Account(id=uuid4())
    db_session.add(account)
    await db_session.flush()
    return account


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