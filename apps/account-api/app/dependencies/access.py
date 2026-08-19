from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_account
from app.domain.access import AuditAction
from app.domain.account import AccountStatus
from app.models.account import Account
from app.models.document import Document
from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord
from app.models.patient import Patient
from app.models.processing_job import DocumentProcessingJob
from app.repositories.document import DocumentRepository, ProcessingJobRepository
from app.repositories.encounter import EncounterRepository
from app.services.access import AccessService
from app.services.audit import AuditService


async def get_access_service(session: AsyncSession = Depends(get_db)) -> AccessService:
    return AccessService(session)


async def get_audit_service(session: AsyncSession = Depends(get_db)) -> AuditService:
    return AuditService(session)


async def _patient_id_for_medical_record(
    session: AsyncSession, medical_record_id: UUID
) -> UUID | None:
    medical_record = await session.get(MedicalRecord, medical_record_id)
    return medical_record.patient_id if medical_record is not None else None


async def _enforce_patient_access(
    *,
    account: Account,
    patient_id: UUID,
    session: AsyncSession,
    access: AccessService,
    audit: AuditService,
    request: Request,
    action: AuditAction,
    flag: str | None,
    deny_status: int,
    resource_type: str = "patient",
    resource_id: UUID | None = None,
) -> Patient:
    """Shared ABAC core: allow/deny, audit every decision, raise on deny."""
    patient = await session.get(Patient, patient_id)
    if patient is None:
        await audit.record(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            patient_id=patient_id,
            actor_account_id=account.id,
            request=request,
            metadata={"decision": "deny", "reason": "patient_not_found"},
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="patient not found"
        )
    if await access.allows(account=account, patient=patient, flag=flag):
        await audit.record(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id or patient.id,
            patient_id=patient.id,
            actor_account_id=account.id,
            request=request,
            metadata={"decision": "allow", "flag": flag},
        )
        return patient
    await audit.record(
        action=action,
        resource_type=resource_type,
        resource_id=resource_id or patient.id,
        patient_id=patient.id,
        actor_account_id=account.id,
        request=request,
        metadata={"decision": "deny", "flag": flag},
    )
    if deny_status == status.HTTP_404_NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="patient not found"
        )
    raise HTTPException(status_code=deny_status, detail="access denied")


def require_patient_access(
    *,
    can_view_documents: bool = False,
    can_upload_documents: bool = False,
    can_view_extractions: bool = False,
    can_view_analytics: bool = False,
    can_create_encounters: bool = False,
    can_edit_medical_data: bool = False,
    action: AuditAction = AuditAction.VIEW_PATIENT,
    deny_status: int = status.HTTP_403_FORBIDDEN,
) -> Callable[..., Patient]:
    """Return a dependency enforcing ABAC for a ``patient_id`` path parameter."""
    flags = [
        name
        for name, enabled in (
            ("can_view_documents", can_view_documents),
            ("can_upload_documents", can_upload_documents),
            ("can_view_extractions", can_view_extractions),
            ("can_view_analytics", can_view_analytics),
            ("can_create_encounters", can_create_encounters),
            ("can_edit_medical_data", can_edit_medical_data),
        )
        if enabled
    ]
    if len(flags) > 1:
        raise ValueError("require_patient_access accepts at most one flag")
    flag = flags[0] if flags else None

    async def dependency(
        request: Request,
        patient_id: UUID,
        account: Account = Depends(get_current_account),
        session: AsyncSession = Depends(get_db),
        access: AccessService = Depends(get_access_service),
        audit: AuditService = Depends(get_audit_service),
    ) -> Patient:
        return await _enforce_patient_access(
            account=account,
            patient_id=patient_id,
            session=session,
            access=access,
            audit=audit,
            request=request,
            action=action,
            flag=flag,
            deny_status=deny_status,
        )

    return dependency


def require_patient_owner(
    *,
    action: AuditAction = AuditAction.GRANT_ACCESS,
) -> Callable[..., Patient]:
    """Return a dependency requiring the actor to own the patient (grant CRUD)."""

    async def dependency(
        request: Request,
        patient_id: UUID,
        account: Account = Depends(get_current_account),
        session: AsyncSession = Depends(get_db),
        audit: AuditService = Depends(get_audit_service),
    ) -> Patient:
        patient = await session.get(Patient, patient_id)
        if patient is None:
            await audit.record(
                action=action,
                resource_type="patient",
                resource_id=patient_id,
                patient_id=patient_id,
                actor_account_id=account.id,
                request=request,
                metadata={"decision": "deny", "reason": "patient_not_found"},
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="patient not found"
            )
        if account.status == AccountStatus.ACTIVE and account.person_id == patient.person_id:
            await audit.record(
                action=action,
                resource_type="patient",
                resource_id=patient.id,
                patient_id=patient.id,
                actor_account_id=account.id,
                request=request,
                metadata={"decision": "allow", "mode": "owner"},
            )
            return patient
        await audit.record(
            action=action,
            resource_type="patient",
            resource_id=patient.id,
            patient_id=patient.id,
            actor_account_id=account.id,
            request=request,
            metadata={"decision": "deny", "reason": "not_owner"},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only the patient owner can manage access grants",
        )

    return dependency


def require_document_access(
    *,
    flag: str = "can_view_documents",
    action: AuditAction = AuditAction.VIEW_DOCUMENT,
) -> Callable[..., Document]:
    """Return a dependency loading a document and enforcing ABAC on its owner."""

    async def dependency(
        request: Request,
        document_id: UUID,
        account: Account = Depends(get_current_account),
        session: AsyncSession = Depends(get_db),
        access: AccessService = Depends(get_access_service),
        audit: AuditService = Depends(get_audit_service),
    ) -> Document:
        document = await DocumentRepository(session).get(document_id)
        if document is None:
            await audit.record(
                action=action,
                resource_type="document",
                resource_id=document_id,
                patient_id=None,
                actor_account_id=account.id,
                request=request,
                metadata={"decision": "deny", "reason": "not_found"},
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="document not found"
            )
        patient_id = await _patient_id_for_medical_record(
            session, document.medical_record_id
        )
        if patient_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="document not found"
            )
        await _enforce_patient_access(
            account=account,
            patient_id=patient_id,
            session=session,
            access=access,
            audit=audit,
            request=request,
            action=action,
            flag=flag,
            deny_status=status.HTTP_403_FORBIDDEN,
            resource_type="document",
            resource_id=document.id,
        )
        return document

    return dependency


def require_encounter_access(
    *,
    flag: str | None = None,
    action: AuditAction = AuditAction.VIEW_MEDICAL_RECORD,
) -> Callable[..., Encounter]:
    """Return a dependency loading an encounter and enforcing ABAC on its owner."""

    async def dependency(
        request: Request,
        encounter_id: UUID,
        account: Account = Depends(get_current_account),
        session: AsyncSession = Depends(get_db),
        access: AccessService = Depends(get_access_service),
        audit: AuditService = Depends(get_audit_service),
    ) -> Encounter:
        encounter = await EncounterRepository(session).get(encounter_id)
        if encounter is None:
            await audit.record(
                action=action,
                resource_type="encounter",
                resource_id=encounter_id,
                patient_id=None,
                actor_account_id=account.id,
                request=request,
                metadata={"decision": "deny", "reason": "not_found"},
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="encounter not found"
            )
        patient_id = await _patient_id_for_medical_record(
            session, encounter.medical_record_id
        )
        if patient_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="encounter not found"
            )
        await _enforce_patient_access(
            account=account,
            patient_id=patient_id,
            session=session,
            access=access,
            audit=audit,
            request=request,
            action=action,
            flag=flag,
            deny_status=status.HTTP_403_FORBIDDEN,
            resource_type="encounter",
            resource_id=encounter.id,
        )
        return encounter

    return dependency


def require_job_access(
    *,
    action: AuditAction = AuditAction.VIEW_DOCUMENT,
) -> Callable[..., DocumentProcessingJob]:
    """Return a dependency loading a job and enforcing ABAC on its owner."""

    async def dependency(
        request: Request,
        job_id: UUID,
        account: Account = Depends(get_current_account),
        session: AsyncSession = Depends(get_db),
        access: AccessService = Depends(get_access_service),
        audit: AuditService = Depends(get_audit_service),
    ) -> DocumentProcessingJob:
        job = await ProcessingJobRepository(session).get(job_id)
        if job is None:
            await audit.record(
                action=action,
                resource_type="job",
                resource_id=job_id,
                patient_id=None,
                actor_account_id=account.id,
                request=request,
                metadata={"decision": "deny", "reason": "not_found"},
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="job not found"
            )
        document = await DocumentRepository(session).get(job.document_id)
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="job not found"
            )
        patient_id = await _patient_id_for_medical_record(
            session, document.medical_record_id
        )
        if patient_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="job not found"
            )
        await _enforce_patient_access(
            account=account,
            patient_id=patient_id,
            session=session,
            access=access,
            audit=audit,
            request=request,
            action=action,
            flag="can_view_documents",
            deny_status=status.HTTP_403_FORBIDDEN,
            resource_type="job",
            resource_id=job.id,
        )
        return job

    return dependency


AccessServiceDep = Annotated[AccessService, Depends(get_access_service)]
AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]
