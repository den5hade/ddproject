from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.dependencies.integration import (
    ApiKeyContext,
    require_api_key_permission,
)
from app.domain.organization import OrganizationApiKeyScope

router = APIRouter(prefix="/integration", tags=["integration"])

RequireUploadScope = Annotated[
    bool, Depends(require_api_key_permission(OrganizationApiKeyScope.DOCUMENTS_UPLOAD))
]


@router.post(
    "/documents",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    summary="Submit a document (stub)",
)
async def create_document(
    _permission: RequireUploadScope,
    context: ApiKeyContext,
) -> dict[str, str]:
    """Phase 4c stub: exercises the full API-key auth chain.

    Authentication, org-isolation, scope, verification gate and rate limiting
    all run here. Real document ingestion lands in Phase 4d (this endpoint is
    replaced by then).
    """
    return {"code": "not_implemented", "detail": "integration upload lands in 4d"}