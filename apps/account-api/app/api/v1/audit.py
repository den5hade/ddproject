from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.dependencies.access import AuditServiceDep
from app.dependencies.rbac import require_roles
from app.domain.access import AuditAction
from app.domain.account import RoleCode
from app.models.audit_log import AuditLog
from app.schemas.audit import AuditLogResponse

router = APIRouter(prefix="/audit-logs", tags=["audit"])


def _log_response(entry: AuditLog) -> AuditLogResponse:
    return AuditLogResponse.model_validate(entry)


@router.get(
    "",
    response_model=list[AuditLogResponse],
    dependencies=[Depends(require_roles(RoleCode.SYSTEM_ADMIN))],
)
async def list_audit_logs(
    service: AuditServiceDep,
    patient_id: UUID | None = None,
    actor_id: UUID | None = None,
    action: AuditAction | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[AuditLogResponse]:
    entries = await service.list_logs(
        patient_id=patient_id,
        actor_account_id=actor_id,
        action=action,
        limit=limit,
        offset=offset,
    )
    return [_log_response(entry) for entry in entries]
