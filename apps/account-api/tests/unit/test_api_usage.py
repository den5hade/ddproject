from datetime import UTC, datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.domain.medical import (
    DocumentStatus,
    OrganizationStatus,
    OrganizationType,
)
from app.domain.organization import BatchStatus, OrganizationUsageRangeError
from app.models.document import Document
from app.models.medical_record import MedicalRecord
from app.models.organization import (
    Organization,
    OrganizationApiRequest,
    OrganizationUploadBatch,
)
from app.models.patient import Patient
from app.models.person import Person
from app.services.organization_api_request import OrganizationApiRequestService
from app.services.organization_monitoring import OrganizationMonitoringService
from app.tasks import api_request_purge

REPO_ROOT = Path(__file__).resolve().parents[4]


async def _org(db_session) -> Organization:
    org = Organization(
        name="City Clinic",
        type=OrganizationType.CLINIC,
        status=OrganizationStatus.ACTIVE,
    )
    db_session.add(org)
    await db_session.commit()
    return org


async def _seed_request(
    db_session,
    org: Organization,
    *,
    status_code: int,
    created_at: datetime,
    extra_org: Organization | None = None,
) -> None:
    db_session.add(
        OrganizationApiRequest(
            organization_id=(extra_org or org).id,
            request_id=uuid4().hex,
            method="POST",
            path="/integration/upload",
            status_code=status_code,
            duration_ms=12,
            created_at=created_at,
        )
    )
    await db_session.commit()


async def test_get_usage_default_window_and_empty_series(db_session):
    org = await _org(db_session)
    service = OrganizationMonitoringService(db_session)
    response = await service.get_usage(org.id)

    today = datetime.now(UTC).date()
    assert response.organization_id == org.id
    assert response.from_date == today - timedelta(days=30)
    assert response.to_date == today
    assert response.days == []
    assert response.total_requests == 0
    assert response.total_documents == 0
    assert response.total_batches == 0


async def test_get_usage_reversed_range_raises(db_session):
    org = await _org(db_session)
    service = OrganizationMonitoringService(db_session)
    today = datetime.now(UTC).date()
    with pytest.raises(OrganizationUsageRangeError):
        await service.get_usage(org.id, from_date=today, to_date=today - timedelta(days=1))


async def test_get_usage_span_over_limit_raises(db_session):
    org = await _org(db_session)
    service = OrganizationMonitoringService(db_session)
    today = datetime.now(UTC).date()
    with pytest.raises(OrganizationUsageRangeError):
        await service.get_usage(org.id, from_date=today - timedelta(days=90), to_date=today)


async def test_get_usage_aggregates_api_requests_per_day(db_session):
    org = await _org(db_session)
    d1, d2 = datetime(2026, 9, 1, 8, 0), datetime(2026, 9, 2, 9, 30)
    await _seed_request(db_session, org, status_code=200, created_at=d1)
    await _seed_request(db_session, org, status_code=200, created_at=d1)
    await _seed_request(db_session, org, status_code=500, created_at=d1)
    await _seed_request(db_session, org, status_code=404, created_at=d2)
    await _seed_request(db_session, org, status_code=200, created_at=datetime(2026, 8, 25, 10, 0))

    service = OrganizationMonitoringService(db_session)
    response = await service.get_usage(
        org.id, from_date=datetime(2026, 9, 1).date(), to_date=datetime(2026, 9, 2).date()
    )

    assert [(row.date, row.requests) for row in response.days] == [
        (datetime(2026, 9, 1).date(), 3),
        (datetime(2026, 9, 2).date(), 1),
    ]
    day1 = response.days[0]
    assert (day1.successes, day1.errors) == (2, 1)
    assert day1.success_rate == 66.67
    assert day1.error_rate == 33.33
    day2 = response.days[1]
    assert (day2.successes, day2.errors) == (0, 1)
    assert (day2.success_rate, day2.error_rate) == (0.0, 100.0)
    assert response.total_requests == 4
    assert response.total_successes == 2
    assert response.total_errors == 2
    assert (response.overall_success_rate, response.overall_error_rate) == (50.0, 50.0)


async def test_get_usage_inclusive_utc_day_bounds(db_session):
    org = await _org(db_session)
    day = datetime(2026, 9, 5, 0, 0)
    await _seed_request(db_session, org, status_code=200, created_at=day)
    await _seed_request(db_session, org, status_code=200, created_at=datetime(2026, 9, 2, 12, 0))
    await _seed_request(db_session, org, status_code=200, created_at=datetime(2026, 8, 31, 23, 30))
    await _seed_request(db_session, org, status_code=200, created_at=datetime(2026, 9, 6, 0, 0))

    service = OrganizationMonitoringService(db_session)
    response = await service.get_usage(
        org.id, from_date=datetime(2026, 9, 1).date(), to_date=datetime(2026, 9, 5).date()
    )

    assert [row.date for row in response.days] == [
        datetime(2026, 9, 2).date(),
        datetime(2026, 9, 5).date(),
    ]
    assert response.total_requests == 2


async def test_get_usage_surfaces_document_and_batch_activity(db_session):
    org = await _org(db_session)
    person = Person()
    db_session.add(person)
    await db_session.flush()
    patient = Patient(person_id=person.id)
    db_session.add(patient)
    await db_session.flush()
    record = MedicalRecord(patient_id=patient.id)
    db_session.add(record)
    await db_session.flush()
    db_session.add(
        Document(
            medical_record_id=record.id,
            organization_id=org.id,
            status=DocumentStatus.UPLOADED,
            created_at=datetime(2026, 9, 3, 11, 0),
        )
    )
    db_session.add(
        Document(
            medical_record_id=record.id,
            organization_id=org.id,
            status=DocumentStatus.FAILED,
            created_at=datetime(2026, 9, 3, 12, 0),
        )
    )
    db_session.add(
        OrganizationUploadBatch(
            organization_id=org.id,
            status=BatchStatus.COMPLETED,
            total_count=10,
            accepted_count=7,
            failed_count=3,
            created_at=datetime(2026, 9, 3, 13, 0),
        )
    )
    await db_session.commit()

    service = OrganizationMonitoringService(db_session)
    response = await service.get_usage(
        org.id, from_date=datetime(2026, 9, 3).date(), to_date=datetime(2026, 9, 3).date()
    )

    assert len(response.days) == 1
    day = response.days[0]
    assert day.requests == 0
    assert day.successes == 0
    assert day.errors == 0
    assert (day.documents, day.documents_failed) == (2, 1)
    assert (day.batches, day.batch_items_failed) == (1, 3)
    assert (day.success_rate, day.error_rate) == (0.0, 0.0)
    assert response.total_documents_failed == 1
    assert response.total_batch_items_failed == 3


async def test_get_usage_org_isolation(db_session):
    org_a, org_b = await _org(db_session), await _org(db_session)
    await _seed_request(db_session, org_a, status_code=200, created_at=datetime(2026, 9, 1, 8, 0))
    await _seed_request(db_session, org_b, status_code=500, created_at=datetime(2026, 9, 1, 8, 0))

    service = OrganizationMonitoringService(db_session)
    response = await service.get_usage(
        org_a.id, from_date=datetime(2026, 9, 1).date(), to_date=datetime(2026, 9, 1).date()
    )

    day = response.days[0]
    assert (day.requests, day.successes, day.errors) == (1, 1, 0)


async def test_purge_expired_deletes_only_old_rows(db_session):
    org = await _org(db_session)
    cutoff = datetime(2026, 9, 1, 0, 0)
    await _seed_request(db_session, org, status_code=200, created_at=datetime(2026, 8, 31, 23, 59))
    await _seed_request(db_session, org, status_code=200, created_at=datetime(2026, 8, 30, 12, 0))
    await _seed_request(db_session, org, status_code=200, created_at=datetime(2026, 9, 1, 0, 0))

    service = OrganizationApiRequestService(db_session)
    assert await service.purge_expired(cutoff) == 2
    remaining = (
        await db_session.execute(sa.select(sa.func.count()).select_from(OrganizationApiRequest))
    ).scalar_one()
    assert remaining == 1
    assert await service.purge_expired(cutoff) == 0


async def test_purge_expired_bounded_loop(db_session, monkeypatch):
    org = await _org(db_session)
    monkeypatch.setattr(OrganizationApiRequestService, "_PURGE_BATCH_SIZE", 2)
    for i in range(5):
        await _seed_request(
            db_session, org, status_code=200, created_at=datetime(2026, 8, 20 + i, 12, 0)
        )

    service = OrganizationApiRequestService(db_session)
    assert await service.purge_expired(datetime(2026, 9, 1, 0, 0)) == 5
    remaining = (
        await db_session.execute(sa.select(sa.func.count()).select_from(OrganizationApiRequest))
    ).scalar_one()
    assert remaining == 0


def test_purge_task_interval_constant() -> None:
    assert api_request_purge.PURGE_INTERVAL_SECONDS == 3600


def _load_migration_0016():
    path = REPO_ROOT / "migrations/alembic/versions/0016_organization_api_request_usage_index.py"
    spec = spec_from_file_location("migration_0016", path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_0016_revision_wiring() -> None:
    migration = _load_migration_0016()
    assert migration.revision == "0016"
    assert migration.down_revision == "0014"


def test_migration_0016_upgrade_downgrade_round_trip() -> None:
    migration = _load_migration_0016()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                """
                CREATE TABLE organization_api_requests (
                    id VARCHAR(32) PRIMARY KEY,
                    organization_id VARCHAR(32),
                    created_at VARCHAR(64)
                )
                """
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO organization_api_requests (id, organization_id, created_at)"
                " VALUES ('1', 'o1', '2026-09-01 08:00:00')"
            )
        )

    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration.upgrade()
        indexes = {
            row[1]
            for row in conn.execute(
                sa.text("PRAGMA index_list(organization_api_requests)")
            )
        }
        assert "ix_organization_api_requests_org_created" in indexes

        with Operations.context(ctx):
            migration.downgrade()
        indexes = {
            row[1]
            for row in conn.execute(
                sa.text("PRAGMA index_list(organization_api_requests)")
            )
        }
        assert "ix_organization_api_requests_org_created" not in indexes