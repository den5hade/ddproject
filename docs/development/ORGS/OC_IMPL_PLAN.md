# Organization Domain — Implementation Specification

## 1. Executive Summary

Turn the existing `Organization`/`OrganizationMembership` records into a full organization-integration contour: legal data, branches, licenses, API keys, a machine-to-machine integration API, a patient resolver, single+bulk document ingestion that reuses the existing processing pipeline, client notifications, organization document schemas, API usage monitoring, and the registry-verification extension point.

Everything builds on existing infrastructure — **no parallel architecture**:
- Reuses JWT + RBAC (`organization_admin` / `organization.manage`) for human management endpoints; new API-key auth only for machine endpoints.
- Reuses `DocumentService` (`apps/account-api/app/services/documents.py`) upload flow, staging, RabbitMQ events, S3, `DocumentVersion`/`DocumentProcessingJob`/`DocumentExtraction`.
- Reuses `Account.email_normalized` UNIQUE + `PatientService.ensure_patient_for_account` IntegrityError pattern for race-safe patient creation.
- Reuses the existing `Consumer`/`Publisher` (`packages/messaging`) and the `notification-worker`.
- Adds 8 logical DB migrations on top of migration head `0005`.

Delivered as 12 vertical slice phases (spec §32). P0 scope = legal data → branches → licenses → API keys → API-key auth → single document integration → patient resolver → document source → notification. P1 = bulk, idempotency, monitoring, schemas. P2 = UI/dashboards, registry verification.

## 2. Current State Analysis

Verified against the repository:

| Area | Current state |
|---|---|
| `Organization` model | `apps/account-api/app/models/organization.py` — table `organizations`, only `id/name/type/status/created_at/updated_at`. No INN/OGRN/legal fields. |
| `OrganizationMembership` | Same file; unique `(organization_id, account_id)`; `status` (`MembershipStatus.PENDING/ACTIVE/LEFT`), `joined_at`, `left_at`. |
| `Document` / `DocumentVersion` | `apps/account-api/app/models/document.py` — no `organization_id`, `organization_branch_id`, `external_id`, `provided_document_type`, `idempotency_key`. |
| `DocumentExtraction` | `app/models/extraction.py` — already has `schema_name`, `schema_version`, `status`, `data`, `confidence` (org schemas plug in here). |
| `DocumentProcessingJob` | `app/models/processing_job.py` — reuses `ProcessingJobType.PDF_CONVERSION`. |
| Auth | JWT via `get_current_account` (`app/dependencies/auth.py`); OTP flow; `Account.status` PENDING/ACTIVE/BLOCKED/DELETED; `email_normalized` UNIQUE nullable. |
| RBAC | `RoleCode.ORGANIZATION_ADMIN` + `PermissionCode.ORGANIZATION_MANAGE` already seeded (`app/repositories/rbac.py`); `require_roles`/`require_permission` deps (`app/dependencies/rbac.py`). |
| Document pipeline | `DocumentService.create_document` stages upload → `document.upload.requested` → objectstorage-worker → S3 → `document.stored` → `document.uploaded` → ai-worker → `document.analysis.completed` → account-api consumer (`app/consumers/document_events.py`) persists extraction + sets status. Routing keys conform to `messaging` topic exchange `pdf.events`, DLQ per queue. |
| S3 | `StorageService` (`app/services/storage.py`) with `build_key(tenant_id, patient_id, document_id, version_id, filename)`, presigned URLs; already patient-centric, org agnostic. |
| Notifications | `account-api` publishes only OTP (`app/services/notifications.py`); `notification-worker` consumes only `auth.otp.requested` (`apps/notification-worker/app/main.py`); provider protocol has only `send(*, to, channel, code)`. No `notifications` table. |
| Audit | `AuditLog` (`app/models/audit_log.py`) with `action` (AuditAction enum), `resource_type/id`, `patient_id`, `metadata_`, IP/UA. |
| Logging | `LoggingMiddleware` (`app/middleware/request_logging.py`) logs requests, masks PII incl. `email`, `name`, `organization`, tokens. |
| API surface | Routers registered in `app/api/v1/__init__.py` under global prefix `/api/v1` (settings `api_prefix`). No organization/integration routers. |
| Migrations | `migrations/alembic/versions/0001…0005`, head `0005`; PG-verified downgrade-safe; enums as VARCHAR (`native_enum=False`). |
| Tests | `apps/account-api/tests/conftest.py` — sqlite `create_all`, fakeredis, `ASGITransport`, dependency overrides incl. `StubNotificationGateway`, `DocumentService(publisher=None)`. `make lint` = `uvx ruff check apps packages tests`; `make test` = `uv run --all-packages pytest apps tests`. |

## 3. Gap Analysis

| Requirement (arch §1/§10) | Current | Gap | Action |
|---|---|---|---|
| Legal data (INN, OGRN, address) | ❌ | columns + validation + unique indexes | create |
| Branches | ❌ | table + CRUD + doc linkage | create |
| Licenses | ❌ | table + CRUD | create |
| API keys | ❌ | model, hashing, create/list/revoke/rotate/expire | create |
| API-key auth + org context | ❌ | dependency + isolation + rate limit + request ID + audit | create |
| Integration API (single upload) | ❌ | `/integration/documents` | create |
| Patient resolver (email) | partial | account flow exists; org-triggered resolve/create chain + race handling missing | create |
| Document source (org/branch) | ❌ | columns + pipeline passthrough | modify `Document` + `DocumentService` |
| Document type from org | partial | `DocumentType` enum exists; org-provided type not captured | modify `Document` |
| External ID / idempotency | ❌ | columns + partial unique indexes + header handling | modify `Document` |
| Bulk upload | ❌ | batch/item tables + API + async-ish per-item processing | create |
| Notifications | partial | OTP only | add `notifications` table + `NotificationRequested` + worker handler |
| Organization schemas | partial | `DocumentExtraction.schema_name` exists | add registry table + CRUD + immutable publish |
| API monitoring | partial | `LoggingMiddleware` exists | add `organization_api_requests` table + aggregation endpoint |
| Rate limiting | ❌ | no per-key limiter | create (Redis) |
| Registry verification | ❌ | must be extension point only | create `Protocol` + status enum, no provider |
| Org access vs. medical access | ❌ | must stay separate (arch §58-59) | document + enforce |

## 4. Target Architecture

```
                         Organization
                              │
              ┌───────────────┼────────────────┐
              │               │                │
        Branches          Licenses          API Keys ──▶ Integration API
              │                                        (JWT = management;
              │                                         API key = machine)
              │                        ┌──────────────┬──────────────────────┐
              │                        ▼              ▼                      ▼
              │                 patient resolver   single upload         bulk upload
              │                        │              │                      │
              └─────────────┐    Account→Person→Patient→MedicalRecord      Batches/Items
                            ▼              │        │
                         Document ◄────────┘        ▼
                            │             existing pipeline (S3, RabbitMQ, ai-worker, canonical)
                            ▼                              │
                    DocumentExtraction ────────────────────┘
                            │ (on analysis.completed, org-sourced)
                            ▼
                    Notification (email, no medical data) ──▶ Client
```

Key principles:
- **Human vs machine separation** (spec §9): management API = JWT + active `OrganizationMembership` + `organization_admin`; integration API = API key + org context + key permissions. An API key can never manage API keys.
- **Submission vs. history access** (arch §58-59): organization gets `document submission authority` only; no automatic permanent `PatientAccessGrant`. Reading a patient's history stays a separate grant flow.
- One pipeline (spec §17/§66): `OrganizationDocumentService → DocumentService → Document/DocumentVersion/ProcessingJob` — never a second processing pipeline.
- Org schemas never replace the platform canonical schema (spec §23).

## 5. Domain Model Changes

New file `apps/account-api/app/domain/organization.py` (mirrors existing enum-module conventions in `domain/account.py`, `domain/medical.py`):

```python
class OrganizationVerificationStatus(str, Enum):
    UNVERIFIED = "unverified"; PENDING = "pending"; VERIFIED = "verified"; REJECTED = "rejected"

class BranchStatus(str, Enum):
    ACTIVE = "active"; INACTIVE = "inactive"

class OrganizationLicenseStatus(str, Enum):
    ACTIVE = "active"; EXPIRED = "expired"; SUSPENDED = "suspended"; REVOKED = "revoked"; PENDING = "pending"

class OrganizationApiKeyStatus(str, Enum):
    ACTIVE = "active"; REVOKED = "revoked"; EXPIRED = "expired"

class OrganizationApiKeyScope(str, Enum):
    DOCUMENTS_UPLOAD = "organization.documents.upload"
    DOCUMENTS_BULK_UPLOAD = "organization.documents.bulk_upload"
    DOCUMENTS_READ = "organization.documents.read"
    JOBS_READ = "organization.jobs.read"

class BatchStatus(str, Enum):
    ACCEPTED = "accepted"; PROCESSING = "processing"; COMPLETED = "completed"; PARTIAL = "partial"; FAILED = "failed"

class BatchItemStatus(str, Enum):
    PENDING = "pending"; ACCEPTED = "accepted"; REJECTED = "rejected"

class OrganizationDocumentSchemaStatus(str, Enum):
    DRAFT = "draft"; PUBLISHED = "published"

class NotificationType(str, Enum):
    DOCUMENT_RECEIVED = "document_received"
    DOCUMENT_PROCESSED = "document_processed"
    DOCUMENT_PROCESSING_FAILED = "document_processing_failed"

class NotificationStatus(str, Enum):
    PENDING = "pending"; SENT = "sent"; FAILED = "failed"; READ = "read"

class NotificationChannel(str, Enum):
    EMAIL = "email"
```

Extend `apps/account-api/app/domain/access.py` `AuditAction` with:
`ORGANIZATION_UPDATED, ORGANIZATION_BRANCH_CREATED/… , ORGANIZATION_LICENSE_…, API_KEY_CREATED, API_KEY_REVOKED, API_KEY_AUTH_FAILED, INTEGRATION_DOCUMENT_UPLOADED, INTEGRATION_BATCH_CREATED` (string enum values, e.g. `"API_KEY_CREATED"`). The `AuditAction` column uses `length=64` — fits.

Extend `apps/account-api/app/core/config.py`:
- `integration_api_hmac_key: str = ""` → add to `_KEY_SETTINGS` (secret, min 32).
- `integration_api_key_prefix: str = "ddorg"` (display prefix `ddorg_liv_` / `ddorg_tst_`).
- `integration_rate_limit_per_minute: int = 120`
- `integration_max_batch_size: int = 100`
- `integration_validate_inn_checksum: bool = True`
- `integration_request_log_sample: float = 1.0` (optional sampling)
- Add to `_security_issues` nothing extra (hmac key handled via `_KEY_SETTINGS`).

New contracts in `packages/contracts/contracts/events/` (registered in `__init__.py`):
- `OrganizationDocumentSubmitted` — `event_id, schema_version=1, occurred_at, organization_id, document_id, patient_id, external_id: str | None`
- `OrganizationBatchCreated` — `organization_id, batch_id, total_count`
- `OrganizationBatchCompleted` — `organization_id, batch_id, processed_count, failed_count`
- `OrganizationPatientCreated` — `organization_id, account_id, patient_id` (no email/PII)
- `NotificationRequested` — `notification_id, account_id, channel, to, subject, body, resource_type, resource_id, occurred_at`

All consumers idempotent by event_id (existing pattern: `async with message.process()`; account-api handlers keyed on document/version IDs; new events are informational — dedup by notification_id on insert).

## 6. Database Schema

All tables follow repo conventions: `Uuid` PK `default=uuid4`, `DateTime(timezone=True)` UTC via `utcnow()` (`app/models/utils.py`), enums `native_enum=False`, naming via `Base.metadata` convention.

**Modify `Organization`** (`app/models/organization.py`):
```python
inn: Mapped[str | None] = mapped_column(String(12), unique=True, nullable=True)
ogrn: Mapped[str | None] = mapped_column(String(13), unique=True, nullable=True)
legal_address: Mapped[str | None] = mapped_column(Text, nullable=True)
email: Mapped[str | None] = mapped_column(String(255), nullable=True)
phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
website: Mapped[str | None] = mapped_column(String(255), nullable=True)
verification_status: Mapped[OrganizationVerificationStatus] = mapped_column(
    Enum(OrganizationVerificationStatus, native_enum=False, length=16),
    default=OrganizationVerificationStatus.UNVERIFIED,
)
```
(unique=True on nullable columns — PG/SQLite allow multiple NULLs; safe. Auto-generated `uq_organizations_inn` / `uq_organizations_ogrn`.)

**New `OrganizationBranch`** — table `organization_branches`:
- `id` UUID pk · `organization_id` FK `organizations.id` CASCADE, index · `code` String(32) · `name` String(255) · `address` Text nullable · `phone` String(32) nullable · `status` `BranchStatus` default ACTIVE · `created_at`/`updated_at`.
- `UniqueConstraint(organization_id, code, name="uq_organization_branches_org_code")`.
- Deactivate (never hard-delete) → documents keep historical branch ref (FK `SET NULL` on the document as safety net, but deactivation preserves the row).

**New `OrganizationLicense`** — table `organization_licenses`:
- `id` uuid pk · `organization_id` FK CASCADE index · `license_number` String(64) · `license_type` String(64) nullable · `status` `OrganizationLicenseStatus` default ACTIVE · `issued_at` Date nullable · `expires_at` Date nullable · `scope` Text nullable · `issuer` String(255) nullable · `created_at`/`updated_at`.
- `UniqueConstraint(organization_id, license_number, name="uq_organization_licenses_org_number")`.
- History preserved: old licenses are set to EXPIRED/REVOKED, never deleted.

**New `OrganizationApiKey`** — table `organization_api_keys`:
- `id` uuid pk · `organization_id` FK CASCADE index · `name` String(255) · `prefix` String(16) · `key_hash` String(128) unique · `permissions` JSON (list of `OrganizationApiKeyScope` codes) · `status` `OrganizationApiKeyStatus` default ACTIVE · `created_by_account_id` FK `accounts.id` SET NULL nullable · `created_at` · `expires_at` nullable · `revoked_at` nullable · `last_used_at` nullable.

**New `OrganizationApiRequest`** — table `organization_api_requests`:
- `id` uuid pk · `organization_id` FK CASCADE index · `api_key_id` FK `organization_api_keys.id` SET NULL nullable index · `request_id` String(64) · `method` String(8) · `path` String(255) · `status_code` Integer · `duration_ms` Integer · `ip_address` String(45) nullable · `user_agent` String(512) nullable · `error_code` String(64) nullable · `created_at` (index).
- **No** bodies/files/canonical JSON/patient PII (spec §24).

**New `OrganizationUploadBatch`** — table `organization_upload_batches`:
- `id` uuid pk · `organization_id` FK CASCADE index · `api_key_id` FK SET NULL nullable · `idempotency_key` String(255) nullable · `status` `BatchStatus` default ACCEPTED · `total_count` Integer · `accepted_count` Integer default 0 · `failed_count` Integer default 0 · `created_at` · `completed_at` nullable.
- `UniqueConstraint(organization_id, idempotency_key, name="uq_organization_upload_batches_org_idem")`.

**New `OrganizationUploadBatchItem`** — table `organization_upload_batch_items`:
- `id` uuid pk · `batch_id` FK `organization_upload_batches.id` CASCADE index · `document_id` FK `documents.id` SET NULL nullable · `item_index` Integer · `patient_email` String(255) · `document_type` `DocumentType` nullable · `external_id` String(255) nullable · `status` `BatchItemStatus` default PENDING · `error_code` String(64) nullable · `error_message` String(512) nullable · `created_at`/`updated_at`.
- `UniqueConstraint(batch_id, item_index, name="uq_organization_upload_batch_items_batch_index")`.

**New `OrganizationDocumentSchema`** — table `organization_document_schemas`:
- `id` uuid pk · `organization_id` FK CASCADE index · `name` String(128) · `description` Text nullable · `document_type` `DocumentType` · `schema_definition` JSON (JSON Schema) · `version` Integer default 1 · `status` `OrganizationDocumentSchemaStatus` default DRAFT · `created_by_account_id` FK SET NULL nullable · `published_at` nullable · `created_at`/`updated_at`.
- `UniqueConstraint(organization_id, name, version, name="uq_organization_document_schemas_org_name_ver")`.
- Published versions immutable (no PATCH/DELETE after publish).

**Modify `Document`** (`app/models/document.py`) — add:
```python
organization_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)
organization_branch_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("organization_branches.id", ondelete="SET NULL"), nullable=True, index=True)
external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
provided_document_type: Mapped[DocumentType | None] = mapped_column(Enum(DocumentType, native_enum=False, length=32), nullable=True)
```
Partial unique indexes (org-scoped idempotency, cross-dialect):
```python
Index("uq_documents_organization_external_id", "organization_id", "external_id", unique=True,
      postgresql_where=text("organization_id IS NOT NULL AND external_id IS NOT NULL"),
      sqlite_where=text("organization_id IS NOT NULL AND external_id IS NOT NULL")),
Index("uq_documents_organization_idempotency_key", "organization_id", "idempotency_key", unique=True,
      postgresql_where=text("organization_id IS NOT NULL AND idempotency_key IS NOT NULL"),
      sqlite_where=text("organization_id IS NOT NULL AND idempotency_key IS NOT NULL")),
```
`uploaded_by_account_id` stays nullable (org uploads have no human uploader).

**New `Notification`** — table `notifications` (`app/models/notification.py`):
- `id` uuid pk · `account_id` FK `accounts.id` CASCADE index · `organization_id` FK `organizations.id` SET NULL nullable index · `type` `NotificationType` · `channel` `NotificationChannel` · `status` `NotificationStatus` default PENDING · `title` String(255) · `template` String(64) nullable · `resource_type` String(64) default `"document"` · `resource_id` UUID nullable · `created_at` · `sent_at` nullable · `read_at` nullable.

**Unchanged:** `DocumentVersion`, `DocumentExtraction`, `DocumentProcessingJob`, `Account`, `Patient`, `Person`, `MedicalRecord`, `AuditLog`, `PatientAccessGrant` (org-scoped grants already possible via existing `organization_id` column).

Register all new models in `apps/account-api/app/models/__init__.py`.

## 7. Alembic Migration Plan

Head = `0005`. Add 8 migrations (arch §61), each downgrade-safe (PG-verified) and independently reviewable:

**`0006_organization_legal_data.py`** (`0006`, revises `0005`)
- Add nullable `inn`, `ogrn`, `legal_address`, `email`, `phone`, `website`, `verification_status` to `organizations`.
- Add `uq_organizations_inn`, `uq_organizations_ogrn` unique indexes.
- Backfill: existing rows default `verification_status='unverified'`; INN/OGRN remain NULL (arch §214-217 — no NOT NULL, no forced data fill).
- Downgrade: `op.drop_index` + `op.drop_column` (only if both indexes contain no NULL violations — safe to drop in downgrade because the columns go with them).

**`0007_organization_branches.py`**
- Create `organization_branches` + indexes + `uq_organization_branches_org_code`.
- Downgrade: drop table.

**`0008_organization_licenses.py`**
- Create `organization_licenses` + indexes + unique constraint.
- Downgrade: drop table.

**`0009_organization_api_keys.py`**
- Create `organization_api_keys` + unique `key_hash` + index on `organization_id`.
- Downgrade: drop table.

**`0010_organization_api_requests.py`**
- Create `organization_api_requests` + indexes on `organization_id`, `api_key_id`, `created_at`.
- Downgrade: drop table.

**`0011_organization_upload_batches.py`**
- Create `organization_upload_batches` + `organization_upload_batch_items` + unique constraints/indexes.
- Downgrade: drop both (items first).

**`0012_organization_document_schemas.py`**
- Create `organization_document_schemas` + unique constraint.
- Downgrade: drop table.

**`0013_notifications.py` + document source/idempotency**
- Create `notifications`.
- Add to `documents`: `organization_id`, `organization_branch_id`, `external_id`, `idempotency_key`, `provided_document_type` (all nullable → safe for existing rows).
- Add partial unique indexes `uq_documents_organization_external_id`, `uq_documents_organization_idempotency_key` (PG + SQLite variants).
- Downgrade: drop indexes, drop FK columns, drop `notifications`.

Migration-by-migration: each migration touches only its own tables/columns; no cross-table data migration except the default backfill in `0006`. Existing production data is never required to satisfy NOT NULL.

## 8. API-Key Architecture

- **Format:** `ddorg_<env>_<secret>` where env ∈ `liv|tst` and secret = `secrets.token_urlsafe(43)` (32 random bytes → 256-bit entropy, URL-safe base64). Example: `ddorg_liv_8f2ac…`. Stored `prefix` = `ddorg_liv_8f2ac` (first ~12 chars) for display.
- **Hashing:** `HMAC_sha256(settings.integration_api_hmac_key, raw_key)` hex. Only `key_hash` is persisted — raw key is never stored or logged (LoggingMiddleware already redacts `authorization`/`x-api-key`; keep API keys sent as `Authorization: Bearer <key>`).
- **Creation:** `OrganizationApiKeyService.create(org, name, scopes, expires_at?, created_by)` returns `(key_record, raw_key)`; raw key shown **once** in the `POST` response, cannot be retrieved later.
- **Status:** `active | revoked | expired`. `expired` derived (or explicitly set) when `expires_at < now`; `revoked` via `revoke()`. Inactive organization ⇒ key unusable regardless of status.
- **Permissions/scopes:** JSON list of `OrganizationApiKeyScope` codes; each integration endpoint declares `Depends(require_api_key_permission(scope))`.
- **Rotate:** `POST /organizations/me/api-keys/{id}/rotate` → revokes old key, creates new key with same scopes, returns new raw key once.
- **last_used_at:** updated best-effort (non-blocking commit) inside the auth dependency.

**FastAPI dependency** — new `apps/account-api/app/dependencies/integration.py`:

```text
extract Bearer token
   → raw key
   → hash (HMAC-SHA256)
   → find_by_hash(key_hash)
   → None/revoked  → 401
   → expires_at past → 401 (401 "expired", 403 for revoked per spec)
   → load organization; status != ACTIVE → 403
   → OrganizationApiContext(organization, api_key, permissions)
```

```python
@dataclass(frozen=True)
class OrganizationApiContext:
    organization: Organization
    api_key: OrganizationApiKey
    permissions: frozenset[OrganizationApiKeyScope]

async def get_organization_api_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db),
) -> OrganizationApiContext: ...

def require_api_key_permission(scope: OrganizationApiKeyScope) -> Callable[..., OrganizationApiContext]: ...
```

Each integration endpoint's `OrganizationApiRequest` row is written after the response (fire-and-forget or in the dependency's `finally`) with `request_id = str(uuid4())` (echoed in `X-Request-Id` response header).

## 9. Authentication & Authorization

Two security models never mixed:

### Management API (human) — prefix `/organizations/me/*`
- Auth: JWT via existing `get_current_account`.
- RBAC: `require_roles(RoleCode.ORGANIZATION_ADMIN)` (reuse `app/dependencies/rbac.py`).
- Org resolution: new dependency `get_current_organization` (`app/dependencies/organization.py`) — loads the account's **active** `OrganizationMembership` and returns the `Organization`. No active membership → 403 `"no active organization membership"`.
- Every sub-resource query is scoped by `organization.id` (no IDOR).

### Integration API (machine) — prefix `/integration/*`
- Auth: API key via `get_organization_api_context` (§8).
- Isolation: every retrieve (`documents/{id}`, `batches/{id}`, `batches/{id}/items`, `jobs/{id}`) loads the resource and asserts `resource.organization_id == context.organization.id`; mismatch → 404 (never reveals existence).
- Permission scopes per endpoint (§10).
- Rate limit: `enforce_api_key_rate_limit` dependency (Redis sliding-window `INCR` on `rl:{api_key_id}:{minute}` vs `integration_rate_limit_per_minute`), 429 on breach. Independent of business logic; configurable.

**Why separate:** an API key is a long-lived machine credential with narrow scopes and rate limits; a JWT human session carries full RBAC roles. Keys must not escalate to management (spec §9). Org submission rights never auto-create `PatientAccessGrant` (arch §58-59) — history access stays a separate specialist/grant flow.

## 10. Endpoint Inventory

### Organization Management API (JWT + organization_admin + active membership)
| Method/Path | Auth/Scope | Request → Response | Notes |
|---|---|---|---|
| `GET /organizations/me` | JWT, org_admin, member | — → `OrganizationResponse` | incl. `verification_status`, counts |
| `PATCH /organizations/me` | same | `OrganizationUpdate` → `OrganizationResponse` | name, legal data, contact info; scoped to own org |
| `GET /organizations/me/branches` | same | — → `list[OrganizationBranchResponse]` | |
| `POST /organizations/me/branches` | same | `OrganizationBranchCreate` → 201 `OrganizationBranchResponse` | duplicate `code` → 409 |
| `PATCH /organizations/me/branches/{id}` | same | `OrganizationBranchUpdate` → response | isolation: 404 if not owned |
| `DELETE /organizations/me/branches/{id}` | same | — → 204 | soft deactivate (status=INACTIVE) |
| `GET /organizations/me/licenses` | same | — → `list[OrganizationLicenseResponse]` | |
| `POST /organizations/me/licenses` | same | `OrganizationLicenseCreate` → 201 | dup number → 409 |
| `PATCH /organizations/me/licenses/{id}` | same | `OrganizationLicenseUpdate` → response | |
| `DELETE /organizations/me/licenses/{id}` | same | — → 204 | soft (status=REVOKED/EXPIRED) |
| `GET /organizations/me/api-keys` | same | — → `list[OrganizationApiKeyListItem]` | prefix, status, created_at, last_used_at, expires_at (§81) |
| `POST /organizations/me/api-keys` | same | `OrganizationApiKeyCreate` → 201 `OrganizationApiKeyResponse` (raw key **once**) | |
| `DELETE /organizations/me/api-keys/{id}` | same | — → 204 | revoke |
| `POST /organizations/me/api-keys/{id}/rotate` | same | → `OrganizationApiKeyResponse` (new raw once) | revokes old |
| `GET /organizations/me/api-usage` (P1) | same | query `?from&to` → aggregates | requests/day, success/error, docs, batches, failures |
| `GET /organizations/me/schemas` / `POST` / `POST /{id}/publish` (P1) | same | schema CRUD + publish (immutable) | |

### Integration API (API key + scope)
| Method/Path | Scope | Request → Response | Notes |
|---|---|---|---|
| `POST /integration/documents` | `organization.documents.upload` | multipart: file + `OrganizationDocumentUploadRequest` JSON part → 201 `OrganizationDocumentUploadResponse` | idempotent by `external_id`/`Idempotency-Key` (200 on duplicate) |
| `POST /integration/documents/bulk` | `organization.documents.bulk_upload` | `OrganizationBulkUploadRequest` (multipart JSON + files) → 202 `OrganizationBulkUploadResponse` (batch_id) | |
| `GET /integration/documents/{id}` | `organization.documents.read` | — → `OrganizationDocumentStatusResponse` | isolation; 404 cross-org |
| `GET /integration/batches/{id}` | `organization.documents.read` | — → `OrganizationBatchResponse` | isolation |
| `GET /integration/batches/{id}/items` | `organization.documents.read` | — → `list[OrganizationBatchItemResponse]` | isolation |
| `GET /integration/jobs/{id}` | `organization.jobs.read` | — → `JobResponse` | isolation via doc.organization_id |

Response codes: 401 missing/invalid/revoked/expired key · 403 inactive org / missing scope · 429 rate limit · 404 cross-org IDOR · 409 duplicate external_id/branch code · 413 oversized · 415 bad type · 422 validation.

## 11. Pydantic Schemas

New files: `apps/account-api/app/schemas/organization.py`, `apps/account-api/app/schemas/integration.py`, `apps/account-api/app/schemas/notification.py`. Conventions from existing schemas (`app/schemas/document.py`): Pydantic v2, `model_config = ConfigDict(from_attributes=True)`, `UUID` ids.

Highlights:
- `OrganizationUpdate` — optional `name`, `inn`, `ogrn`, `legal_address`, `email`, `phone`, `website`; validators normalize + checksum-check INN/OGRN (see §12); sets `verification_status=PENDING` when legal data changed (re-verification).
- `OrganizationResponse` — from `Organization` model (existing pattern).
- `OrganizationBranchCreate/Update/Response` — `code` `^[A-Za-z0-9_-]{1,32}$`, `name≤255`, `address`, `phone`.
- `OrganizationLicenseCreate/Update/Response` — `license_number≤64`, `license_type`, `status`, `issued_at`, `expires_at`, `scope`, `issuer`.
- `OrganizationApiKeyCreate` — `name`, `scopes: list[OrganizationApiKeyScope]` (required, non-empty), `expires_at?`.
- `OrganizationApiKeyResponse` — includes `raw_key` only in create/rotate response; list item excludes it.
- `OrganizationDocumentUploadRequest` — `patient_email` (Identity-validation), `document_type?`, `external_id?`, `branch_code?`, `title?`.
- `OrganizationDocumentUploadResponse` — `document_id`, `status` (`"processing"`), `external_id`, `patient_id` (no PII).
- `OrganizationBulkUploadRequest` — `items: list[Item]` (≤`integration_max_batch_size`), `idempotency_key?`; each item: `patient_email`, `document_type?`, `external_id?`, `filename`, `branch_code?`.
- `OrganizationBulkUploadResponse` — `batch_id`, `status`, `total_count`.
- `OrganizationBatchResponse` / `OrganizationBatchItemResponse` — batch status, counts (masked email: keep only `patient_email` truncated `a***@d.com`).
- `OrganizationDocumentStatusResponse` — `document_id`, `external_id`, `status`, `document_date`, `processing_job_status` (status read only; no canonical content read for orgs in v1).
- `NotificationResponse` (client-side, P1) — `type`, `title`, `resource_type/id`, `status`, `read_at`.

## 12. Patient Resolution

New service `apps/account-api/app/services/organization_patient_resolver.py`:

```python
class OrganizationPatientResolver:
    async def resolve_by_email(self, organization_id: UUID, raw_email: str) -> PatientContext: ...
```

Pipeline: `normalize email → find account → ensure patient → create missing chain → return`.

Handles all spec §15 cases:
1. **Account exists + patient exists** → `PatientService.ensure_patient_for_account` returns existing context.
2. **Account exists, no patient** → creates Person (empty defaults; `Person.name` has default `""`), links `account.person_id`, creates `Patient` + `MedicalRecord` in one transaction.
3. **No account** → `AccountRepository.get_or_create_by_identity(email)` creates a **PENDING** account (`email_normalized` + `email` set); then case 2. Not email-verified (spec §16 — reuse OTP lifecycle; first `verify_otp` promotes to ACTIVE).
4. **Unverified email** → same as case 1/2; account stays PENDING until OTP verify.
5. **Concurrent same-email requests** → rely on `accounts.email_normalized` UNIQUE + the existing `PatientService.ensure_patient_for_account` IntegrityError→rollback→reload pattern (`app/services/patient.py:43-53`); wrap the resolver so an `IntegrityError` on account insert triggers `rollback()`, reload by identity, retry `ensure`. No duplicate users (spec §15/16).

Reuse `<AccountRepository | PatientService | PersonRepository | PatientRepository.create_with_medical_record>` unchanged. The resolver commits via `PatientService._ensure`'s own commit; document creation then commits separately (acceptable v1; idempotency keys prevent duplicates — see Open Decisions).

## 13. Document Ingestion

Reuse the existing pipeline end-to-end (spec §17, arch §66):

```
POST /integration/documents
  → API-key auth + scope + rate limit
  → OrganizationPatientResolver.resolve_by_email
  → OrganizationDocumentService.create_document(...)
      → DocumentService (extended) creates Document(status=PENDING, org/branch/external/idempotency/provided_type)
      → DocumentVersion(v1)
      → DocumentProcessingJob(PDF_CONVERSION)
      → stage file in storage_temp_dir
      → publish document.upload.requested
      → commit
  → objectstorage-worker → S3 → document.stored → account-api sets PROCESSING → document.uploaded
  → ai-worker → document.analysis.completed → extraction + status COMPLETED/FAILED
```

**Minimal change to `DocumentService`:** add an optional method `create_organization_document(...)` (or a `source` param) that reuses `_stage_upload`, `_publish`, `_document_patient`, and the same repository calls as `create_document` (lines 139-211) but:
- skips the `FREE_DOCUMENT_LIMIT` quota check (client quota is per account plan; org-sourced docs are a different dimension — document in Open Decisions),
- sets `organization_id`, `organization_branch_id` (resolved from `branch_code`), `external_id`, `idempotency_key`, `provided_document_type`,
- leaves `uploaded_by_account_id = NULL`,
- on `document.analysis.completed` (existing handler) — no changes needed; fields already persist.

**Document type handling (spec §19):** if the org provides a `document_type`, validate against `DocumentType`; store it in `provided_document_type`; set platform `document_type` to the same value. Unknown/invalid → **422** (never silently discard). No AI re-classification in v1 (future step).

## 14. Bulk Upload

New `OrganizationBulkUploadService` (`app/services/organization_bulk_upload.py`); logic never one giant transaction (arch §67-68):

1. `POST /integration/documents/bulk` → validate `Idempotency-Key` (or `idempotency_key` in body): existing batch with same `(organization_id, idempotency_key)` → return it (200).
2. Create `OrganizationUploadBatch(status=ACCEPTED, total_count=N)`; commit; publish `OrganizationBatchCreated`. → 202 with batch_id.
3. For each item (≤ `integration_max_batch_size`), **own transaction**:
   - insert `OrganizationUploadBatchItem(status=PENDING)` (unique `(batch_id, item_index)`),
   - `resolve_by_email` → patient,
   - call `DocumentService.create_organization_document`; duplicate `(organization_id, external_id)` → item `REJECTED` idempotent-duplicate (no new doc),
   - on success: item `ACCEPTED`, `document_id` set; on any error: rollback-item, item `REJECTED` + `error_code/message`, continue.
4. Finalize batch: `status = COMPLETED | PARTIAL | FAILED`, counts set; publish `OrganizationBatchCompleted`.

Retrieval: `GET /integration/batches/{id}` (status/counts), `GET /integration/batches/{id}/items` (item status incl. per-item errors). Progress is per-item; retry of an item = re-submission with the same `external_id` (idempotent, no duplicate). Synchronous per-request processing chosen for v1 (simple, testable, bounded by max batch size); moving item processing to a RabbitMQ consumer is a P1 extension (Open Decisions).

## 15. Notification Flow

Integrate with existing `notification-worker` (spec §22, arch §71-72).

- **Account-api side:** new `notification` model + `NotificationService` (`app/services/notification.py`). In `app/consumers/document_events.py`, after `on_document_analysis_completed` (or `on_document_processing_failed`), if `document.organization_id is not None`, create a `Notification` row (type `DOCUMENT_PROCESSED` or `DOCUMENT_PROCESSING_FAILED`) and publish `NotificationRequested`. A `DOCUMENT_RECEIVED` notification can be emitted at acceptance (P1 option; decision below).
- **Payload (no medical data):** `to` (patient email), `subject`, `body` = generic text with **organization name**, document **availability** and a secure link to the platform; no diagnosis/values/filenames.
- **notification-worker:** extend `apps/notification-worker/app/main.py` to accept `NotificationRequested` alongside `AuthOtpRequested`; extend provider protocol (`apps/notification-worker/app/providers/base.py`) with `send_message(*, to, channel, subject, body)`; implement in `console.py` (log) and `smtp.py` (EmailMessage). Extend `notification_routing_keys` config to `"auth.otp.requested,notification.requested"`.
- Notification row status transitions `PENDING → SENT/FAILED` (worker), `READ` (client reads — P1 client endpoint `GET /notifications/me`).

## 16. Organization Document Schemas

New `OrganizationDocumentSchema` registry (P1) + `OrganizationSchemaService`:

- CRUD + versioning: `POST /organizations/me/schemas` (draft v1), `PATCH` (draft only), `POST /{id}/publish` → `ver = +1`? No — publish freezes the current draft as the published version (immutable). Schema `name` is unique per org; versions are monotonic per `(org, name)`.
- `schema_definition` = JSON Schema; `document_type` = platform `DocumentType` (the org maps its own type onto the platform enum).
- **Interaction with pipeline:** org schemas are metadata for future ai-worker extraction + `DocumentExtraction.schema_name/schema_version` (already persisted). The platform canonical schema remains authoritative and separate; org schemas never overwrite it (spec §23). Actual LLM consumption of org schemas is P2/deferred.
- Registry verification boundary: add `OrganizationRegistryProvider` `Protocol` (`verify(inn, ogrn) -> OrganizationVerificationResult`) in `app/services/verification.py` (P1/P2 stub, arch §75) — Organization domain never depends on a specific government API.

## 17. API Monitoring

- **DB usage log:** every integration request writes an `OrganizationApiRequest` row (§6): org, api_key, request_id, method, path, status, duration_ms, ip, ua, error_code. No bodies/canonical/PII.
- **Three log classes kept distinct (spec §24):**
  - *API usage* → `organization_api_requests` (high-volume, non-PII).
  - *Security audit* → existing `AuditLog` for key create/revoke/rotate + API-key auth failures (`API_KEY_AUTH_FAILED`), org updates.
  - *Medical audit* → existing `AuditLog` patient-scoped actions stay untouched.
- **Metrics:** `packages/observability` is a stub (arch §82). v1 = structured logs (`LoggingMiddleware` already logs every `/integration/*` path, masks PII) + DB aggregates via `GET /organizations/me/api-usage`. Prometheus counters can be added in P2.
- **Request IDs:** `request_id` generated in the integration dependency, echoed as `X-Request-Id`; middleware logs can include it.

## 18. Security Model

- API key secret: only HMAC-SHA256 hash stored; raw key shown once; revoke/expire/active flow; prefix display; `last_used_at`.
- Org isolation: **every** integration query filters by `context.organization.id`; IDOR checks on documents/batches/jobs return 404 on cross-org (arch §79-80).
- Inactive organization ⇒ API key 403 (even if key active).
- Missing permission scope ⇒ 403.
- Rate limit per key (429), upload size limit (reuse `max_upload_bytes`), file MIME+magic validation (existing `_stage_upload`/`_detect_mime`/`_detect_magic`).
- Idempotency: `(organization_id, external_id)` and `(organization_id, idempotency_key)` partial unique constraints; repeated requests return existing resources, never duplicate docs.
- No medical data in logs/emails/events (only IDs, org name, availability).
- HTTPS/TLS assumed at ingress (production).

## 19. Event Model

New events (`packages/contracts/contracts/events/`, §5) reuse `pdf.events` topic exchange and existing `Publisher`. Each event: `event_id`, `schema_version=1`, `occurred_at`, plus domain ids. No sensitive payloads.

| Event | Routing key | Producer → consumer | Purpose |
|---|---|---|---|
| `OrganizationDocumentSubmitted` | `organization.document.submitted` | account-api → (self) | internal/audit + future webhook |
| `OrganizationBatchCreated` | `organization.batch.created` | account-api → (self) | batch lifecycle |
| `OrganizationBatchCompleted` | `organization.batch.completed` | account-api → (self) | batch lifecycle |
| `OrganizationPatientCreated` | `organization.patient.created` | account-api → (self) | audit/metrics |
| `NotificationRequested` | `notification.requested` | account-api → notification-worker | email delivery |

Idempotency: consumer dedupers keyed on `event_id`/`notification_id`; existing DLQ pattern already handles failures/retries. No new RabbitMQ topic needed.

## 20. Service & Repository Structure

New files under `apps/account-api/app/` (adapting arch §63-64 to the actual repo where `services/x.py` + `repositories/x.py` per domain is the norm):

```
domain/organization.py        # enums (already in §5)
repositories/organization.py  # OrganizationRepository (legal data), BranchRepository, LicenseRepository
repositories/org_api_key.py   # find_by_hash/create/revoke/update_last_used/list_by_org
repositories/org_api_request.py
repositories/upload_batch.py  # batch + items
repositories/org_schema.py
repositories/notification.py
services/organization.py          # management: org read/update, branch CRUD, license CRUD
services/organization_api_key.py  # create/list/revoke/rotate (raw-key emission)
services/organization_patient_resolver.py
services/organization_document.py # wraps DocumentService for org single upload
services/organization_bulk_upload.py
services/organization_schema.py
services/notification.py          # create + publish NotificationRequested
services/verification.py          # OrganizationRegistryProvider Protocol (extension point)
dependencies/organization.py      # get_current_organization (membership)
dependencies/integration.py       # get_organization_api_context, require_api_key_permission, rate limit, request log
api/v1/organizations.py           # management router
api/v1/integration.py             # integration router
schemas/organization.py / integration.py / notification.py
```

Router = HTTP validation → service (business logic) → repository (DB). Extended `DocumentService` (§13) stays in `app/services/documents.py`.

## 21. Pydantic Schemas

Covered in §11. Schemas follow existing `ConfigDict(from_attributes=True)` style; all multi-field validation in validators (normalization + checksums for INN/OGRN, Identity for email, enum coercion for `document_type`).

## 22. Testing Strategy

Conventions: `apps/account-api/tests/conftest.py` (sqlite `create_all`, fakeredis, `ASGITransport`, dependency overrides). New overrides needed for the integration deps (`get_organization_api_context` → seeded key) and `NotificationService`.

**Unit** (`tests/unit/`): INN validation (10/12-digit checksums), OGRN checksum, API-key generation/hashing/expiry/revocation, `OrganizationPatientResolver` (cases 1-5 + concurrency via two simultaneous resolver calls), batch state machine (ACCEPTED→processing→COMPLETED/PARTIAL/FAILED per-item), schema publish immutability, rate limiter window.

**API**: `tests/test_organizations_api.py` (me/branches/licenses/api-keys CRUD, isolation), `tests/test_integration_api.py` (single upload 201 → status 200, bulk 202 → batch status, duplicate idempotency returns existing, IDOR 404).

**Security**: org A key vs org B doc/batch/job — 404; revoked key 401; expired key 401; inactive org 403; missing scope 403; duplicate requests do not duplicate documents (concurrency test reusing `ASGITransport`).

**Concurrency**: two requests creating the same email patient concurrently → one account/patient; IntegrityError path covered.

Run: `uv run --project apps/account-api pytest apps/account-api` and `uvx ruff check apps packages tests` (Makefile `lint`/`test`). Add integration tests to root `tests/integration` (marked `integration`) for the S3/RabbitMQ leg.

## 23. Implementation Phases

Vertical slices; each phase has objective/files/DB/API/services/tests/dependencies/acceptance. Migration numbers from §7.

**Phase 1 — Organization core.** DB: `0006` + `Organization` fields + domain enums + schemas. Service `OrganizationService` + `get_current_organization`/`require_organization_admin` deps. API: `GET|PATCH /organizations/me` (`app/api/v1/organizations.py`, register in `app/api/v1/__init__.py`). Audit `ORGANIZATION_UPDATED`. Tests: validation, uniqueness, permissions, serialization, migration. Deps: none. Accept: existing orgs digest PATCH with INN/OGRN/address; admin-only.

**Phase 2 — Branches.** DB: `0007`. API: branch CRUD (+soft deactivate). Tests: CRUD, org isolation, duplicate code, deactivation keeps history. Deps: Ph1. Accept: 1:N branches, `branch_code` usable by later phases.

**Phase 3 — Licenses.** DB: `0008`. API: license CRUD (status/validity/scope/issuer). Tests: CRUD, isolation, duplicate number, expiry transitions. Deps: Ph1. Accept: org holds multiple licenses; future-registry-ready schema.

**Phase 4 — API keys.** DB: `0009`. `OrganizationApiKeyService` + `find_by_hash`. API: list/create/revoke/rotate. Tests: hash-only storage, raw key shown once, revoke/rotate, scopes. Deps: Ph1. Accept: create key → raw key returned once; rotating revokes old.

**Phase 5 — API-key auth.** Deps module + `OrganizationApiContext`, scopes, rate limit (Redis), `OrganizationApiRequest` writes (`0010`), `request_id`. Tests: 401/403/429 matrix. Deps: Ph4. Accept: a key authenticates, is org-scoped, rate-limited, and audited.

**Phase 6 — Single document integration.** Extend `DocumentService` (`0013` document columns part), `OrganizationDocumentService`, patient resolver. API: `POST /integration/documents`, `GET /integration/documents/{id}`. Events: `OrganizationDocumentSubmitted`. Tests: upload → status, doc-type conflict (422), external_id idempotency, MIME/size. Deps: Ph5 + resolver. Accept: org uploads a doc end-to-end through the existing pipeline.

**Phase 7 — Patient resolver.** `OrganizationPatientResolver` + concurrency/race tests (spec §15). All 5 cases covered; used by Ph6. Accept: unknown email → PENDING account + Person + Patient + MR exactly once under concurrency.

**Phase 8 — Notifications.** DB `notifications`; `NotificationService`; extend `notification-worker` (provider `send_message`, consume `notification.requested`); hook after analysis completed/failed for org-sourced docs. Tests: notification row created, email has no medical data, worker delivery to console/smtp stub. Deps: Ph6. Accept: client receives "document processed/failed" email with org name + secure link, no medical data.

**Phase 9 — Bulk upload.** DB `0011`; `OrganizationBulkUploadService`; API `POST /integration/documents/bulk`, `GET /integration/batches/{id}(/items)`; batch events; partial failure/idempotency. Tests: batch state machine, per-item failures, duplicate external_id skipped, no giant transaction. Deps: Ph6/7. Accept: 100-doc batch, partial failures tracked per item, resubmission idempotent.

**Phase 10 — Organization schemas.** DB `0012`; `OrganizationSchemaService`; API schemas CRUD + publish (immutable). Tests: versioning, publish-immutability, JSON-Schema validation. Deps: Ph1. Accept: org drafts/publishes versioned schemas without touching canonical model.

**Phase 11 — Monitoring.** `GET /organizations/me/api-usage` aggregates; `OrganizationApiRequest` volume handling; metrics/log notes. Tests: aggregation filters by org, no PII columns. Deps: Ph5. Accept: org sees requests/day, success/error, docs, batches, failures.

**Phase 12 — Registry verification extension point.** Add `OrganizationRegistryProvider` Protocol + `OrganizationVerificationResult`; no provider implementation. Deps: Ph1. Accept: future `FederalRegistryProvider` can be injected without changing `OrganizationService`.

## 24. File-by-File Change Plan

*Create* unless noted *modify*. All paths real.

**account-api** (`apps/account-api/`):
- modify `app/domain/access.py` — new AuditActions
- create `app/domain/organization.py`
- modify `app/models/organization.py`, `app/models/document.py`, `app/models/__init__.py`
- create `app/models/organization_branch.py`, `organization_license.py`, `organization_api_key.py`, `organization_api_request.py`, `organization_upload_batch.py`, `organization_document_schema.py`, `notification.py`
- modify `app/services/documents.py` (add `create_organization_document`-style extension, reuse internals)
- create `app/services/organization.py`, `organization_api_key.py`, `organization_patient_resolver.py`, `organization_document.py`, `organization_bulk_upload.py`, `organization_schema.py`, `notification.py`, `verification.py`
- create `app/repositories/organization.py`, `org_api_key.py`, `org_api_request.py`, `upload_batch.py`, `org_schema.py`, `notification.py`
- modify `app/dependencies/__init__.py`; create `app/dependencies/organization.py`, `app/dependencies/integration.py`
- create `app/api/v1/organizations.py`, `app/api/v1/integration.py`; modify `app/api/v1/__init__.py` (register both)
- create `app/schemas/organization.py`, `app/schemas/integration.py`, `app/schemas/notification.py`
- modify `app/core/config.py` (new settings §5)
- modify `app/consumers/document_events.py` (notification hook)
- modify `app/middleware/request_logging.py` (already redacts; add `request_id` passthrough — optional)
- tests: create `tests/unit/test_organization.py`, `test_inn_ogrn.py`, `test_api_key.py`, `test_patient_resolver.py`, `test_bulk_upload.py`, `test_schema.py`, `tests/test_organizations_api.py`, `tests/test_integration_api.py`; modify `tests/conftest.py` (override integration deps)

**contracts** (`packages/contracts/contracts/events/`): create `organization_document_submitted.py`, `organization_batch_created.py`, `organization_batch_completed.py`, `organization_patient_created.py`, `notification_requested.py`; modify `__init__.py`.

**notification-worker** (`apps/notification-worker/app/`): modify `main.py` (handle `NotificationRequested`), `providers/base.py` (+`send_message`), `providers/console.py`, `providers/smtp.py`, `config.py` (routing keys).

**migrations** (`migrations/alembic/versions/`): create `0006…0013` per §7.

**infra**: `.env.example` — add `INTEGRATION_API_HMAC_KEY`, `INTEGRATION_RATE_LIMIT_PER_MINUTE`, `INTEGRATION_MAX_BATCH_SIZE`.

## 25. Commit Plan

One small, compiling, test-passing commit per logical slice (adapt of spec §34):
1. `org: legal data model, migration 0006, domain enums, /organizations/me get+patch`
2. `org: branches (0007) CRUD + isolation tests`
3. `org: licenses (0008) CRUD`
4. `org: api keys (0009) create/list/revoke/rotate + hashing`
5. `org: api-key auth dependency, scopes, rate limit, request log (0010)`
6. `org: document source columns + single integration upload (0013 partial)`
7. `org: patient resolver + concurrency safety`
8. `org: notifications table + worker NotificationRequested flow (0013 notifications)`
9. `org: bulk upload batches/items (0011) + endpoint`
10. `org: document schemas (0012) + publish immutability`
11. `org: api-usage aggregation + monitoring`
12. `org: registry verification extension point`

Each commit: passes `make lint` + relevant `apps/account-api` tests, independently reviewable, no mixed concerns.

## 26. Definition of Done

Per arch §104, this stage is done when:
- **Org:** INN, OGRN, legal address present, validated, unique indexes; `verification_status` lifecycle.
- **Branch:** 1:N CRUD, org isolation, active/inactive (soft), unique `code`.
- **License:** multiple per org, CRUD, status, validity.
- **API key:** create, hash-only storage, prefix, revoke, expire, permissions, `last_used_at`; raw once.
- **Integration API:** API-key auth, org context, rate limit, request ID, idempotency, single upload, status endpoint.
- **Patient:** resolve by normalized email, create account/person/patient/medical record, race-protected, no duplicates.
- **Document:** org + branch source, document type (provided + platform), external ID, existing pipeline reused.
- **Notification:** document received/processed/failed flows, email, secure link, no medical data.
- **Bulk:** batch, items, partial failures, retry, idempotency.
- **Monitoring:** request log, key usage, auth failures, latency, success/error metrics.
- **Schemas:** org schema, versioning, validation, publish, immutable published versions.
- No dead code / no duplicate pipeline; all new code lint- and test-green.

## 27. Open Decisions

**(1) INN/OGRN checksum enforcement**
- Why it matters: fake legal data in production orgs is a compliance risk both ways (invalid vs rejected-legit).
- Recommended default: Pydantic validators enforce length (`INN` 10|12 digits, `OGRN` 13 digits) always; checksum (`integration_validate_inn_checksum=True`) enabled behind config so it can be disabled if the registry of record has odd cases.
- Alternative: format-only validation, checksums in future `RegistryProvider`.

**(2) API rate limits & max batch size**
- Why: real numbers depend on broker/S3 capacity.
- Default: 120 req/min/key, max batch 100 items — configurable via settings.
- Alternative: per-org quotas table; bulk counts as `max(1, items//10)` toward the limit.

**(3) Whether integration API may read document status / canonical content**
- Default: status + `document_date` only, no canonical read in v1 (keeps "no history access" boundary clean).
- Alternative: grant `organization.document.read_canonical` scope later.

**(4) Notification timing**
- Default: process-completed/process-failed only (org-sourced). "Document received" email is optional P1.
- Alternative: send "received" immediately on acceptance; risk: two emails with little content for fast pipelines.

**(5) Organization document schema format**
- Default: JSON Schema stored in `schema_definition`, published versions immutable; not yet consumed by ai-worker.
- Alternative: platform-defined Pydantic model registry first; org schemas later map onto it.

**(6) API-key scope granularity**
- Default: the 4 scopes in §5 (upload, bulk, read, jobs).
- Alternative: per-document-type scopes or ID-less coarse `full` scope — rejected (no management via keys).

**(7) Retention for `organization_api_requests`**
- Default: keep 90 days, purge synthetically in monitoring phase; sampled at 100%.
- Alternative: sample (e.g., 10%) or move to log-store; revisit after volume measurement.

**(8) Quota policy for org-sourced documents**
- Default: no free-plan cap; org docs bypass client `FREE_DOCUMENT_LIMIT` (they're server-side submissions, not client uploads).
- Alternative: org plan quota (count per org/month) in P2.

**(9) Bulk processing sync vs consumer**
- Default: synchronous per-item loop in-request (bounded, testable).
- Alternative: RabbitMQ consumer per batch item (P1) for scale without request-timeout risk.

Decisions (2)-(9) do **not** block implementation; defaults above unblock each phase.

## 28. Risks

- **Concurrent account/patient creation** — mitigated by `email_normalized` UNIQUE + IntegrityError reload pattern (already proven in `PatientService`); explicit concurrency tests.
- **IDOR in integration reads** — mitigated by mandatory org-scope checks returning 404; security tests per resource.
- **Duplicate medical documents on retry** — mitigated by `(organization_id, external_id)` + `(organization_id, idempotency_key)` partial unique constraints; duplicate tests.
- **Org schema/canonical model coupling** — mitigated by strict separation (org schemas are metadata; canonical remains platform-owned).
- **Notification leakage of medical data** — email body is template-driven with org name + availability only; provider payload reviewed; no canonical/doc content.
- **Large bulk in one transaction** — mitigated by per-item transactions and bounded batch size.
- **Migration/data integrity** — all new columns nullable for existing rows; PG downgrade verification per convention (`docs/development/MIGRATIONS.md`).
- **Secret material** — new `INTEGRATION_API_HMAC_KEY` added to production startup guards (`_security_issues`).
- **API-key sprawl / leakage** — prefix display, single-show raw key, revoke/rotate/expiry, `last_used_at` visibility.

## 29. Implementation Status

Updated after each phase (per the working agreement: implement a phase →
update this status → ask before the next phase).

| Phase | Scope | Status | Notes |
|---|---|---|---|
| 1 | Organization core | ✅ **DONE** | `0006` + legal-data columns + `GET/PATCH /organizations/me` |
| 2 | Branches | ⏳ next | |
| 3 | Licenses | pending | |
| 4 | API keys | pending | |
| 5 | API-key auth | pending | |
| 6 | Single document integration | pending | |
| 7 | Patient resolver | pending | |
| 8 | Notifications | pending | |
| 9 | Bulk upload | pending | |
| 10 | Organization schemas | pending | |
| 11 | Monitoring | pending | |
| 12 | Registry verification extension | pending | |

### Phase 1 — implemented 2026-09-14

Files created:
- `apps/account-api/app/domain/organization.py` — all enums of §5 plus
  `normalize_inn`/`inn_checksum_valid`/`normalize_ogrn`/`ogrn_checksum_valid`
  (official control-digit schemes) and `OrganizationNotFoundError`,
  `OrganizationLegalDataConflictError`.
- `apps/account-api/app/schemas/organization.py` — `OrganizationUpdate`
  (normalize + length/checksum INN/OGRN, checksum behind
  `integration_validate_inn_checksum`), `OrganizationResponse`.
- `apps/account-api/app/repositories/organization.py` — `get_by_id`,
  `find_by_inn`, `find_by_ogrn`, `get_active_organization_for_account`.
- `apps/account-api/app/services/organization.py` — `OrganizationService`
  `update_organization` (unique pre-check, legal-change → `PENDING`,
  commits, writes `ORGANIZATION_UPDATED` audit).
- `apps/account-api/app/dependencies/organization.py` — `get_current_organization`,
  `require_organization_admin`, `CurrentOrganization`/`OrganizationAdmin`/
  `OrganizationServiceDep` aliases; 403 `"no active organization membership"`.
- `apps/account-api/app/api/v1/organizations.py` — `GET|PATCH /organizations/me`,
  registered in `app/api/v1/__init__.py`.
- `migrations/alembic/versions/0006_organization_legal_data.py` — adds
  nullable `inn`/`ogrn`/`legal_address`/`email`/`phone`/`website` +
  `verification_status` (server_default `'UNVERIFIED'`, matching the stored
  enum-member-name format — see §29 note), unique indexes
  `uq_organizations_inn`/`uq_organizations_ogrn`; downgrade drops them.
- Tests: `tests/unit/test_inn_ogrn.py`, `tests/unit/test_organization.py`
  (service + 0006 upgrade/downgrade round-trip on SQLite), `tests/test_organizations_api.py`.

Files modified:
- `app/domain/access.py` — `AuditAction.ORGANIZATION_UPDATED` added (the remaining
  audit actions of §5 land in their phases).
- `app/core/config.py` — `integration_validate_inn_checksum: bool = True`.
- `app/models/organization.py` — new columns per §6; `Text` import added.
- `app/api/v1/http_errors.py` — `OrganizationNotFoundError → 404`,
  `OrganizationLegalDataConflictError → 409`.

Notes / decisions applied in Phase 1:
- SQLAlchemy stores `str, Enum` members by **name** (`native_enum=False`),
  confirmed empirically (e.g. `MembershipStatus.ACTIVE` → `'ACTIVE'`), so the
  migration backfill/server default uses `'UNVERIFIED'` (uppercase), not the
  `.value`.
- The full alembic chain is not SQLite-portable (0002 uses PG `btrim`), so the
  migration test exercises `0006` upgrade/downgrade in isolation against a
  synthetic 0005-shape `organizations` table.
- `PATCH` with `""` clears the field (→ `None`); clearing legal data also moves
  status to `PENDING`.
- Verification status is only ever transitioned to `PENDING` by edits; the
  human API cannot self-set `VERIFIED`/`REJECTED` (registry provider = §23 Phase 12).
- §25 commit 1 (`org: legal data model, migration 0006, domain enums, /organizations/me get+patch`) intended for this phase; commit not yet created.