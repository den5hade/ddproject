from fastapi import APIRouter

from app.api.v1.access import router as access_router
from app.api.v1.admin import router as admin_router
from app.api.v1.audit import router as audit_router
from app.api.v1.auth import router as auth_router
from app.api.v1.documents import router as documents_router
from app.api.v1.encounters import router as encounters_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.patients import router as patients_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(admin_router)
api_router.include_router(access_router)
api_router.include_router(audit_router)
api_router.include_router(patients_router)
api_router.include_router(documents_router)
api_router.include_router(encounters_router)
api_router.include_router(jobs_router)

__all__ = ["api_router"]