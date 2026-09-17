from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.domain.access import AuditAction
from app.domain.medical import DocumentType, OrganizationType
from app.domain.organization import (
    OrganizationDocumentSchemaConflictError,
    OrganizationDocumentSchemaImmutableError,
    OrganizationDocumentSchemaNotFoundError,
    OrganizationDocumentSchemaStatus,
)
from app.models.account import Account
from app.models.audit_log import AuditLog
from app.models.organization import Organization, OrganizationDocumentSchema
from app.schemas.organization import (
    OrganizationDocumentSchemaCreate,
    OrganizationDocumentSchemaUpdate,
    validate_schema_definition,
)
from app.services.organization_schema import OrganizationSchemaService

REPO_ROOT = Path(__file__).resolve().parents[4]


def _valid_definition() -> dict:
    return {
        "type": "object",
        "properties": {
            "hemoglobin": {"type": "number"},
            "wbc": {"type": "number"},
        },
    }


async def _org(db_session) -> Organization:
    org = Organization(name="City Clinic", type=OrganizationType.CLINIC)
    db_session.add(org)
    await db_session.commit()
    return org


async def _account(db_session) -> Account:
    account = Account()
    db_session.add(account)
    await db_session.commit()
    return account


async def _create(service, org, actor) -> OrganizationDocumentSchema:
    return await service.create_schema(
        org.id,
        actor,
        OrganizationDocumentSchemaCreate(
            name="lab_blood",
            description="general blood panel",
            schema_definition=_valid_definition(),
        ),
    )


async def test_create_schema_draft_version_one(db_session) -> None:
    org = await _org(db_session)
    actor = await _account(db_session)
    service = OrganizationSchemaService(db_session)
    schema = await _create(service, org, actor.id)
    assert schema.organization_id == org.id
    assert schema.name == "lab_blood"
    assert schema.description == "general blood panel"
    assert schema.document_type == DocumentType.OTHER
    assert schema.schema_definition["type"] == "object"
    assert schema.version == 1
    assert schema.status is OrganizationDocumentSchemaStatus.DRAFT
    assert schema.created_by_account_id == actor.id
    assert schema.published_at is None


async def test_create_schema_duplicate_draft_conflict(db_session) -> None:
    org = await _org(db_session)
    actor = await _account(db_session)
    service = OrganizationSchemaService(db_session)
    await _create(service, org, actor.id)
    with pytest.raises(OrganizationDocumentSchemaConflictError):
        await _create(service, org, actor.id)


async def test_create_schema_same_name_other_org_allowed(db_session) -> None:
    org_a = await _org(db_session)
    org_b = Organization(name="Lab Plus", type=OrganizationType.LABORATORY)
    db_session.add(org_b)
    await db_session.commit()
    actor = await _account(db_session)
    service = OrganizationSchemaService(db_session)
    await _create(service, org_a, actor.id)
    again = await service.create_schema(
        org_b.id,
        actor.id,
        OrganizationDocumentSchemaCreate(
            name="lab_blood", schema_definition=_valid_definition()
        ),
    )
    assert again.organization_id == org_b.id
    assert again.version == 1


async def test_publish_schema(db_session) -> None:
    org = await _org(db_session)
    actor = await _account(db_session)
    service = OrganizationSchemaService(db_session)
    schema = await _create(service, org, actor.id)
    published = await service.publish_schema(org.id, schema.id, actor.id)
    assert published.status is OrganizationDocumentSchemaStatus.PUBLISHED
    assert published.published_at is not None
    assert published.version == 1


async def test_publish_schema_twice_conflict(db_session) -> None:
    org = await _org(db_session)
    actor = await _account(db_session)
    service = OrganizationSchemaService(db_session)
    schema = await _create(service, org, actor.id)
    await service.publish_schema(org.id, schema.id, actor.id)
    with pytest.raises(OrganizationDocumentSchemaConflictError):
        await service.publish_schema(org.id, schema.id, actor.id)


async def test_update_draft_reflects_changes(db_session) -> None:
    org = await _org(db_session)
    actor = await _account(db_session)
    service = OrganizationSchemaService(db_session)
    schema = await _create(service, org, actor.id)
    updated = await service.update_schema(
        org.id,
        schema.id,
        actor.id,
        OrganizationDocumentSchemaUpdate(
            description="full blood count", document_type=DocumentType.LAB_RESULT
        ),
    )
    assert updated.description == "full blood count"
    assert updated.document_type == DocumentType.LAB_RESULT
    assert updated.status is OrganizationDocumentSchemaStatus.DRAFT


async def test_update_published_schema_immutable(db_session) -> None:
    org = await _org(db_session)
    actor = await _account(db_session)
    service = OrganizationSchemaService(db_session)
    schema = await _create(service, org, actor.id)
    await service.publish_schema(org.id, schema.id, actor.id)
    with pytest.raises(OrganizationDocumentSchemaImmutableError):
        await service.update_schema(
            org.id,
            schema.id,
            actor.id,
            OrganizationDocumentSchemaUpdate(name="lab_full"),
        )


async def test_rename_to_existing_name_conflict(db_session) -> None:
    org = await _org(db_session)
    actor = await _account(db_session)
    service = OrganizationSchemaService(db_session)
    first = await service.create_schema(
        org.id,
        actor.id,
        OrganizationDocumentSchemaCreate(
            name="lab_blood", schema_definition=_valid_definition()
        ),
    )
    await service.create_schema(
        org.id,
        actor.id,
        OrganizationDocumentSchemaCreate(
            name="imaging_xray", schema_definition=_valid_definition()
        ),
    )
    with pytest.raises(OrganizationDocumentSchemaConflictError):
        await service.update_schema(
            org.id,
            first.id,
            actor.id,
            OrganizationDocumentSchemaUpdate(name="imaging_xray"),
        )


async def test_version_increments_after_publish(db_session) -> None:
    org = await _org(db_session)
    actor = await _account(db_session)
    service = OrganizationSchemaService(db_session)
    v1 = await _create(service, org, actor.id)
    assert v1.version == 1
    await service.publish_schema(org.id, v1.id, actor.id)
    v2 = await _create(service, org, actor.id)
    assert v2.version == 2
    assert v2.status is OrganizationDocumentSchemaStatus.DRAFT
    published_v2 = await service.publish_schema(org.id, v2.id, actor.id)
    assert published_v2.version == 2
    v3 = await service.create_schema(
        org.id,
        actor.id,
        OrganizationDocumentSchemaCreate(
            name="lab_blood", schema_definition=_valid_definition()
        ),
    )
    assert v3.version == 3


async def test_list_schemas_ordered(db_session) -> None:
    org = await _org(db_session)
    actor = await _account(db_session)
    service = OrganizationSchemaService(db_session)
    await service.create_schema(
        org.id,
        actor.id,
        OrganizationDocumentSchemaCreate(
            name="bravo", schema_definition=_valid_definition()
        ),
    )
    await service.create_schema(
        org.id,
        actor.id,
        OrganizationDocumentSchemaCreate(
            name="alpha", schema_definition=_valid_definition()
        ),
    )
    schemas = await service.list_schemas(org.id)
    assert [s.name for s in schemas] == ["alpha", "bravo"]


async def test_get_schema_org_scoped(db_session) -> None:
    org_a = await _org(db_session)
    org_b = Organization(name="Other Clinic", type=OrganizationType.CLINIC)
    db_session.add(org_b)
    await db_session.commit()
    actor = await _account(db_session)
    service = OrganizationSchemaService(db_session)
    schema = await _create(service, org_a, actor.id)
    own = await service.get_schema(org_a.id, schema.id)
    assert own.id == schema.id
    with pytest.raises(OrganizationDocumentSchemaNotFoundError):
        await service.get_schema(org_b.id, schema.id)


async def test_audit_rows_for_create_update_publish(db_session) -> None:
    org = await _org(db_session)
    actor = await _account(db_session)
    service = OrganizationSchemaService(db_session)
    schema = await _create(service, org, actor.id)
    await service.update_schema(
        org.id,
        schema.id,
        actor.id,
        OrganizationDocumentSchemaUpdate(description="updated"),
    )
    await service.publish_schema(org.id, schema.id, actor.id)
    result = await db_session.execute(
        sa.select(AuditLog.action).where(
            AuditLog.actor_account_id == actor.id,
            AuditLog.resource_type == "organization_document_schema",
        )
    )
    actions = {row[0] for row in result.all()}
    assert actions == {
        AuditAction.ORGANIZATION_SCHEMA_CREATED.value,
        AuditAction.ORGANIZATION_SCHEMA_UPDATED.value,
        AuditAction.ORGANIZATION_SCHEMA_PUBLISHED.value,
    }


def test_schema_definition_validation() -> None:
    with pytest.raises(ValueError):
        validate_schema_definition(["not", "an", "object"])
    with pytest.raises(ValueError):
        validate_schema_definition({"type": 7})
    with pytest.raises(ValueError):
        validate_schema_definition({"properties": []})
    with pytest.raises(ValueError):
        validate_schema_definition({"properties": {"hemoglobin": "number"}})
    assert validate_schema_definition(_valid_definition())["type"] == "object"


def test_update_schema_at_least_one_field_validation() -> None:
    with pytest.raises(ValueError):
        OrganizationDocumentSchemaUpdate()
    assert OrganizationDocumentSchemaUpdate(name="lab_full").name == "lab_full"


def _load_migration_0014():
    path = REPO_ROOT / "migrations/alembic/versions/0014_organization_document_schemas.py"
    spec = spec_from_file_location("migration_0014", path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_0014_revision_wiring() -> None:
    migration = _load_migration_0014()
    assert migration.revision == "0014"
    assert migration.down_revision == "0015"


def test_migration_0014_upgrade_downgrade_round_trip() -> None:
    migration = _load_migration_0014()
    engine = sa.create_engine("sqlite://")
    org_id, account_id, schema_id = (uuid4() for _ in range(3))
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
                """
                CREATE TABLE accounts (
                    id VARCHAR(32) PRIMARY KEY
                )
                """
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO organizations (id, name) VALUES (:id, 'City Clinic')"
            ).bindparams(id=org_id.hex)
        )
        conn.execute(
            sa.text("INSERT INTO accounts (id) VALUES (:id)").bindparams(
                id=account_id.hex
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
        assert "organization_document_schemas" in tables
        columns = {
            row[1]
            for row in conn.execute(
                sa.text("PRAGMA table_info(organization_document_schemas)")
            )
        }
        assert {
            "id",
            "organization_id",
            "name",
            "description",
            "document_type",
            "schema_definition",
            "version",
            "status",
            "created_by_account_id",
            "published_at",
            "created_at",
            "updated_at",
        } <= columns
        indexes = {
            row[1]
            for row in conn.execute(
                sa.text("PRAGMA index_list(organization_document_schemas)")
            )
        }
        assert {
            "ix_organization_document_schemas_organization_id",
            "ix_organization_document_schemas_created_at",
            "uq_organization_document_schemas_org_name_ver",
        } <= indexes

        conn.execute(
            sa.text(
                "INSERT INTO organization_document_schemas"
                " (id, organization_id, name, schema_definition, version, status,"
                " created_by_account_id, created_at, updated_at)"
                " VALUES (:id, :org, 'lab_blood', '{}', 1, 'DRAFT', :owner,"
                " '2026-01-01', '2026-01-01')"
            ).bindparams(
                id=schema_id.hex, org=org_id.hex, owner=account_id.hex
            )
        )
        row = conn.execute(
            sa.text(
                "SELECT document_type, status, version FROM"
                " organization_document_schemas WHERE id = :id"
            ).bindparams(id=schema_id.hex)
        ).one()
        assert row._mapping["document_type"] == "OTHER"
        assert row._mapping["status"] == "DRAFT"
        assert row._mapping["version"] == 1
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO organization_document_schemas"
                    " (id, organization_id, name, schema_definition, version, status,"
                    " created_at, updated_at)"
                    " VALUES (:id, :org, 'lab_blood', '{}', 1, 'DRAFT',"
                    " '2026-01-01', '2026-01-01')"
                ).bindparams(id=uuid4().hex, org=org_id.hex)
            )
        conn.rollback()

        with Operations.context(ctx):
            migration.downgrade()
        tables_after = {
            row[0]
            for row in conn.execute(
                sa.text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        }
        assert "organization_document_schemas" not in tables_after