from datetime import date, timedelta
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
    BranchStatus,
    OrganizationBranchConflictError,
    OrganizationBranchNotFoundError,
    OrganizationLegalDataConflictError,
    OrganizationLicenseConflictError,
    OrganizationLicenseNotFoundError,
    OrganizationLicenseStatus,
    OrganizationNotFoundError,
    OrganizationVerificationStatus,
)
from app.models.audit_log import AuditLog
from app.models.organization import Organization, OrganizationBranch, OrganizationLicense
from app.schemas.organization import (
    BranchCreate,
    BranchUpdate,
    LicenseCreate,
    LicenseUpdate,
    OrganizationUpdate,
)
from app.services.organization import OrganizationService

REPO_ROOT = Path(__file__).resolve().parents[4]


def _load_migration_0006():
    path = REPO_ROOT / "migrations/alembic/versions/0006_organization_legal_data.py"
    spec = spec_from_file_location("migration_0006", path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_migration_0007():
    path = REPO_ROOT / "migrations/alembic/versions/0007_organization_branches.py"
    spec = spec_from_file_location("migration_0007", path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_migration_0008():
    path = REPO_ROOT / "migrations/alembic/versions/0008_organization_licenses.py"
    spec = spec_from_file_location("migration_0008", path)
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


async def _branch(db_session, org: Organization, **fields) -> OrganizationBranch:
    branch = OrganizationBranch(
        organization_id=org.id,
        code=fields.pop("code", "br-1"),
        name=fields.pop("name", "Main Branch"),
        **fields,
    )
    db_session.add(branch)
    await db_session.commit()
    return branch


async def test_create_branch(db_session) -> None:
    org = await _org(db_session)
    service = OrganizationService(db_session)
    branch = await service.create_branch(
        org.id, uuid4(), BranchCreate(code="br-9", name="East", address="prosp. 1")
    )
    assert branch.organization_id == org.id
    assert branch.code == "br-9"
    assert branch.name == "East"
    assert branch.address == "prosp. 1"
    assert branch.status == BranchStatus.ACTIVE


async def test_create_branch_duplicate_code_conflict(db_session) -> None:
    org = await _org(db_session)
    await _branch(db_session, org, code="br-1")
    service = OrganizationService(db_session)
    with pytest.raises(OrganizationBranchConflictError):
        await service.create_branch(org.id, uuid4(), BranchCreate(code="br-1", name="Dup"))


async def test_create_branch_same_code_in_different_org_ok(db_session) -> None:
    org_a = await _org(db_session)
    org_b = await _org(db_session)
    service = OrganizationService(db_session)
    await service.create_branch(org_a.id, uuid4(), BranchCreate(code="br-1", name="A"))
    branch_b = await service.create_branch(
        org_b.id, uuid4(), BranchCreate(code="br-1", name="B")
    )
    assert branch_b.organization_id == org_b.id


async def test_list_branches(db_session) -> None:
    org = await _org(db_session)
    await _branch(db_session, org, code="br-2", name="Two")
    await _branch(db_session, org, code="br-1", name="One")
    service = OrganizationService(db_session)
    branches = await service.list_branches(org.id)
    assert [b.code for b in branches] == ["br-2", "br-1"]


async def test_get_branch_not_found(db_session) -> None:
    org = await _org(db_session)
    service = OrganizationService(db_session)
    with pytest.raises(OrganizationBranchNotFoundError):
        await service.get_branch(org.id, uuid4())


async def test_get_branch_is_org_scoped(db_session) -> None:
    org_a = await _org(db_session)
    org_b = await _org(db_session)
    branch = await _branch(db_session, org_a, code="br-1")
    service = OrganizationService(db_session)
    with pytest.raises(OrganizationBranchNotFoundError):
        await service.get_branch(org_b.id, branch.id)


async def test_update_branch(db_session) -> None:
    org = await _org(db_session)
    branch = await _branch(db_session, org, code="br-1", name="Main")
    service = OrganizationService(db_session)
    updated = await service.update_branch(
        org.id, branch.id, uuid4(), BranchUpdate(name="HQ", phone="+7")
    )
    assert updated.name == "HQ"
    assert updated.phone == "+7"
    assert updated.code == "br-1"


async def test_update_branch_duplicate_code_conflict(db_session) -> None:
    org = await _org(db_session)
    await _branch(db_session, org, code="br-1", name="One")
    branch = await _branch(db_session, org, code="br-2", name="Two")
    service = OrganizationService(db_session)
    with pytest.raises(OrganizationBranchConflictError):
        await service.update_branch(org.id, branch.id, uuid4(), BranchUpdate(code="br-1"))


async def test_update_branch_clears_address(db_session) -> None:
    org = await _org(db_session)
    branch = await _branch(db_session, org, code="br-1", address="Somewhere")
    service = OrganizationService(db_session)
    updated = await service.update_branch(org.id, branch.id, uuid4(), BranchUpdate(address=""))
    assert updated.address is None


async def test_deactivate_branch_sets_inactive_and_keeps_history(db_session) -> None:
    org = await _org(db_session)
    branch = await _branch(db_session, org, code="br-1")
    service = OrganizationService(db_session)
    await service.deactivate_branch(org.id, branch.id, uuid4())
    fetched = await service.get_branch(org.id, branch.id)
    assert fetched.status == BranchStatus.INACTIVE
    assert [b.id for b in await service.list_branches(org.id)] == [branch.id]


async def test_deactivate_branch_not_found(db_session) -> None:
    org = await _org(db_session)
    service = OrganizationService(db_session)
    with pytest.raises(OrganizationBranchNotFoundError):
        await service.deactivate_branch(org.id, uuid4(), uuid4())


async def test_branch_operations_write_audit_log(db_session) -> None:
    org = await _org(db_session)
    actor = uuid4()
    service = OrganizationService(db_session)
    branch = await service.create_branch(org.id, actor, BranchCreate(code="br-1", name="Main"))
    await service.update_branch(org.id, branch.id, actor, BranchUpdate(name="HQ"))
    await service.deactivate_branch(org.id, branch.id, actor)
    rows = (await db_session.execute(sa.select(AuditLog))).scalars().all()
    actions = [row.action for row in rows]
    assert AuditAction.ORGANIZATION_BRANCH_CREATED in actions
    assert AuditAction.ORGANIZATION_BRANCH_UPDATED in actions
    assert AuditAction.ORGANIZATION_BRANCH_DEACTIVATED in actions


def test_migration_0007_revision_wiring() -> None:
    migration = _load_migration_0007()
    assert migration.revision == "0007"
    assert migration.down_revision == "0006"


def test_migration_0007_upgrade_downgrade_round_trip() -> None:
    migration = _load_migration_0007()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                """
                CREATE TABLE organizations (
                    id VARCHAR(32) PRIMARY KEY,
                    name VARCHAR(255) NOT NULL
                )
                """
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO organizations (id, name) VALUES ('1', 'City Clinic')"
            )
        )

    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration.upgrade()
        tables = {
            row[0]
            for row in conn.execute(
                sa.text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        }
        assert "organization_branches" in tables
        columns = {
            row[1]
            for row in conn.execute(sa.text("PRAGMA table_info(organization_branches)"))
        }
        assert {
            "id",
            "organization_id",
            "code",
            "name",
            "address",
            "phone",
            "status",
            "created_at",
            "updated_at",
        } <= columns
        indexes = {
            row[1]
            for row in conn.execute(sa.text("PRAGMA index_list(organization_branches)"))
        }
        assert "uq_organization_branches_org_code" in indexes
        conn.execute(
            sa.text(
                "INSERT INTO organization_branches (id, organization_id, code, name,"
                " status, created_at, updated_at)"
                " VALUES ('b1', '1', 'br-1', 'Main', 'active', '2026-01-01', '2026-01-01')"
            )
        )
        assert (
            conn.execute(
                sa.text("SELECT status FROM organization_branches WHERE id = 'b1'")
            ).scalar_one()
            == "active"
        )

        with Operations.context(ctx):
            migration.downgrade()
        tables_after = {
            row[0]
            for row in conn.execute(
                sa.text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        }
        assert "organization_branches" not in tables_after


async def _license(db_session, org: Organization, **fields) -> OrganizationLicense:
    license = OrganizationLicense(
        organization_id=org.id,
        license_number=fields.pop("license_number", "L-77-00001"),
        license_type=fields.pop("license_type", "терапия"),
        **fields,
    )
    db_session.add(license)
    await db_session.commit()
    return license


async def test_create_license(db_session) -> None:
    org = await _org(db_session)
    service = OrganizationService(db_session)
    license = await service.create_license(
        org.id,
        uuid4(),
        LicenseCreate(
            license_number="ЛО-77-01-000001",
            license_type="стоматология",
            issued_at=date(2026, 1, 10),
            expires_at=date(2031, 1, 10),
            scope="амбулаторно-поликлиническая",
            issuer="Росздравнадзор",
        ),
    )
    assert license.organization_id == org.id
    assert license.license_number == "ЛО-77-01-000001"
    assert license.license_type == "стоматология"
    assert license.status == OrganizationLicenseStatus.ACTIVE
    assert license.issued_at == date(2026, 1, 10)
    assert license.issuer == "Росздравнадзор"


async def test_create_license_duplicate_number_conflict(db_session) -> None:
    org = await _org(db_session)
    await _license(db_session, org, license_number="ЛО-77-01-000001")
    service = OrganizationService(db_session)
    with pytest.raises(OrganizationLicenseConflictError):
        await service.create_license(
            org.id, uuid4(), LicenseCreate(license_number="ЛО-77-01-000001", license_type="x")
        )


async def test_create_license_same_number_in_different_org_ok(db_session) -> None:
    org_a = await _org(db_session)
    org_b = await _org(db_session)
    service = OrganizationService(db_session)
    license_a = await service.create_license(
        org_a.id, uuid4(), LicenseCreate(license_number="ЛО-77-01-000001", license_type="x")
    )
    license_b = await service.create_license(
        org_b.id, uuid4(), LicenseCreate(license_number="ЛО-77-01-000001", license_type="y")
    )
    assert license_a.organization_id == org_a.id
    assert license_b.organization_id == org_b.id


async def test_license_schema_rejects_expires_before_issued(db_session) -> None:
    with pytest.raises(ValueError):
        LicenseCreate(
            license_number="ЛО-77-01-000002",
            license_type="x",
            issued_at=date(2031, 1, 10),
            expires_at=date(2026, 1, 10),
        )


async def test_list_licenses(db_session) -> None:
    org = await _org(db_session)
    await _license(db_session, org, license_number="ЛО-77-01-000002")
    await _license(db_session, org, license_number="ЛО-77-01-000001")
    service = OrganizationService(db_session)
    licenses = await service.list_licenses(org.id)
    assert [license.license_number for license in licenses] == [
        "ЛО-77-01-000002",
        "ЛО-77-01-000001",
    ]


async def test_get_license_not_found(db_session) -> None:
    org = await _org(db_session)
    service = OrganizationService(db_session)
    with pytest.raises(OrganizationLicenseNotFoundError):
        await service.get_license(org.id, uuid4())


async def test_get_license_is_org_scoped(db_session) -> None:
    org_a = await _org(db_session)
    org_b = await _org(db_session)
    license = await _license(db_session, org_a)
    service = OrganizationService(db_session)
    with pytest.raises(OrganizationLicenseNotFoundError):
        await service.get_license(org_b.id, license.id)


async def test_update_license(db_session) -> None:
    org = await _org(db_session)
    license = await _license(db_session, org, scope="уро.логия")
    service = OrganizationService(db_session)
    updated = await service.update_license(
        org.id, license.id, uuid4(), LicenseUpdate(scope="урология", issuer="Росздравнадзор")
    )
    assert updated.scope == "урология"
    assert updated.issuer == "Росздравнадзор"
    assert updated.license_number == license.license_number


async def test_update_license_duplicate_number_conflict(db_session) -> None:
    org = await _org(db_session)
    await _license(db_session, org, license_number="ЛО-77-01-000001")
    license = await _license(db_session, org, license_number="ЛО-77-01-000002")
    service = OrganizationService(db_session)
    with pytest.raises(OrganizationLicenseConflictError):
        await service.update_license(
            org.id, license.id, uuid4(), LicenseUpdate(license_number="ЛО-77-01-000001")
        )


async def test_update_license_clears_scope(db_session) -> None:
    org = await _org(db_session)
    license = await _license(db_session, org, scope="урология")
    service = OrganizationService(db_session)
    updated = await service.update_license(org.id, license.id, uuid4(), LicenseUpdate(scope=""))
    assert updated.scope is None


async def test_update_license_manual_status_change(db_session) -> None:
    org = await _org(db_session)
    license = await _license(db_session, org)
    service = OrganizationService(db_session)
    updated = await service.update_license(
        org.id,
        license.id,
        uuid4(),
        LicenseUpdate(status=OrganizationLicenseStatus.SUSPENDED),
    )
    assert updated.status == OrganizationLicenseStatus.SUSPENDED


async def test_deactivate_license_sets_revoked_and_keeps_history(db_session) -> None:
    org = await _org(db_session)
    license = await _license(db_session, org)
    service = OrganizationService(db_session)
    await service.deactivate_license(org.id, license.id, uuid4())
    fetched = await service.get_license(org.id, license.id)
    assert fetched.status == OrganizationLicenseStatus.REVOKED
    assert [licence.id for licence in await service.list_licenses(org.id)] == [license.id]


async def test_deactivate_license_not_found(db_session) -> None:
    org = await _org(db_session)
    service = OrganizationService(db_session)
    with pytest.raises(OrganizationLicenseNotFoundError):
        await service.deactivate_license(org.id, uuid4(), uuid4())


async def test_overdue_active_license_expires_on_list(db_session) -> None:
    org = await _org(db_session)
    await _license(
        db_session,
        org,
        license_number="ЛО-77-01-000001",
        expires_at=date.today() - timedelta(days=1),
    )
    await _license(
        db_session,
        org,
        license_number="ЛО-77-01-000002",
        expires_at=date.today() + timedelta(days=30),
    )
    service = OrganizationService(db_session)
    licenses = await service.list_licenses(org.id)
    by_number = {license.license_number: license.status for license in licenses}
    assert by_number["ЛО-77-01-000001"] == OrganizationLicenseStatus.EXPIRED
    assert by_number["ЛО-77-01-000002"] == OrganizationLicenseStatus.ACTIVE


async def test_overdue_active_license_expires_on_get(db_session) -> None:
    org = await _org(db_session)
    license = await _license(
        db_session, org, expires_at=date.today() - timedelta(days=1)
    )
    service = OrganizationService(db_session)
    fetched = await service.get_license(org.id, license.id)
    assert fetched.status == OrganizationLicenseStatus.EXPIRED


async def test_active_license_without_expiry_is_not_expired(db_session) -> None:
    org = await _org(db_session)
    await _license(db_session, org, expires_at=None)
    service = OrganizationService(db_session)
    licenses = await service.list_licenses(org.id)
    assert len(licenses) == 1
    assert licenses[0].status == OrganizationLicenseStatus.ACTIVE


async def test_license_operations_write_audit_log(db_session) -> None:
    org = await _org(db_session)
    actor = uuid4()
    service = OrganizationService(db_session)
    license = await service.create_license(
        org.id, actor, LicenseCreate(license_number="ЛО-77-01-000001", license_type="x")
    )
    await service.update_license(org.id, license.id, actor, LicenseUpdate(scope="x"))
    await service.deactivate_license(org.id, license.id, actor)
    rows = (await db_session.execute(sa.select(AuditLog))).scalars().all()
    actions = [row.action for row in rows]
    assert AuditAction.ORGANIZATION_LICENSE_CREATED in actions
    assert AuditAction.ORGANIZATION_LICENSE_UPDATED in actions
    assert AuditAction.ORGANIZATION_LICENSE_DEACTIVATED in actions


def test_migration_0008_revision_wiring() -> None:
    migration = _load_migration_0008()
    assert migration.revision == "0008"
    assert migration.down_revision == "0007"


def test_migration_0008_upgrade_downgrade_round_trip() -> None:
    migration = _load_migration_0008()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                """
                CREATE TABLE organizations (
                    id VARCHAR(32) PRIMARY KEY,
                    name VARCHAR(255) NOT NULL
                )
                """
            )
        )
        conn.execute(
            sa.text("INSERT INTO organizations (id, name) VALUES ('1', 'City Clinic')")
        )

    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration.upgrade()
        tables = {
            row[0]
            for row in conn.execute(
                sa.text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        }
        assert "organization_licenses" in tables
        columns = {
            row[1]
            for row in conn.execute(sa.text("PRAGMA table_info(organization_licenses)"))
        }
        assert {
            "id",
            "organization_id",
            "license_number",
            "license_type",
            "status",
            "issued_at",
            "expires_at",
            "scope",
            "issuer",
            "created_at",
            "updated_at",
        } <= columns
        indexes = {
            row[1]
            for row in conn.execute(sa.text("PRAGMA index_list(organization_licenses)"))
        }
        assert "uq_organization_licenses_org_number" in indexes
        conn.execute(
            sa.text(
                "INSERT INTO organization_licenses (id, organization_id, license_number,"
                " license_type, status, created_at, updated_at)"
                " VALUES ('l1', '1', 'ЛО-77-01-000001', 'терапия', 'active',"
                " '2026-01-01', '2026-01-01')"
            )
        )
        assert (
            conn.execute(
                sa.text("SELECT status FROM organization_licenses WHERE id = 'l1'")
            ).scalar_one()
            == "active"
        )
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO organization_licenses (id, organization_id, license_number,"
                    " license_type, status, created_at, updated_at)"
                    " VALUES ('l2', '1', 'ЛО-77-01-000001', 'терапия', 'active',"
                    " '2026-01-01', '2026-01-01')"
                )
            )

        with Operations.context(ctx):
            migration.downgrade()
        tables_after = {
            row[0]
            for row in conn.execute(
                sa.text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        }
        assert "organization_licenses" not in tables_after