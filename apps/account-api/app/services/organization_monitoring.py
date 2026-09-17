from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.organization import OrganizationUsageRangeError
from app.repositories.organization import OrganizationRepository
from app.schemas.organization import (
    OrganizationApiUsageDay,
    OrganizationApiUsageResponse,
)

_DEFAULT_WINDOW_DAYS = 30


class OrganizationMonitoringService:
    """Org-scoped API-usage aggregation for ``GET /organizations/me/api-usage``
    (Phase 4h).

    Aggregates the org's ``organization_api_requests`` access-log volume and
    the org-sourced document/batch activity into a sparse per-day series.
    Counts and dates only — **never PII** (no patient emails, paths, IPs or
    user agents), matching the locked §4.14 monitoring notes.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repos = OrganizationRepository(session)

    async def get_usage(
        self,
        organization_id: UUID,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> OrganizationApiUsageResponse:
        """Daily aggregates over the inclusive ``[from_date, to_date]`` range.

        Both bounds are optional; defaults are the trailing
        ``_DEFAULT_WINDOW_DAYS`` days ending today. The span is capped by
        ``integration_usage_max_range_days`` and ``from_date`` must not come
        after ``to_date`` (else ``OrganizationUsageRangeError`` -> 422).
        Day boundaries are UTC (v1 semantics).
        """
        today = datetime.now(UTC).date()
        from_date = from_date or today - timedelta(days=_DEFAULT_WINDOW_DAYS)
        to_date = to_date or today

        if from_date > to_date:
            raise OrganizationUsageRangeError("'to' must not be before 'from'")
        span_days = (to_date - from_date).days + 1
        if span_days > settings.integration_usage_max_range_days:
            raise OrganizationUsageRangeError(
                "usage range exceeds "
                f"{settings.integration_usage_max_range_days} days"
            )

        from_dt = datetime.combine(from_date, time.min, tzinfo=UTC)
        to_dt = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=UTC)

        api_rows = await self._repos.aggregate_api_requests_by_day(
            organization_id, from_dt, to_dt
        )
        doc_rows = dict(
            await self._repos.aggregate_org_documents_by_day(
                organization_id, from_dt, to_dt
            )
        )
        failed_rows = dict(
            await self._repos.aggregate_org_documents_failed_by_day(
                organization_id, from_dt, to_dt
            )
        )
        batch_rows = {
            day: (batch_count, failed_items)
            for day, batch_count, failed_items in await self._repos.aggregate_batches_by_day(
                organization_id, from_dt, to_dt
            )
        }

        days: list[OrganizationApiUsageDay] = []
        for day, requests, successes, errors in api_rows:
            days.append(
                OrganizationApiUsageDay(
                    date=day,
                    requests=requests,
                    successes=successes,
                    errors=errors,
                    success_rate=_rate(successes, requests),
                    error_rate=_rate(errors, requests),
                    documents=doc_rows.get(day, 0),
                    documents_failed=failed_rows.get(day, 0),
                    batches=batch_rows.get(day, (0, 0))[0],
                    batch_items_failed=batch_rows.get(day, (0, 0))[1],
                )
            )
        # Sparse series: a day with only document/batch activity (no API log
        # row yet) still surfaces.
        only_activity = (
            set(doc_rows) | set(failed_rows) | set(batch_rows)
        ) - {row.date for row in days}
        for day in sorted(only_activity):
            days.append(
                OrganizationApiUsageDay(
                    date=day,
                    requests=0,
                    successes=0,
                    errors=0,
                    success_rate=0.0,
                    error_rate=0.0,
                    documents=doc_rows.get(day, 0),
                    documents_failed=failed_rows.get(day, 0),
                    batches=batch_rows.get(day, (0, 0))[0],
                    batch_items_failed=batch_rows.get(day, (0, 0))[1],
                )
            )
        days.sort(key=lambda row: row.date)

        total_requests = sum(row.requests for row in days)
        total_successes = sum(row.successes for row in days)
        total_errors = sum(row.errors for row in days)
        total_documents = sum(row.documents for row in days)
        total_documents_failed = sum(row.documents_failed for row in days)
        total_batches = sum(row.batches for row in days)
        total_batch_items_failed = sum(row.batch_items_failed for row in days)

        return OrganizationApiUsageResponse(
            from_date=from_date,
            to_date=to_date,
            organization_id=organization_id,
            days=days,
            total_requests=total_requests,
            total_successes=total_successes,
            total_errors=total_errors,
            overall_success_rate=_rate(total_successes, total_requests),
            overall_error_rate=_rate(total_errors, total_requests),
            total_documents=total_documents,
            total_documents_failed=total_documents_failed,
            total_batches=total_batches,
            total_batch_items_failed=total_batch_items_failed,
        )


def _rate(part: int, total: int) -> float:
    """Percentage ``part/total`` (0.0 when total is 0), rounded to 2 dp."""
    if total <= 0:
        return 0.0
    return round((part / total) * 100, 2)


__all__ = ["OrganizationMonitoringService"]