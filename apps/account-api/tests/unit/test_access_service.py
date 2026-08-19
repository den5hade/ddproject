from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.domain.access import (
    AccessReason,
    AuditAction,
    GrantStatus,
    PatientAccessGrantNotFoundError,
)
from app.domain.account import AccountStatus, RoleCode
from app.models.account import Account
from app.repositories.rbac import RbacRepository
from app.schemas.access import AccessGrantCreate, AccessGrantUpdate
from app.services.access import AccessService
from app.services.audit import AuditService
from app.services.patient import PatientService


async def _active_account(db_session) -> Account:
    account = Account(id=uuid4(), status=AccountStatus.ACTIVE)
    db_session.add(account)
    await db_session.flush()
    return account


async def _patient(db_session, owner: Account):
    return (await PatientService(db_session).ensure_patient_for_account(owner)).patient


async def _specialist(db_session) -> Account:
    account = await _active_account(db_session)
    rbac = RbacRepository(db_session)
    await rbac.seed_defaults()
    await rbac.assign_roles(account.id, [RoleCode.SPECIALIST.value])
    await db_session.commit()
    return account


def _create_data(account_id, **overrides) -> AccessGrantCreate:
    defaults = {
        "account_id": account_id,
        "can_view_documents": True,
        "access_reason": AccessReason.TREATMENT,
    }
    defaults.update(overrides)
    return AccessGrantCreate(**defaults)


async def test_grant_creates_active_grant(db_session):
    owner = await _active_account(db_session)
    specialist = await _specialist(db_session)
    patient = await _patient(db_session, owner)
    service = AccessService(db_session)

    grant = await service.grant(
        actor=owner, patient_id=patient.id, data=_create_data(specialist.id)
    )

    assert grant.status == GrantStatus.ACTIVE
    assert grant.can_view_documents is True
    assert grant.can_upload_documents is False
    assert grant.granted_by_account_id == owner.id
    assert grant.access_reason == AccessReason.TREATMENT.value


async def test_grant_writes_audit(db_session):
    owner = await _active_account(db_session)
    specialist = await _specialist(db_session)
    patient = await _patient(db_session, owner)
    service = AccessService(db_session)

    await service.grant(
        actor=owner, patient_id=patient.id, data=_create_data(specialist.id)
    )

    entries = await AuditService(db_session).list_logs(patient_id=patient.id)
    assert len(entries) == 1
    assert entries[0].action == AuditAction.GRANT_ACCESS
    assert entries[0].actor_account_id == owner.id


async def test_update_grant_changes_flags(db_session):
    owner = await _active_account(db_session)
    specialist = await _specialist(db_session)
    patient = await _patient(db_session, owner)
    service = AccessService(db_session)
    grant = await service.grant(
        actor=owner, patient_id=patient.id, data=_create_data(specialist.id)
    )

    updated = await service.update_grant(
        actor=owner,
        patient_id=patient.id,
        grant_id=grant.id,
        data=AccessGrantUpdate(can_upload_documents=True, expires_at=None),
    )

    assert updated.can_upload_documents is True
    assert updated.can_view_documents is True
    assert updated.expires_at is None


async def test_update_grant_not_found_raises(db_session):
    owner = await _active_account(db_session)
    patient = await _patient(db_session, owner)
    service = AccessService(db_session)

    with pytest.raises(PatientAccessGrantNotFoundError):
        await service.update_grant(
            actor=owner,
            patient_id=patient.id,
            grant_id=uuid4(),
            data=AccessGrantUpdate(can_view_documents=True),
        )


async def test_revoke_sets_status_revoked(db_session):
    owner = await _active_account(db_session)
    specialist = await _specialist(db_session)
    patient = await _patient(db_session, owner)
    service = AccessService(db_session)
    grant = await service.grant(
        actor=owner, patient_id=patient.id, data=_create_data(specialist.id)
    )

    revoked = await service.revoke(
        actor=owner, patient_id=patient.id, grant_id=grant.id
    )

    assert revoked.status == GrantStatus.REVOKED
    entries = await AuditService(db_session).list_logs(patient_id=patient.id)
    assert entries[0].action == AuditAction.REVOKE_ACCESS


async def test_revoke_not_found_raises(db_session):
    owner = await _active_account(db_session)
    patient = await _patient(db_session, owner)
    service = AccessService(db_session)

    with pytest.raises(PatientAccessGrantNotFoundError):
        await service.revoke(actor=owner, patient_id=patient.id, grant_id=uuid4())


async def test_list_grants(db_session):
    owner = await _active_account(db_session)
    specialist = await _specialist(db_session)
    patient = await _patient(db_session, owner)
    service = AccessService(db_session)
    await service.grant(
        actor=owner, patient_id=patient.id, data=_create_data(specialist.id)
    )

    grants = await service.list_grants(patient_id=patient.id)

    assert len(grants) == 1
    assert grants[0].account_id == specialist.id


async def test_allows_owner(db_session):
    owner = await _active_account(db_session)
    patient = await _patient(db_session, owner)
    service = AccessService(db_session)

    assert await service.allows(account=owner, patient=patient) is True


async def test_allows_stranger_without_role(db_session):
    owner = await _active_account(db_session)
    stranger = await _active_account(db_session)
    patient = await _patient(db_session, owner)
    service = AccessService(db_session)

    assert await service.allows(account=stranger, patient=patient) is False


async def test_allows_specialist_with_flag(db_session):
    owner = await _active_account(db_session)
    specialist = await _specialist(db_session)
    patient = await _patient(db_session, owner)
    service = AccessService(db_session)
    await service.grant(
        actor=owner,
        patient_id=patient.id,
        data=_create_data(specialist.id),
    )

    assert (
        await service.allows(
            account=specialist, patient=patient, flag="can_view_documents"
        )
        is True
    )


async def test_allows_specialist_missing_flag(db_session):
    owner = await _active_account(db_session)
    specialist = await _specialist(db_session)
    patient = await _patient(db_session, owner)
    service = AccessService(db_session)
    await service.grant(
        actor=owner,
        patient_id=patient.id,
        data=_create_data(specialist.id, can_view_documents=False),
    )

    assert (
        await service.allows(
            account=specialist, patient=patient, flag="can_view_documents"
        )
        is False
    )
    assert await service.allows(account=specialist, patient=patient) is True


async def test_allows_expired_grant(db_session):
    owner = await _active_account(db_session)
    specialist = await _specialist(db_session)
    patient = await _patient(db_session, owner)
    service = AccessService(db_session)
    await service.grant(
        actor=owner,
        patient_id=patient.id,
        data=_create_data(
            specialist.id, expires_at=datetime.now(UTC) - timedelta(days=1)
        ),
    )

    assert await service.allows(account=specialist, patient=patient) is False


async def test_allows_revoked_grant(db_session):
    owner = await _active_account(db_session)
    specialist = await _specialist(db_session)
    patient = await _patient(db_session, owner)
    service = AccessService(db_session)
    grant = await service.grant(
        actor=owner, patient_id=patient.id, data=_create_data(specialist.id)
    )
    await service.revoke(actor=owner, patient_id=patient.id, grant_id=grant.id)

    assert await service.allows(account=specialist, patient=patient) is False


async def test_allows_inactive_account(db_session):
    owner = await _active_account(db_session)
    patient = await _patient(db_session, owner)
    owner.status = AccountStatus.PENDING
    await db_session.commit()
    service = AccessService(db_session)

    assert await service.allows(account=owner, patient=patient) is False
