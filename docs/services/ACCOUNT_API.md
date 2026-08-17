# Account API

FastAPI service on the Main VPS. Entry point: `apps/account-api/app/main.py`.

## Responsibilities

```text
Authentication (passwordless OTP, JWT access, rotating refresh)
Authorization (RBAC roles/permissions + ABAC via access grants)
Patients
Medical Records
Documents metadata + versions
Encounters
Access grants
Audit log
Analytics API
Presigned S3 upload/download URLs
```

## Does NOT

```text
run Marker
process PDFs
run LLM
generate embeddings
store binary files locally
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

## Storage & messaging

- PostgreSQL for all structured data (see [data/DB_MODELS.md](../data/DB_MODELS.md)).
- S3 for binaries via presigned URLs (see [data/STORAGE.md](../data/STORAGE.md)).
- RabbitMQ for events (see [messaging/](../messaging/)).
- Shared packages: `pdf-contracts`, `pdf-messaging`, `pdf-storage`,
  `pdf-observability`.

## Run locally

```bash
uv run --project apps/account-api uvicorn app.main:app --reload
```
