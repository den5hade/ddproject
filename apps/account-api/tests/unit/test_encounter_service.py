from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.domain.medical import (
    EncounterNotFoundError,
    EncounterStatus,
    EncounterType,
)
from app.models.access_grant import PatientAccessGrant
from app.models.account import Account
from app.models.organization import MembershipStatus, Organization, OrganizationMembership
from app.models.person import Person
from app.models.specialist import Specialist
from app.schemas.encounter import EncounterCreate, EncounterUpdate
from app.services.encounter import EncounterService
from app.services.patient import PatientService


async def _account(db_session) -> Account:
    account = Account(id=uuid4())
    db_session.add(account)
    await db_session.flush()
    return account


async def _specialist_account(db_session) -> tuple[Account, Specialist]:
    person = Person()
    db_session.add(person)
    await db_session.flush()
    account = Account(id=uuid4(), person_id=person.id)
    db_session.add(account)
    specialist = Specialist(person_id=person.id)
    db_session.add(specialist)
    await db_session.flush()
    return account, specialist


async def _patient(db_session, account: Account):
    return (await PatientService(db_session).ensure_patient_for_account(account)).patient


async def _grant(db_session, patient_id, account_id, **kwargs) -> PatientAccessGrant:
    grant = PatientAccessGrant(patient_id=patient_id, account_id=account_id, **kwargs)
    db_session.add(grant)
    await db_session.commit()
    return grant


def _create_data(**overrides) -> EncounterCreate:
    defaults = {
        "type": EncounterType.CONSULTATION,
        "started_at": datetime.now(UTC),
        "reason": "headache",
    }
    defaults.update(overrides)
    return EncounterCreate(**defaults)


async def test_create_encounter_as_owner(db_session):
    service = EncounterService(db_session)
    owner = await _account(db_session)
    patient = await _patient(db_session, owner)

    encounter = await service.create_encounter(owner, patient.id, _create_data())

    assert encounter.status == EncounterStatus.SCHEDULED
    assert encounter.type == EncounterType.CONSULTATION
    assert encounter.reason == "headache"
    assert encounter.specialist_id is None
    assert encounter.organization_id is None


async def test_create_encounter_specialist_with_grant(db_session):
    service = EncounterService(db_session)
    owner = await _account(db_session)
    specialist, specialist_row = await _specialist_account(db_session)
    patient = await _patient(db_session, owner)
    await _grant(db_session, patient.id, specialist.id, can_create_encounters=True)

    encounter = await service.create_encounter(
        specialist, patient.id, _create_data(summary="severe")
    )

    assert encounter.specialist_id == specialist_row.id
    assert encounter.summary == "severe"


async def test_create_encounter_unknown_patient_raises(db_session):
    service = EncounterService(db_session)
    owner = await _account(db_session)

    with pytest.raises(EncounterNotFoundError):
        await service.create_encounter(owner, uuid4(), _create_data())


async def test_create_encounter_fills_organization_from_membership(db_session):
    service = EncounterService(db_session)
    owner = await _account(db_session)
    specialist, _ = await _specialist_account(db_session)
    patient = await _patient(db_session, owner)
    await _grant(db_session, patient.id, specialist.id, can_create_encounters=True)

    org = Organization(name="City Clinic", type="clinic")
    db_session.add(org)
    await db_session.flush()
    db_session.add(
        OrganizationMembership(
            organization_id=org.id,
            account_id=specialist.id,
            status=MembershipStatus.ACTIVE,
        )
    )
    await db_session.commit()

    encounter = await service.create_encounter(specialist, patient.id, _create_data())

    assert encounter.organization_id == org.id


async def test_list_encounters_owner(db_session):
    service = EncounterService(db_session)
    owner = await _account(db_session)
    patient = await _patient(db_session, owner)
    await service.create_encounter(owner, patient.id, _create_data())
    await service.create_encounter(owner, patient.id, _create_data(reason="second"))

    encounters = await service.list_encounters(patient.id)

    assert len(encounters) == 2


async def test_list_encounters_specialist_with_grant(db_session):
    service = EncounterService(db_session)
    owner = await _account(db_session)
    specialist, _ = await _specialist_account(db_session)
    patient = await _patient(db_session, owner)
    await service.create_encounter(owner, patient.id, _create_data())
    await _grant(db_session, patient.id, specialist.id)

    encounters = await service.list_encounters(patient.id)

    assert len(encounters) == 1


async def test_get_encounter_owner(db_session):
    service = EncounterService(db_session)
    owner = await _account(db_session)
    patient = await _patient(db_session, owner)
    created = await service.create_encounter(owner, patient.id, _create_data())

    encounter = await service.get_encounter(created.id)

    assert encounter.id == created.id


async def test_get_encounter_grant_recipient(db_session):
    service = EncounterService(db_session)
    owner = await _account(db_session)
    specialist, _ = await _specialist_account(db_session)
    patient = await _patient(db_session, owner)
    created = await service.create_encounter(owner, patient.id, _create_data())
    await _grant(db_session, patient.id, specialist.id)

    encounter = await service.get_encounter(created.id)

    assert encounter.id == created.id


async def test_get_encounter_not_found(db_session):
    service = EncounterService(db_session)

    with pytest.raises(EncounterNotFoundError):
        await service.get_encounter(uuid4())


async def test_update_encounter_owner(db_session):
    service = EncounterService(db_session)
    owner = await _account(db_session)
    patient = await _patient(db_session, owner)
    created = await service.create_encounter(owner, patient.id, _create_data())

    updated = await service.update_encounter(
        created.id,
        EncounterUpdate(status=EncounterStatus.COMPLETED, summary="done"),
    )

    assert updated.status == EncounterStatus.COMPLETED
    assert updated.summary == "done"


async def test_update_encounter_with_edit_grant(db_session):
    service = EncounterService(db_session)
    owner = await _account(db_session)
    specialist, _ = await _specialist_account(db_session)
    patient = await _patient(db_session, owner)
    created = await service.create_encounter(owner, patient.id, _create_data())
    await _grant(db_session, patient.id, specialist.id, can_edit_medical_data=True)

    updated = await service.update_encounter(
        created.id, EncounterUpdate(status=EncounterStatus.CANCELLED)
    )

    assert updated.status == EncounterStatus.CANCELLED
