# Project Status

> **Archive snapshots:** [PROJECT_STATUS_092626.md](archive/PROJECT_STATUS_092626.md) (Classification 2.0, 2026-09-26) · [PROJECT_STATUS_091826.md](archive/PROJECT_STATUS_091826.md) (org/integration backend, 2026-09-18) · [PROJECT_STATUS_090526.md](archive/PROJECT_STATUS_090526.md) (code-based, 2026-09-05) · [PROJECT_STATUS_090426.md](archive/PROJECT_STATUS_090426.md) (comprehensive, 2026-09-04)
> **Latest snapshot link:** [PROJECT_STATUS_LATEST.md](PROJECT_STATUS_LATEST.md) (symlink → `archive/PROJECT_STATUS_092626.md`)
> **Schema:** [development/operational/STATUS_REPORT_SCHEMA.md](development/operational/STATUS_REPORT_SCHEMA.md)
> **Living status updated:** 2026-09-26

## Executive Summary
- **Stage:** Working Client MVP (vertical slice: auth → upload → AI pipeline → canonical extraction → cabinet) + closed backend contour for Organisation/Integration + **Classification 2.0 (rule-based, evaluated)**
- **Core pipeline:** OTP auth → document upload → S3 → ai-worker (OCR → deterministic classification → LLM extraction) → PostgreSQL → web cabinet; org documents via machine integration API + server notifications
- **New since 09-18:** Classification 2.0 M1–M3 (contract types → rule-based classifier + pipeline wiring + regression dataset → deterministic eval CLI + calibration 2.1.0 + manifest audit); profile summary stats (`/patients/me/summary`); `document.convert` topology via rabbit-setup; docs restructured to ORGS reference model
- **Gaps:** Org/admin/specialist UI, notifications/access UI, medical normalization, analytics, Marker GPU pipeline, embeddings/Qdrant

## Layer Status
| Layer | Status | Notes |
|-------|--------|-------|
| Migrations | 🟢 16 applied | `0001_initial` → `0016_organization_api_request_usage_index`, ~29 tables |
| Domain Model | 🟢 Models | Account/Person/Patient/Specialist/Org(+branches/licenses/api_keys/schemas/upload batches)/Notification/Document/Encounter/Access/Audit |
| API | 🟢 68+ endpoints | Auth, Patients (+`/me/summary`), Documents, Encounters, Access, Jobs, Audit, Admin, **Admin-org, Org management, Integration (single/bulk), API usage** |
| Auth | 🟢 OTP + JWT | Redis OTP, HMAC refresh rotation, RBAC + ABAC, org-membership roles, m2m API keys (4 scopes), status enforcement |
| Document Pipeline | 🟢 multi-stage | objectstorage-worker → S3 → ai-worker → account-api; doc events via RabbitMQ; DLQ declared |
| Classification | 🟢 2.0 (rule-based) | Deterministic `rule_score`: laboratory/appointment/prescription/generic + subtypes; 11-fixture regression dataset; eval CLI + gates (no Marker/LMM) |
| Canonical Data | 🟢 Implemented | Pydantic validation (canonical pkg), structured.md, canonical.json API |
| Frontend (MVP-1) | 🟢 Complete | OTP login, dashboard, docs, canonical view, medical record, profile + **profile/edit + summary stats**, Playwright E2E |
| Packages | 🟢 4/5 | canonical, contracts, messaging (topology via rabbit-setup), storage done; observability stub |
| Infrastructure | 🟢 Dev compose + CI | Main VPS compose ~; GPU VPS infra ready, worker stub; test.yml/build.yml/deploy-main.yml |

## Near-Complete (`[~]`)
- Specialist workflow (model+RBAC+ABAC+org-auth done; CRUD API/UI pending)
- Organisation/Platform-admin UI (full backend; UI pending)
- Notifications UI (server-side round-trip done; cabinet UI pending; non-document events pending)
- Access Management UI (backend done; screen pending)
- Delete document (web has disabled button; no backend endpoint/lifecycle)
- Main VPS production compose (Qdrant connected but unused; backup/monitoring TODOs)
- Classification percentage gates (count-based at N=11; resume design-spec §30 % targets when real markers > ~50)

## Not Implemented (`[ ]`)
- Medical normalization: `observations`, `diagnoses`, `medications`, `patient_consents`
- Analytics: time-series, trends, charts
- Marker GPU pipeline (`marker-worker`, `marker-orchestrator` — 0-byte stubs; no LMM for doc classification)
- Embeddings + chunking + Qdrant
- Retry/DLQ redrive, integration tests (`tests/integration/` empty)
- `packages/observability`, `users.py` router (empty)
- Longitudinal AI, Specialist AI assistant

## Next Priorities
1. Organisation UI (owner/admin cabinet) + platform-admin onboarding UI
2. Specialist workflow (CRUD API + UI)
3. Access management UI + notifications UI + delete document
4. Medical normalization (observations → time-series → analytics)
5. Embeddings/Qdrant + Marker GPU pipeline; classification dataset scaling (N > ~50)

## Code Reference Map
| Layer | Paths |
|-------|-------|
| Models | `apps/account-api/app/models/*.py` (organization.py, notification.py) |
| API | `apps/account-api/app/api/v1/*.py` (admin_organizations.py, organizations.py, integration.py, patients.py) |
| Auth/OTP | `apps/account-api/app/services/{auth,otp}.py`, `core/security.py` |
| Access | `services/access.py`, `dependencies/{access,rbac}.py` |
| Org backend | `apps/account-api/app/services/{organization,branches,licenses,api_keys,schemas,api_usage}.py`, patient `resolver.py` |
| Documents | `apps/account-api/app/services/documents.py`, `services/storage.py` |
| Events | `apps/account-api/app/consumers/document_events.py`, `notification_result.py`, `core/bus.py`; `rabbit-setup` topology |
| Classification | `apps/ai-worker/app/classification/{service,scoring,resolver,signals,evaluate,fixtures}.py` (+ `EVAL_FLOW.md`, `MANIFEST_AUDIT.md`) |
| AI Pipeline | `apps/ai-worker/app/{processor,ai_client,doc_classifier,pdf_converter}.py` |
| Canonical | `packages/canonical/canonical/{schemas,metadata,render}.py` |
| Upload | `apps/objectstorage-worker/app/processor.py` |
| Notifications | `apps/notification-worker/app/{main.py,providers/*}` |
| Web | `apps/web/src/{app,features,lib}/` (routes incl. `profile/edit`) |
| Migrations | `migrations/alembic/versions/0001..0016*.py` |
| Infra | `infrastructure/*`, `Makefile` (incl. `test-api`, `eval-classification`), `.github/workflows/` |