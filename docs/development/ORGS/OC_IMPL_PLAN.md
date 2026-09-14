# Organization Domain — Implementation Plan

Implementation plan for the organization integration contour: legal data,
branches, licenses, API keys, a machine-to-machine integration API, patient
resolution, single + bulk document ingestion through the existing pipeline,
client notifications, organization document schemas, API-usage monitoring, and
the registry-verification extension point. Built on existing infrastructure
only — **no parallel architecture**. Sources for depth: `docs/development/ORGS/OAI_IMPL_ARCH.md` (arch) + `docs/development/ORGS/OAI_IMPL_SPEC.md` (spec).

**Revision 4** — Phase 3 (Licenses) completed; `0008` marked done;
`ORGANIZATION_LICENSE_CREATED/UPDATED/DEACTIVATED` audit actions, license
schemas/endpoints folded into §4; Phase 4 marked next.

**Revision 3** — Phase 2 (Branches) completed; `0007` marked done;
`ORGANIZATION_BRANCH_*` audit actions and branch schemas/endpoints folded into
§4.

**Revision 2** — restructured into the concise step/status format of
`docs/development/DOC_PROC_DEV_FLOW_IMPL_PLAN.md`; the 28-section spec was
condensed into the locked design reference (§4). Phase 1 completed
(commit `9b683b7`, see §2).

**Revision 1** — initial full 28-section implementation specification.

Status legend: `[ ]` pending · `[x]` done.

---

## 0. Overview

**Target shape:**

```
                Organization
                     │
     ┌───────────────┼────────────────┐
     │               │                │
Branches         Licenses         API Keys ──▶ Integration API
                                     (JWT = management; API key = machine)
     ┌──────────────────────────────┬─────────────────────┐
     ▼                              ▼                     ▼
patient resolver              single upload           bulk upload
     │                              │                     │
     ▼                    Account→Person→Patient→MedicalRecord   Batches/Items
  Document ◄────────────────────────┘
     │──────────── existing pipeline (S3, RabbitMQ, ai-worker, canonical)
     ▼
DocumentExtraction ──────────▶ Notification (email, no medical data) ──▶ Client
```

**Invariants (locked):**

- **Human vs machine separation** (spec §9): management API = JWT + active `OrganizationMembership` + `organization_admin`; integration API = API key + org context + key scopes. An API key never manages API keys.
- **Submission vs. history access** (arch §58-59): org gets document *submission authority* only; no automatic `PatientAccessGrant`; reading history stays a separate grant flow.
- **One pipeline** (spec §17/§66): `OrganizationDocumentService → DocumentService → Document/DocumentVersion/ProcessingJob` — never a second processing pipeline.
- **Org schemas never replace** the platform canonical schema (spec §23).
- Document status is mutated **only** in `apps/account-api/app/services/documents.py`, never in workers/consumers.

---

## 1. Execution summary

| Phase | Scope | Status |
|---|---|---|
| 1 | Organization core | [x] done |
| 2 | Branches | [x] done |
| 3 | Licenses | [x] done |
| 4 | API keys | [ ] |
| 5 | API-key auth | [ ] |
| 6 | Single document integration | [ ] |
| 7 | Patient resolver | [ ] |
| 8 | Notifications | [ ] |
| 9 | Bulk upload | [ ] |
| 10 | Organization schemas | [ ] |
| 11 | Monitoring | [ ] |
| 12 | Registry verification extension | [ ] |

---

## 2. Completed phases

### Phase 1 — Organization core [x]

**Objective.** Existing orgs digest PATCH with INN/OGRN/legal address;
`GET|PATCH /organizations/me`, admin-only; audit `ORGANIZATION_UPDATED`.
Commit `9b683b7` (`org: legal data model, migration 0006, domain enums,
/organizations/me get+patch`).

**Changes.** Domain enums + INN/OGRN control-digit helpers
(`app/domain/organization.py`); legal-data + `verification_status` columns on
`Organization`; `OrganizationUpdate` / `OrganizationResponse` schemas;
`OrganizationService.update_organization` (unique pre-check, legal change →
`PENDING`, audit); `get_current_organization` / `require_organization_admin`
deps (403 `"no active organization membership"`); `GET|PATCH /organizations/me`
router registered; `AuditAction.ORGANIZATION_UPDATED`;
`integration_validate_inn_checksum` config; migration `0006` (unique indexes,
backfill default).

**Verification.** 33 new tests (INN/OGRN checksums, service, migration
round-trip, API) + full account-api suite **225 pass**; `uvx ruff check
apps/account-api` clean.

#### Phase 1 Implementation Status

- Files created: `app/domain/organization.py`, `app/schemas/organization.py`,
  `app/repositories/organization.py`, `app/services/organization.py`,
  `app/dependencies/organization.py`, `app/api/v1/organizations.py`,
  `tests/unit/test_inn_ogrn.py`, `tests/unit/test_organization.py`,
  `tests/test_organizations_api.py`,
  `migrations/alembic/versions/0006_organization_legal_data.py`.
- Files modified: `app/domain/access.py`, `app/models/organization.py`,
  `app/core/config.py`, `app/api/v1/__init__.py`, `app/api/v1/http_errors.py`.
- SQLAlchemy stores `str, Enum` members by **name** (`native_enum=False`) —
  verified empirically — so `0006` uses server_default `'UNVERIFIED'`
  (uppercase), not the `.value`.
- The full alembic chain is not SQLite-portable (0002 uses PG `btrim`); the
  migration test exercises `0006` upgrade/downgrade in isolation against a
  synthetic 0005-shape `organizations` table.
- `PATCH` with `""` clears the field (→ `NULL`); clearing legal data also moves
  status to `PENDING`.
- The human API can only move status **to `PENDING`**; `VERIFIED`/`REJECTED` are
  set exclusively by the registry provider (Phase 12).

### Phase 2 — Branches [x]

**Objective.** 1:N branches with full CRUD under `/organizations/me/branches`,
org-scoped (no IDOR), duplicate `code` → 409, soft deactivate (DELETE sets
`INACTIVE`, never hard-delete).

**Changes.** `OrganizationBranch` model (+ `BranchStatus` enum use); migration
`0007` (`organization_branches`, `(organization_id, code)` unique index,
FK CASCADE); `BranchCreate`/`BranchUpdate`/`BranchResponse` schemas (code
pattern `^[A-Za-z0-9_-]{1,32}$`, `""` clears a field); `OrganizationRepository`
branch queries (`list_branches`/`get_branch`/`find_branch_by_code`, all org-
scoped); `OrganizationService` branch methods with duplicate pre-check + audit
(`ORGANIZATION_BRANCH_CREATED/UPDATED/DEACTIVATED`); 5 routes
(`GET/POST /me/branches`, `GET/PATCH/DELETE /me/branches/{id}` — DELETE → 204);
404/409 mapping in `http_errors`.

**Verification.** 26 new tests (14 unit + 12 API) + full account-api suite
**251 pass**; `uvx ruff check apps/account-api` clean. Details in the
Implementation Status block below.

#### Phase 2 Implementation Status

- Files created: `migrations/alembic/versions/0007_organization_branches.py`.
- Files modified: `app/models/organization.py`, `app/models/__init__.py`,
  `app/domain/organization.py` (branch errors), `app/domain/access.py`
  (branch audit actions), `app/schemas/organization.py`, `app/repositories/organization.py`,
  `app/services/organization.py`, `app/api/v1/organizations.py`,
  `app/api/v1/http_errors.py`, `tests/test_organizations_api.py`,
  `tests/unit/test_organization.py`.
- New tests: 14 unit (service CRUD, org-scoping, dup-code, soft-deactivate
  keeps history, migration 0007 round-trip) + 12 API (auth/admin gates,
  CRUD, 404 cross-org, 409 dup code, invalid code 422, soft delete 204).
- Full account-api suite **251 pass** (was 225); `uvx ruff check
  apps/account-api` clean. Committed: pending (will commit with Phase 2).
- Deviation from plan: the repo convention for SQLite-testable migrations is a
  **unique index** (`op.create_index(..., unique=True)`) instead of a
  `create_unique_constraint` — SQLite cannot `ALTER` unique constraints
  (`NotImplementedError`); the model still declares
  `UniqueConstraint(name="uq_organization_branches_org_code")`, matched by
  index name. Same pattern as `0006` (inn/ogrn).
- Branch `code` is mutable via PATCH (dup-pre-checked); `status` is only
  mutated by DELETE (deactivate). Inactive branches stay in list/get results
  (history preserved), ready for `branch_code` use by later phases.

### Phase 3 — Licenses [x]

**Objective.** 1:N licenses with full CRUD under `/organizations/me/licenses`,
org-scoped (no IDOR), duplicate `license_number` → 409, history preserved
(DELETE is a soft status change, never a row removal). Registry-ready schema:
future government-registry verification plugs in without coupling the domain to
an external provider.

**Changes.** `OrganizationLicense` model (`license_number` String(64),
`license_type` String(64), `status` (default ACTIVE), `issued_at`/`expires_at`
Date, `scope`/`issuer` String(255)); migration `0008` (`organization_licenses`,
`(organization_id, license_number)` unique index, FK CASCADE);
`LicenseCreate`/`LicenseUpdate`/`LicenseResponse` schemas (`expires_at` after
`issued_at` enforced, `""` clears `scope`/`issuer`, update needs ≥1 field,
explicit `status` change allowed incl. reactivation); `OrganizationRepository`
license queries (all org-scoped); `OrganizationService` license methods with
duplicate pre-check + audit
(`ORGANIZATION_LICENSE_CREATED/UPDATED/DEACTIVATED`); expiry transition —
past-due ACTIVE licenses auto-flip to `EXPIRED` on list/get
(`_expire_overdue`, commits only when something changed); 5 routes
(`GET/POST /me/licenses`, `GET/PATCH/DELETE /me/licenses/{id}` — DELETE → 204,
soft-revoke to `REVOKED`); 404/409 mapping in `http_errors`.

**Verification.** 31 new tests (19 unit + 12 API) + full account-api suite
**282 pass**; `uvx ruff check apps/account-api` clean. Details in the
Implementation Status block below.

#### Phase 3 Implementation Status

- Files created: `migrations/alembic/versions/0008_organization_licenses.py`.
- Files modified: `app/models/organization.py`, `app/models/__init__.py`,
  `app/domain/organization.py` (license errors), `app/domain/access.py`
  (license audit actions), `app/schemas/organization.py`,
  `app/repositories/organization.py`, `app/services/organization.py`,
  `app/api/v1/organizations.py`, `app/api/v1/http_errors.py`,
  `tests/test_organizations_api.py`, `tests/unit/test_organization.py`.
- New tests: 19 unit (service CRUD, org-scoping, dup-number, soft-revoke keeps
  history, manual status change, schema date ordering, expiry transitions on
  list/get, no-expiry stays ACTIVE, audit, migration 0008 round-trip incl.
  duplicate-number `IntegrityError` + downgrade) + 12 API (auth/admin gates,
  CRUD, 404 cross-org, 409 dup number, invalid dates 422, soft delete 204).
- Full account-api suite **282 pass** (was 251); `uvx ruff check
  apps/account-api` clean.
- `0008` follows the verified unique-**index** pattern (see §7) — model
  declares `UniqueConstraint(name="uq_organization_licenses_org_number")`
  matched by index name; a revoked/expired license keeps its number allocated,
  so duplicate numbers can never be re-created (history preserved).
- `_expire_overdue` is a lazy read-time transition (list/get only): no
  scheduled job, and a license without `expires_at` is never expired. It
  commits only when ≥1 license flips, so read paths stay write-free in the
  common case.
- DELETE semantics: status → `REVOKED` (soft). `PATCH` may set `status`
  explicitly (e.g. SUSPENDED, or reactivate a REVOKED/EXPIRED license).

---

## 3. Pending phases

Vertical slices; migration numbers from §4.4. Each phase ends with tests +
`docs` status update + a pause to confirm with the user.

### Phase 4 — API keys [ ]
DB `0009`. `OrganizationApiKeyService` + `find_by_hash`. API: list/create/
revoke/rotate (`/me/api-keys`). Tests: hash-only storage, raw key shown once,
revoke/rotate, scopes. Deps: Ph1. **Accept:** create key → raw key returned
once; rotating revokes old.

### Phase 5 — API-key auth [ ]
Deps module + `OrganizationApiContext`, scopes, Redis rate limit, `OrganizationApiRequest` writes (`0010`), `request_id` (echoed `X-Request-Id`). Tests: 401/403/429 matrix. Deps: Ph4. **Accept:** a key authenticates, is org-scoped, rate-limited, and audited.

### Phase 6 — Single document integration [ ]
Extend `DocumentService` (`0013` document columns), `OrganizationDocumentService`, patient resolver. API: `POST /integration/documents`, `GET /integration/documents/{id}`. Event `OrganizationDocumentSubmitted`. Tests: upload → status, doc-type conflict (422), `external_id` idempotency, MIME/size. Deps: Ph5 + resolver. **Accept:** org uploads a doc end-to-end through the existing pipeline.

### Phase 7 — Patient resolver [ ]
`OrganizationPatientResolver` + concurrency/race tests (spec §15, §4.9).
Deps: —. **Accept:** unknown email → PENDING account + Person + Patient + MedicalRecord exactly once under concurrency.

### Phase 8 — Notifications [ ]
DB `notifications` (part of `0013`); `NotificationService`; extend `notification-worker` (provider `send_message`, consume `notification.requested`); hook after analysis completed/failed for org-sourced docs. Tests: row created, email has no medical data, worker delivery. Deps: Ph6. **Accept:** client receives "document processed/failed" email with org name + secure link, no medical data.

### Phase 9 — Bulk upload [ ]
DB `0011`; `OrganizationBulkUploadService`; API `POST /integration/documents/bulk`, `GET /integration/batches/{id}(/items)`; batch events; partial failure/idempotency (`(org, external_id)` skip). Tests: batch state machine, per-item failures, duplicates, no giant transaction. Deps: Ph6/7. **Accept:** 100-doc batch, partial failures tracked per item, resubmission idempotent.

### Phase 10 — Organization schemas [ ]
DB `0012`; `OrganizationSchemaService`; API schemas CRUD + publish (immutable). Tests: versioning, publish-immutability, JSON-Schema validation. Deps: Ph1. **Accept:** org drafts/publishes versioned schemas without touching the canonical model.

### Phase 11 — Monitoring [ ]
`GET /organizations/me/api-usage` aggregates; `OrganizationApiRequest` volume; metrics/log notes. Tests: aggregation filters by org, no PII columns. Deps: Ph5. **Accept:** org sees requests/day, success/error, docs, batches, failures.

### Phase 12 — Registry verification extension point [ ]
Add `OrganizationRegistryProvider` `Protocol` + `OrganizationVerificationResult`; **no** provider implementation. Deps: Ph1. **Accept:** a future `FederalRegistryProvider` injects without changing `OrganizationService`.

---

## 4. Locked design reference (condensed from Rev 1)

### 4.1 Current state / platform assets (reused, not rebuilt)

| Asset | Where | Used by |
|---|---|---|
| JWT + OTP auth, `Account.status`, `email_normalized` UNIQUE | `app/dependencies/auth.py`, `app/services/auth.py` | management API; resolver |
| RBAC `ORGANIZATION_ADMIN` role + `ORGANIZATION_MANAGE` permission | `app/repositories/rbac.py` | management API |
| Document pipeline (`upload.requested → stored → uploaded → converted → analysis.completed`), S3, DLQ | `DocumentService`, `app/consumers/document_events.py` | ingestion |
| `PatientService.ensure_patient_for_account` IntegrityError reload pattern | `app/services/patient.py:43-53` | resolver races |
| `AuditLog` (`action/resource_type/resource_id/patient_id/metadata_/IP/UA`) | `app/models/audit_log.py` | security audit |
| `LoggingMiddleware` (PII-masking, logs every `/integration/*` path) | `app/middleware/request_logging.py` | monitoring |
| Migrations `0001…0005`, head `0005`, downgrade-safe, enums as VARCHAR | `migrations/alembic/versions/` | §4.4 |
| Test harness: sqlite `create_all`, fakeredis, `ASGITransport`, dep overrides | `apps/account-api/tests/conftest.py` | §5 |

### 4.2 Domain model (`app/domain/organization.py`)

Enums (already created in Phase 1): `OrganizationVerificationStatus`
(`unverified|pending|verified|rejected`), `BranchStatus` (`active|inactive`),
`OrganizationLicenseStatus`
(`active|expired|suspended|revoked|pending`), `OrganizationApiKeyStatus`
(`active|revoked|expired`), `OrganizationApiKeyScope`
(`organization.documents.upload | .bulk_upload | .read`, `organization.jobs.read`),
`BatchStatus` (`accepted|processing|completed|partial|failed`), `BatchItemStatus`
(`pending|accepted|rejected`), `OrganizationDocumentSchemaStatus`
(`draft|published`), `NotificationType` (`document_received|processed|
processing_failed`), `NotificationStatus` (`pending|sent|failed|read`),
`NotificationChannel` (`email`).

INN/OGRN helpers (Phase 1): `normalize_inn`/`inn_checksum_valid` (10|12 digits,
weighted control digits), `normalize_ogrn`/`ogrn_checksum_valid` (13 digits,
first-12 mod 11 mod 10).

`AuditAction` additions (each in its phase): `ORGANIZATION_UPDATED` ✓ (Ph1),
`ORGANIZATION_BRANCH_CREATED` / `_UPDATED` / `_DEACTIVATED` ✓ (Ph2),
`ORGANIZATION_LICENSE_CREATED` / `_UPDATED` / `_DEACTIVATED` ✓ (Ph3),
`API_KEY_CREATED`, `API_KEY_REVOKED`,
`API_KEY_AUTH_FAILED`, `INTEGRATION_DOCUMENT_UPLOADED`,
`INTEGRATION_BATCH_CREATED` (string values → fits `length=64`).

Config additions: `integration_api_hmac_key` (empty default; goes in
`_KEY_SETTINGS`, min 32 — production guard), `integration_api_key_prefix =
"ddorg"`, `integration_rate_limit_per_minute = 120`,
`integration_max_batch_size = 100`, `integration_validate_inn_checksum = True`
✓ (Ph1), `integration_request_log_sample = 1.0`.

### 4.3 Database schema

Conventions: `Uuid` PK `default=uuid4`, `DateTime(timezone=True)` UTC via
`utcnow()`, enums `native_enum=False`, names via `Base.metadata` convention.
All new columns nullable for existing rows (never force NOT NULL on prod data).

| Table | Key columns / constraints |
|---|---|
| `organizations` (modified) | + `inn` String(12) unique · `ogrn` String(13) unique · `legal_address` Text · `email` · `phone` · `website` · `verification_status` (default `UNVERIFIED`) |
| `organization_branches` | `organization_id` FK CASCADE · `code` String(32) · `name` · `address` · `phone` · `status` `BranchStatus` · `UniqueConstraint(organization_id, code, name="uq_organization_branches_org_code")` |
| `organization_licenses` | `organization_id` FK CASCADE · `license_number` String(64) · `license_type` · `status` · `issued_at`/`expires_at` Date · `scope` · `issuer` · `UniqueConstraint(organization_id, license_number, name="uq_organization_licenses_org_number")` |
| `organization_api_keys` | `organization_id` FK CASCADE · `name` · `prefix` String(16) · `key_hash` String(128) unique · `permissions` JSON(scopes) · `status` · `created_by_account_id` FK SET NULL · `expires_at`/`revoked_at`/`last_used_at` |
| `organization_api_requests` | `organization_id` FK CASCADE · `api_key_id` FK SET NULL · `request_id` · `method` · `path` · `status_code` · `duration_ms` · `ip_address` · `user_agent` · `error_code` · `created_at` (ix). **No bodies/files/canonical/PII** (spec §24) |
| `organization_upload_batches` | `organization_id` FK · `api_key_id` FK · `idempotency_key` · `status` `BatchStatus` · `total/accepted/failed_count` · `completed_at` · `uq_organization_upload_batches_org_idem` |
| `organization_upload_batch_items` | `batch_id` FK CASCADE · `document_id` FK SET NULL · `item_index` · `patient_email` · `document_type` · `external_id` · `status` `BatchItemStatus` · `error_code/message` · `uq_organization_upload_batch_items_batch_index` |
| `organization_document_schemas` | `organization_id` FK · `name` String(128) · `description` · `document_type` · `schema_definition` JSON · `version` (default 1) · `status` `OrganizationDocumentSchemaStatus` · `created_by_account_id` · `published_at` · `uq_organization_document_schemas_org_name_ver` (published = immutable) |
| `documents` (modified) | + `organization_id` FK SET NULL ix · `organization_branch_id` FK SET NULL ix · `external_id` · `idempotency_key` · `provided_document_type` · partial unique `uq_documents_organization_external_id` / `_idempotency_key` (PG + SQLite `postgresql_where`/`sqlite_where`) |
| `notifications` | `account_id` FK CASCADE · `organization_id` FK SET NULL · `type` · `channel` · `status` · `title` · `template` · `resource_type` (default `"document"`) · `resource_id` · `sent_at`/`read_at` |

Unchanged: `DocumentVersion`, `DocumentExtraction`, `DocumentProcessingJob`,
`Account`, `Patient`, `Person`, `MedicalRecord`, `AuditLog`,
`PatientAccessGrant` (already carries `organization_id`).

### 4.4 Migrations (8 on top of `0005`; each downgrade-safe, independently reviewable)

| Migration | Contents |
|---|---|
| `0006_organization_legal_data.py` ✓ | org legal columns + `verification_status` (server default `'UNVERIFIED'`) + `uq_organizations_inn`/`_ogrn` |
| `0007_organization_branches.py` ✓ | `organization_branches` + `(organization_id, code)` unique index (see note §7) |
| `0008_organization_licenses.py` ✓ | `organization_licenses` + `(organization_id, license_number)` unique index (see note §7) |
| `0009_organization_api_keys.py` | `organization_api_keys` + unique `key_hash` |
| `0010_organization_api_requests.py` | `organization_api_requests` + indexes |
| `0011_organization_upload_batches.py` | batches + items (drop items first on downgrade) |
| `0012_organization_document_schemas.py` | `organization_document_schemas` |
| `0013_notifications.py` + document source | `notifications`; `documents` source columns + partial unique indexes |

### 4.5 API-key architecture

- **Format:** `ddorg_<env>_<secret>`, env ∈ `liv|tst`, secret = `secrets.token_urlsafe(43)` (256-bit). `prefix` = first ~12 chars for display.
- **Hashing:** `HMAC_sha256(settings.integration_api_hmac_key, raw_key)` hex; only `key_hash` persisted — raw key never stored/logged (kept as `Authorization: Bearer <key>`).
- **Creation:** `create(org, name, scopes, expires_at?, created_by)` → `(record, raw_key)`; raw shown **once**. `last_used_at` updated best-effort in the auth dependency.
- **Status:** `active|revoked|expired`; inactive org ⇒ key unusable regardless.

### 4.6 Authentication & authorization

- Management (`/organizations/me/*`): JWT `get_current_account` → `require_roles(RoleCode.ORGANIZATION_ADMIN)` → `get_current_organization` (ACTIVE membership) → 403 `"no active organization membership"`. Every sub-resource scoped by `organization.id` (no IDOR).
- Integration (`/integration/*`): `Bearer` → hash → `find_by_hash` → 401 (none/revoked/expired) → org status ≠ ACTIVE → 403 → `OrganizationApiContext(organization, api_key, permissions)`. Per-endpoint scope `require_api_key_permission(scope)`; Redis sliding-window rate limit `rl:{api_key_id}:{minute}` vs `integration_rate_limit_per_minute` → 429.

### 4.7 Endpoints

Management (JWT + org_admin + member):

| Method/Path | Request → Response | Notes |
|---|---|---|
| `GET/PATCH /organizations/me` ✓ | — / `OrganizationUpdate` → `OrganizationResponse` | Ph1 |
| `GET/POST /organizations/me/branches` · `PATCH/DELETE /…/{id}` | `BranchCreate/Update` → `BranchResponse` · 204 | ✓ Ph2; dup code 409; DELETE = soft deactivate |
| `GET/POST /organizations/me/licenses` · `PATCH/DELETE /…/{id}` | `LicenseCreate/Update` → `LicenseResponse` · 204 | ✓ Ph3; dup number 409; DELETE = soft revoke; auto `EXPIRED` on list/get |
| `GET/POST /organizations/me/api-keys` · `DELETE/Rotate /…/{id}` | `ApiKeyCreate` → response (**raw once**) · 204 | list hides raw |
| `GET /organizations/me/api-usage` | `?from&to` → aggregates | Ph11 |
| `GET/POST /organizations/me/schemas` · `POST /…/{id}/publish` | schema CRUD + publish | Ph10; published immutable |

Integration (API key + scope):

| Method/Path | Scope | Notes |
|---|---|---|
| `POST /integration/documents` | `organization.documents.upload` | idempotent by `external_id`/`Idempotency-Key` (200 on dup) |
| `POST /integration/documents/bulk` | `organization.documents.bulk_upload` | 202 → `batch_id` |
| `GET /integration/documents/{id}` · `GET /integration/batches/{id}(/items)` | `organization.documents.read` | cross-org → 404 |
| `GET /integration/jobs/{id}` | `organization.jobs.read` | isolation via `doc.organization_id` |

Codes: 401 · 403 · 429 · 404 · 409 · 413 (oversized) · 415 (bad type) · 422.

### 4.8 Schemas (`app/schemas/organization.py` ✓, `integration.py`, `notification.py`)

- `OrganizationUpdate` ✓ — optional name/inn/ogrn/legal_address/email/phone/website; INN/OGRN normalized + checksum-checked; legal-data change → `PENDING` (re-verification).
- Branch ✓: `code ^[A-Za-z0-9_-]{1,32}$`, `name ≤255`, `address`, `phone`; PATCH `""` → `NULL`.
- License ✓: `license_number ≤64`, `license_type`, `status`, `issued_at`, `expires_at`, `scope`, `issuer`; `expires_at` must not precede `issued_at`; PATCH `""` clears `scope`/`issuer`; explicit `status` change allowed.
- ApiKey: `name`, `scopes` (required, non-empty), `expires_at?`; response includes `raw_key` only on create/rotate.
- Integration: upload request `patient_email` (Identity-validated), `document_type?`, `external_id?`, `branch_code?`, `title?`; response `document_id`, `status="processing"`, `external_id`, `patient_id`. Bulk: `items ≤ integration_max_batch_size`, `idempotency_key?`. Status reads only (no canonical content for orgs in v1).
- Notification (client, P1): `type`, `title`, `resource_type/id`, `status`, `read_at`.

### 4.9 Patient resolution (`OrganizationPatientResolver.resolve_by_email`)

`normalize email → find account → ensure patient → create missing chain`. Five cases:
1. Account + patient exist → existing context.
2. Account exists, no patient → Person (empty defaults) + Patient + MedicalRecord in one transaction.
3. No account → `get_or_create_by_identity` creates **PENDING** account, then case 2.
4. Unverified email → same as 1/2; stays PENDING until OTP verify.
5. Concurrent same-email → `email_normalized` UNIQUE + the existing IntegrityError→rollback→reload pattern (`app/services/patient.py:43-53`).

### 4.10 Document ingestion (single)

`POST /integration/documents` → auth+scope+rate limit → `resolve_by_email` → `DocumentService.create_organization_document` (reuses `_stage_upload`/`_publish`/same repos): skip `FREE_DOCUMENT_LIMIT` (org-sourced, server-side; Open Decision §7.1), set `organization_id`/`organization_branch_id`/`external_id`/`idempotency_key`/`provided_document_type`, `uploaded_by_account_id = NULL`. Org-provided `document_type` validated against `DocumentType` + stored; invalid → 422. No AI re-classification in v1.

### 4.11 Bulk upload

Never one giant transaction (arch §67-68): validate/return existing batch by `(org, idempotency_key)` → create batch `ACCEPTED` (202, publish `OrganizationBatchCreated`) → per item its **own transaction**: `PENDING` → `resolve_by_email` → create document (dup `external_id` → item `REJECTED`, no new doc) → `ACCEPTED`/`REJECTED` + error → finalize `COMPLETED|PARTIAL|FAILED` + publish `OrganizationBatchCompleted`. Synchronous per-request loop (bounded, testable); consumer per-item is a P1 option.

### 4.12 Notifications

account-api: after `analysis.completed`/`processing.failed` for org-sourced docs → `Notification` row + publish `NotificationRequested`. Payload = org name + availability + secure link, **no diagnosis/values/filenames**. notification-worker: handle `NotificationRequested`; provider protocol `send_message(*, to, channel, subject, body)`; routing keys `auth.otp.requested,notification.requested`. Rows `PENDING → SENT/FAILED → READ`.

### 4.13 Organization document schemas

JSON-Schema metadata registry; versions monotonic per `(org, name)`; publish freezes the draft (immutable). `document_type` = platform enum. Never overwrite canonical (spec §23); LLM consumption deferred.

### 4.14 Monitoring

- API usage → `organization_api_requests` (high-volume, non-PII).
- Security audit → `AuditLog` (key CRUD + `API_KEY_AUTH_FAILED`, org updates).
- Medical audit → existing patient-scoped `AuditLog`, untouched.
- v1 metrics = structured logs + `GET /organizations/me/api-usage` DB aggregates; Prometheus = P2. `request_id` echoed as `X-Request-Id`.

---

## 5. Tests

- **Unit** (`tests/unit/`): `test_inn_ogrn.py` ✓ (checksums), `test_organization.py` ✓ (service + 0006 round-trip), `test_api_key.py`, `test_patient_resolver.py`, `test_bulk_upload.py`, `test_schema.py`.
- **API**: `tests/test_organizations_api.py` ✓; `tests/test_integration_api.py`.
- **Security**: cross-org 404, revoked/expired 401, inactive org 403, missing scope 403, no duplicate docs on retry (concurrency via `ASGITransport`).
- **Run**: `uv run --project apps/account-api pytest apps/account-api` + `uvx ruff check apps packages tests`. S3/RabbitMQ-leg tests live in root `tests/integration` (marked `integration`).

---

## 6. Implementation order

1. Phase 1 — Organization core. [x]
2. Phase 2 — Branches. [x]
3. Phase 3 — Licenses. [x]
4. Phase 4 — API keys. [ ] (next)
5. Phase 5 — API-key auth. [ ]
6. Phase 7 — Patient resolver. [ ] (ordered before 6: §4.9 unblocks single upload)
7. Phase 6 — Single document integration. [ ]
8. Phase 8 — Notifications. [ ]
9. Phase 9 — Bulk upload. [ ]
10. Phase 10 — Organization schemas. [ ]
11. Phase 11 — Monitoring. [ ]
12. Phase 12 — Registry verification extension. [ ]

Each phase: implement → update this status → pause for confirmation.

---

## 7. Conventions & decisions

### Gotchas (verified)

- SQLAlchemy stores `str, Enum` members by **name** (`native_enum=False`); migration backfill/defaults must use uppercase (e.g. `'UNVERIFIED'`).
- Full alembic chain is not SQLite-portable (0002 uses PG `btrim`); migration tests exercise individual revisions in isolation.
- Unique *constraints* cannot be `ALTER`ed on SQLite (`NotImplementedError`) — implement them as **unique indexes** (`op.create_index(..., unique=True)`) named like the model constraint (pattern: 0006 inn/ogrn, 0007 branch code, 0008 license number).
- `PATCH ""` clears a field → `NULL`; verification status can only move **to `PENDING`** via the human API.
- `uv run` at the workspace root resolves all members incl. ai-worker → `torch` (no mac-x86 wheel); use `uv run --project apps/account-api …`.
- Follow `docs/development/CONTRIBUTING.md`: `Annotated` service aliases, router `raise_for`, service commits once.

### Open decisions (defaults chosen; none block a phase)

1. **INN/OGRN checksum** — enforce lengths always; checksum behind `integration_validate_inn_checksum=True` (disabled if registry has odd cases). ✓ applied in Ph1.
2. **Rate limit / batch size** — 120 req/min/key, max 100 items — configurable.
3. **Integration read of canonical** — status + `document_date` only in v1; `read_canonical` scope possible later.
4. **Notification timing** — process-completed/-failed only; "received" is optional P1 (two-emails risk).
5. **Org schema format** — JSON Schema, published immutable; not yet consumed by ai-worker.
6. **API-key scopes** — the 4 of §4.2; no `full`/per-type scopes.
7. **`organization_api_requests` retention** — 90 days; purge in monitoring phase.
8. **Org docs quota** — no free-plan cap (server-side submissions).
9. **Bulk processing** — synchronous per-item in-request; RabbitMQ consumer is P1.

### Risks (mitigations in place)

- Concurrent account/patient creation → `email_normalized` UNIQUE + reload pattern; explicit concurrency tests.
- IDOR in integration reads → mandatory org-scope checks returning 404; security tests per resource.
- Duplicate docs on retry → partial unique `(org, external_id)` + `(org, idempotency_key)`.
- Org schema/canonical coupling → strict separation (metadata only).
- Notification data leakage → template-driven body (org name + availability only).
- Large bulk in one transaction → per-item transactions + bounded batch size.
- Migration integrity → nullable columns for existing rows; PG downgrade verification per `docs/development/MIGRATIONS.md`.
- Secret material → `INTEGRATION_API_HMAC_KEY` in `_KEY_SETTINGS` production guards.
- API-key sprawl/leakage → prefix display, single-show raw, revoke/rotate/expiry, `last_used_at`.