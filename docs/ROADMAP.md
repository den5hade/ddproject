# ROADMAP.md

> Milestones for the whole platform. Detailed, per-service dev plans live in
> [development/](development/): `OAI_IMPLEMENTATION_PLAN.md` (full 8-phase plan)
> and `OC_ACC_IMPLEMTATION.md` (account-api M1–M6). This file is the canonical
> milestone list; it is not a task tracker (issues belong in GitHub).

Legend: ✅ done · ⏳ deferred / future · ◼ in progress

---

## Platform phases

```text
Phase 0  Foundation
Phase 1  Identity & Auth
Phase 2  Patient & Medical Record
Phase 3  Documents & S3
Phase 4  Processing Pipeline (Marker)
Phase 5  AI Extraction
Phase 6  Specialist Access
Phase 7  Analytics
Phase 8  Production hardening
```

Each phase must end with a **working vertical slice**, not just a set of tables.

---

## Account API milestones (from `OC_ACC_IMPLEMTATION.md`)

| Milestone | Scope | Status |
|-----------|-------|--------|
| M0 | Foundation: migration `0002` schema, auth flow (OTP + JWT + refresh rotation) | ✅ |
| M1 | RBAC: seed roles/permissions, `POST /admin/rbac/seed`, assign roles, `require_roles` / `require_permission` | ✅ |
| M2 | Person + Patient + MedicalRecord (`POST /patients`, `GET /patients/me`, `PATCH /patients/me`) | ✅ |
| M3 | Documents + Versions + Storage + Processing Jobs (worker-backed upload, versions, download, jobs) | ✅ |
| M4 | Encounters (create/list/get/update, docs per encounter) | ✅ |
| M5 | Access Grants + ABAC + Audit Log (`require_patient_access`) | ✅ |
| M6 | Analytics (observations/diagnoses/medications/consents) | ⏳ |

Dependency rule: **M3 and M4 must not ship without the M5 dependency
`require_patient_access`** (data-leak prevention). M5 can be built in parallel.

---

## Platform milestones (from `OAI_IMPLEMENTATION_PLAN.md` §34)

| Milestone | Scope | Status |
|-----------|-------|--------|
| M1 | Infrastructure: monorepo, Docker, PostgreSQL, RabbitMQ, MinIO, Qdrant, Alembic, CI, logging | ✅ (foundation in place) |
| M2 | Authentication: account, email/phone, OTP, JWT/session, roles, permissions, `/me` | ✅ |
| M3 | Patient: person, patient, medical record, basic profile | ✅ |
| M4 | Documents: upload init, presigned S3 upload, document/version, status, download, delete, RabbitMQ job | ◼ |
| M5 | Marker: marker-worker, S3 download, conversion, artifact upload, RabbitMQ events, retry/DLQ | ◼ |
| M6 | GPU orchestration: queue monitoring, provider API, start/stop, heartbeat, scale threshold, idle shutdown | ◼ |
| M7 | AI: Markdown parser, document classification, structured extraction, Pydantic validation, PostgreSQL persistence, embeddings, Qdrant | ◼ |
| M8 | Specialist: profile, organizations, memberships, access grants, medical record access, encounter creation, document upload | ◼ |
| M9 | Analytics: observations, trends, timeline, charts/API, AI summaries | ⏳ |
| M10 | Security/production: audit logs, rate limiting, encryption, backups, monitoring, alerting, retention, access reviews, DR | ⏳ |

---

## First end-to-end vertical slice (target)

```text
Register → Login → Create Patient → Create Medical Record → Upload PDF
→ S3 → RabbitMQ → Marker → Markdown → AI extraction → PostgreSQL → Qdrant
→ GET /medical-record → user sees extracted result
```

Then: patient grants access → specialist views record → creates encounter →
uploads document → same pipeline. Analytics only after this works.

---

## Architecture principles (fixed before coding)

1. PostgreSQL — source of truth (medical data).
2. S3 — source of binary artifacts (PDF/images/Markdown/JSON).
3. Qdrant — search/index layer (embeddings/chunks), never source of truth.
4. RabbitMQ — transport, not a database.
5. AI is not the source of truth — AI output must pass Pydantic validation and
   domain rules before it reaches PostgreSQL.
