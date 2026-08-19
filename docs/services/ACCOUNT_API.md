# Account API

FastAPI service on the Main VPS. Entry point: `apps/account-api/app/main.py`.

## Responsibilities

```text
Authentication (passwordless OTP, JWT access, rotating refresh)
Authorization (RBAC roles/permissions + ABAC via access grants)
Patients
Medical Records
Documents metadata + versions + processing jobs
Encounters
Access grants
Audit log
Analytics API
Presigned S3 download URLs
Document pipeline: stage uploads, publish document.upload.requested,
consume document.stored / converted / analysis.completed / processing.failed
```

## Does NOT

```text
run Marker
process PDFs / generate markdown
run LLM
generate embeddings
persist binaries locally (staging in STORAGE_TEMP_DIR is transient)
own the medical database writes (structured data goes through services/repositories)
```

This boundary list prevents architectural drift: any code that moves one of the
"does not" items into account-api must be challenged.

## Layering

```text
domain (enums, aggregate rules)         apps/account-api/app/domain/*
  │
Pydantic schema (request/response)      apps/account-api/app/schemas/<domain>.py
  │
repository (only SQL, no logic)         apps/account-api/app/repositories/<entity>.py
  │
service (invariants, events, commit)    apps/account-api/app/services/<domain>.py
  │
router (HTTP, Depends, errors → HTTP)   apps/account-api/app/api/v1/<resource>.py
  │
dependencies (auth/ABAC/RBAC)           apps/account-api/app/dependencies/*
```

Rules:

- **Repository never commits** — only select/insert/flush, returns models.
- **Service commits once** at the end of the operation and raises domain
  exceptions (e.g. `PatientAccessDeniedError`) that routers map to `HTTPException`.
- **Enums** come from `app/domain/*`.
- **Access to foreign data** always goes through the `require_patient_access`
  dependency, never ad-hoc checks.
- **JSON columns** (`data`, `metadata`) are `sa.JSON`.

## Dependency injection

Providers are `get_*` async functions in `app/dependencies/*`, one per concern.
Each dependency file ends with an `Annotated` alias that routers consume directly
(no `Depends(...)` in route signatures):

```python
# app/dependencies/patient.py
async def get_patient_service(session: AsyncSession = Depends(get_db)) -> PatientService:
    return PatientService(session)

PatientServiceDep = Annotated[PatientService, Depends(get_patient_service)]
```

```python
# app/api/v1/patients.py
async def get_my_patient(
    account: CurrentAccount,
    service: PatientServiceDep,
) -> PatientResponse:
```

Rules:

- Route signatures reference only the alias name.
- `CurrentAccount` (from `dependencies/auth.py`) injects the authenticated `Account`.
- Argument-taking factories (`require_roles`, `require_permission`) keep
  `Depends(...)` in the router's `dependencies=[...]` list.
- Non-default `Annotated` params must precede params with defaults (Python syntax).

Aliases in use:

| Alias | Injects | Defined in |
|---|---|---|
| `CurrentAccount` | `Account` | `dependencies/auth.py` |
| `AuthServiceDep` | `AuthService` | `dependencies/auth.py` |
| `OtpServiceDep` | `OtpService` | `dependencies/auth.py` |
| `RbacServiceDep` | `RbacService` | `dependencies/rbac.py` |
| `PatientServiceDep` | `PatientService` | `dependencies/patient.py` |
| `DocumentServiceDep` | `DocumentService` | `dependencies/documents.py` |
| `JobServiceDep` | `JobService` | `dependencies/documents.py` |
| `StorageServiceDep` | `StorageService` | `dependencies/documents.py` |

## Implemented endpoints

### Auth — `api/v1/auth.py`

- `POST /auth/request-otp`, `POST /auth/verify`, `POST /auth/refresh`,
  `POST /auth/logout`, `GET /auth/me`

### Admin / RBAC — `api/v1/admin.py` (requires `user.manage`)

- `POST /admin/rbac/seed` — idempotent seed
- `POST /admin/accounts/{account_id}/roles` — assign roles
- `GET /admin/accounts/{account_id}/roles`
- `GET /admin/accounts/{account_id}/permissions`

### Patients — `api/v1/patients.py`

- `POST /patients` — explicit create (201; 409 if patient already exists)
- `GET /patients/me` — lazy-create patient + medical record on first access
- `PATCH /patients/me` — update own `Person`
- `GET /patients/{patient_id}` — owner or specialist with an active access grant,
  otherwise `404` (hides existence)

### Documents — `api/v1/documents.py`

- `POST /patients/{patient_id}/documents` — multipart upload (title,
  document_type, encounter_id as form fields)
- `GET /documents/{id}`, `GET /documents/{id}/versions`,
  `GET /documents/{id}/extractions`, `GET /documents/{id}/jobs`
- `POST /documents/{id}/versions` — upload a new version
- `GET /documents/{id}/download?version_id=` — presigned GET URL

### Jobs — `api/v1/jobs.py`

- `GET /jobs/{job_id}` — single processing job

## Storage & messaging

- PostgreSQL for all structured data (see [data/DB_MODELS.md](../data/DB_MODELS.md)).
- S3 for binaries: uploads staged through objectstorage-worker, downloads via
  presigned GET (see [data/STORAGE.md](../data/STORAGE.md)).
- RabbitMQ for events (see [messaging/](../messaging/)).
- Shared packages: `pdf-contracts`, `pdf-messaging`, `pdf-storage`,
  `pdf-observability`.

## Run locally

```bash
uv run --project apps/account-api uvicorn app.main:app --reload
```
