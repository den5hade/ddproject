# Project Status

> **Current snapshot:** [PROJECT_STATUS_LATEST.md](PROJECT_STATUS_LATEST.md) (code-based, 2026-09-05)
> **Reference:** [archive/PROJECT_STATUS_090426.md](archive/PROJECT_STATUS_090426.md) (comprehensive, 2026-09-04)
> **Schema:** [development/operational/STATUS_REPORT_SCHEMA.md](development/operational/STATUS_REPORT_SCHEMA.md)

## Executive Summary
- **Stage:** Working Client MVP (vertical slice: auth → upload → AI extraction → cabinet) + domain/DB foundation
- **Core pipeline:** OTP auth → document upload → S3 → ai-worker (OCR + canonical extraction) → PostgreSQL → web cabinet
- **Gaps:** Specialist/org workflows, notifications, medical normalization, analytics, Marker GPU pipeline

## Layer Status
| Layer | Status | Notes |
|-------|--------|-------|
| Migrations | 🟢 5 applied | `0001_initial` → `0005_document_date_backfill` |
| Domain Model | 🟢 21 models | Account/Person/Patient/Specialist/Org/Document/Encounter/Access/Audit |
| API | 🟢 34 endpoints | Auth, Patients, Documents, Encounters, Access, Jobs, Audit, Admin |
| Auth | 🟢 OTP + JWT | Redis OTP, HMAC refresh rotation, account status enforcement |
| Document Pipeline | 🟢 2-stage | objectstorage-worker → S3 → ai-worker (no Marker GPU yet) |
| Canonical Data | 🟢 Implemented | Pydantic validation, structured.md, canonical.json API |
| Frontend (MVP-1) | 🟢 Complete | OTP login, dashboard, docs, canonical view, profile, Playwright E2E |
| Packages | 🟢 4/5 | canonical, contracts, messaging, storage done; observability stub |
| Infrastructure | 🟢 Dev compose | Main VPS compose ~; GPU VPS infra ready, worker stub |

## Near-Complete (`[~]`)
- Specialist workflow (model+RBAC+ABAC done; API/UI pending)
- Organisation workflow (model+membership done; API/UI pending)
- Notifications (OTP done; document events + worker pending)
- Access Management UI (backend done; client cabinet screen pending)
- Main VPS production compose (Qdrant connected but unused)

## Not Implemented (`[ ]`)
- Medical normalization: `observations`, `diagnoses`, `medications`, `patient_consents`
- Analytics: time-series, trends, charts
- Marker GPU pipeline (`marker-worker`, `marker-orchestrator`)
- Embeddings + Qdrant
- Retry/DLQ redrive, integration tests
- Longitudinal AI, Specialist AI assistant

## Next Priorities
1. Client UX polish (access management, notifications)
2. Specialist workflow (CRUD API + UI)
3. Organisation workflow (document delivery + notifications)
4. Medical normalization (observations → time-series → analytics)

## Code Reference Map
| Layer | Paths |
|-------|-------|
| Models | `apps/account-api/app/models/*.py` |
| API | `apps/account-api/app/api/v1/*.py` |
| Auth/OTP | `apps/account-api/app/services/{auth,otp}.py`, `core/security.py` |
| Access | `services/access.py`, `dependencies/{access,rbac}.py` |
| Documents | `services/documents.py`, `services/storage.py` |
| Events | `consumers/document_events.py`, `core/bus.py` |
| AI Pipeline | `apps/ai-worker/app/{main,processor,ai_client,doc_classifier,pdf_converter}.py` |
| Canonical | `packages/canonical/canonical/{schemas,metadata,render}.py` |
| Upload | `apps/objectstorage-worker/app/processor.py` |
| OTP Delivery | `apps/notification-worker/app/{main.py,providers/*}` |
| Web | `apps/web/src/{app,features,lib}/` |
| Migrations | `migrations/alembic/versions/0001..0005*.py` |
| Infra | `infrastructure/*`, `Makefile`, `.github/workflows/` |