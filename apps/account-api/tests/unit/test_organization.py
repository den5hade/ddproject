from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.domain.access import AuditAction
from app.domain.medical import OrganizationType
from app.domain.organization import (
    OrganizationLegalDataConflictError,
    OrganizationNotFoundError,
    OrganizationVerificationStatus,
)
from app.models.audit_log import AuditLog
from app.models.organization import Organization
from app.schemas.organization import OrganizationUpdate
from app.services.organization import OrganizationService

REPO_ROOT = Path(__file__).resolve().parents[4]


def _load_migration_0006():
    path = REPO_ROOT / "migrations/alembic/versions/0006_organization_legal_data.py"
    spec = spec_from_file_location("migration_0006", path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


async def _org(db_session, **fields) -> Organization:
    org = Organization(name="City Clinic", type=OrganizationType.CLINIC, **fields)
    db_session.add(org)
    await db_session.commit()
    return org


async def test_update_name_only_keeps_unverified(db_session) -> None:
    org = await _org(db_session)
    service = OrganizationService(db_session)
    updated = await service.update_organization(
        org.id, uuid4(), OrganizationUpdate(name="New Name")
    )
    assert updated.name == "New Name"
    assert updated.verification_status == OrganizationVerificationStatus.UNVERIFIED


async def test_update_legal_data_sets_pending(db_session) -> None:
    org = await _org(db_session)
    service = OrganizationService(db_session)
    updated = await service.update_organization(
        org.id,
        uuid4(),
        OrganizationUpdate(inn="7707083893", legal_address="ул. Ленина, 1"),
    )
    assert updated.inn == "7707083893"
    assert updated.legal_address == "ул. Ленина, 1"
    assert updated.verification_status == OrganizationVerificationStatus.PENDING


async def test_clearing_legal_field_sets_pending(db_session) -> None:
    org = await _org(db_session, inn="7707083893")
    service = OrganizationService(db_session)
    updated = await service.update_organization(org.id, uuid4(), OrganizationUpdate(inn=""))
    assert updated.inn is None
    assert updated.verification_status == OrganizationVerificationStatus.PENDING


async def test_update_not_found(db_session) -> None:
    service = OrganizationService(db_session)
    with pytest.raises(OrganizationNotFoundError):
        await service.update_organization(uuid4(), uuid4(), OrganizationUpdate(name="x"))


async def test_update_duplicate_inn_conflict(db_session) -> None:
    await _org(db_session, inn="7707083893")
    other = await _org(db_session)
    service = OrganizationService(db_session)
    with pytest.raises(OrganizationLegalDataConflictError):
        await service.update_organization(
            other.id, uuid4(), OrganizationUpdate(inn="7707083893")
        )


async def test_duplicate_ogrn_conflict(db_session) -> None:
    await _org(db_session, ogrn="1027700132195")
    other = await _org(db_session)
    service = OrganizationService(db_session)
    with pytest.raises(OrganizationLegalDataConflictError):
        await service.update_organization(
            other.id, uuid4(), OrganizationUpdate(ogrn="1027700132195")
        )


async def test_resending_own_inn_is_allowed(db_session) -> None:
    org = await _org(db_session, inn="7707083893", ogrn="1027700132195")
    service = OrganizationService(db_session)
    updated = await service.update_organization(
        org.id, uuid4(), OrganizationUpdate(inn="7707083893")
    )
    assert updated.inn == "7707083893"


async def test_update_writes_audit_log(db_session) -> None:
    org = await _org(db_session)
    actor = uuid4()
    service = OrganizationService(db_session)
    await service.update_organization(org.id, actor, OrganizationUpdate(website="https://x.example"))
    rows = (await db_session.execute(sa.select(AuditLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].action == AuditAction.ORGANIZATION_UPDATED
    assert rows[0].actor_account_id == actor
    assert rows[0].resource_id == org.id
    assert rows[0].metadata_["fields"] == ["website"]


def test_migration_0006_revision_wiring() -> None:
    migration = _load_migration_0006()
    assert migration.revision == "0006"
    assert migration.down_revision == "0005"


def test_migration_0006_upgrade_downgrade_round_trip() -> None:
    migration = _load_migration_0006()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                """
                CREATE TABLE organizations (
                    id VARCHAR(32) PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    type VARCHAR(32) NOT NULL,
                    status VARCHAR(16),
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO organizations (id, name, type, status) "
                "VALUES ('1', 'Legacy Clinic', 'clinic', 'active')"
            )
        )

    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration.upgrade()
        columns = {
            row[1] for row in conn.execute(sa.text("PRAGMA table_info(organizations)"))
        }
        assert {
            "inn",
            "ogrn",
            "legal_address",
            "email",
            "phone",
            "website",
            "verification_status",
        } <= columns
        indexes = {
            row[1] for row in conn.execute(sa.text("PRAGMA index_list(organizations)"))
        }
        assert "uq_organizations_inn" in indexes
        assert "uq_organizations_ogrn" in indexes
        status = conn.execute(
            sa.text("SELECT verification_status FROM organizations WHERE id = '1'")
        ).scalar_one()
        assert status == "UNVERIFIED"

        with Operations.context(ctx):
            migration.downgrade()
        columns_after = {
            row[1] for row in conn.execute(sa.text("PRAGMA table_info(organizations)"))
        }
        assert not {"inn", "verification_status"} & columns_after
        indexes_after = {
            row[1] for row in conn.execute(sa.text("PRAGMA index_list(organizations)"))
        }
        assert "uq_organizations_inn" not in indexes_after
        assert "uq_organizations_ogrn" not in indexes_after