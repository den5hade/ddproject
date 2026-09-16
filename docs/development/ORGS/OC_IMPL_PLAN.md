# Organization Domain — Implementation Plan

Implementation plan for the organization integration contour: legal data,
branches, licenses, API keys, a machine-to-machine integration API, patient
resolution, single + bulk document ingestion through the existing pipeline,
client notifications, organization document schemas, API-usage monitoring, and
the registry-verification extension point. Built on existing infrastructure
only — **no parallel architecture**. Sources for depth: `docs/development/ORGS/OAI_IMPL_ARCH.md` (arch) + `docs/development/ORGS/OAI_IMPL_SPEC.md` (spec).

**Revision 7** — Phase 4a re-planned as **admin organization onboarding** per
`docs/development/ORGS/OAI_ONBOARD_IMPL_PLAN.md`: a `system_admin` provisions
organizations and connects representatives by email. **No public**
`POST /organizations` self-registration (the never-committed 4a code was
reverted). Endpoints move to `/api/v1/admin/organizations`
(+ `/…/{organization_id}/members`); representative authorization is
`OrganizationMembership.role` (`owner` default, `admin` allowed) **only** — no
global `organization_admin` grant (the transitional-grant idea is removed; the
`/organizations/me/*` global-role check migrates to the membership role in 4b);
account resolution reuses existing identities (no duplicate accounts);
audit `ORGANIZATION_CREATED` + `ORGANIZATION_ADMIN_ADDED`; representative
notification is recorded at onboarding (delivery lands in 4f). Migration `0010`
is unchanged (`created_by_account_id` + `role`); `0006–0009` history unchanged.
**Implemented + verified** (Phase 4a `[x]`): full suite 335 passed, `ruff`
clean; Phase 4b is next — see §6 and the Phase 4a Implementation Status block.

**Revision 8** — Phase 4b (organization context & membership-role
authorization) completed: `/organizations/me/*` authorizes via the resolved
`OrganizationMembership.role ∈ {owner, admin}` — the legacy global
`organization_admin` `AccountRole` check is dropped (onboarding never granted
it); multi-membership current-org selection is explicit via the
`X-Organization-Id` header (ambiguous → 400, unknown → 404) instead of an
implicit "first membership"; new reads `GET /organizations`,
`GET /organizations/{id}`, `GET /organizations/{id}/members` (org-scoped, no
IDOR; cross-org → 404; `member` reads context but cannot manage). Full suite
**347 passed**, `ruff` clean. Phase 4c is next — see §6 and the Phase 4b
Implementation Status block.

**Revision 9** — Phase 4c (API-key auth & verification policy) completed:
`dependencies/integration.py` answers `Bearer <api-key>` with an
`OrganizationApiContext` — HMAC hash lookup, revoked/expired → 401, org
`status ≠ ACTIVE` → 403, verification `REJECTED` → 403, per-key Redis
minute-window rate limit (`ApiKeyRateLimiter`, default 120/min) → 429, per-key
`permissions` JSON enforced per endpoint (`require_api_key_permission`), and a
best-effort `last_used_at` + `API_KEY_AUTH_FAILED` audit. `LoggingMiddleware`
echoes a client-`X-Request-Id` or generated id and persists non-PII
`organization_api_requests` rows (`0011`; org/api_key NULL when auth failed) for
`/integration/*`. Stub `POST /integration/documents` (501) exercises the full
chain; real ingestion lands in 4d. Full suite **367 passed**, `ruff` clean.
Phase 4d is next — see §6 and the Phase 4c Implementation Status block.

**Revision 10** — Phase 4d (integration API & patient resolver) completed:
real `POST /integration/documents` (201 new / 200 idempotent replay by
`external_id` or `Idempotency-Key`, 409 on conflicting keys) and
`GET /integration/documents/{id}` (org-scoped, read scope, cross-org → 404);
`OrganizationPatientResolver` unlocks the upload (email-only identity; reuses
`get_or_create_by_identity` + `ensure_patient_for_account`, PENDING account
default, IntegrityError→rollback→reload race recovery); migration
`0012_organization_document_source.py` (documents `organization_id` /
`organization_branch_id`/`external_id`/`idempotency_key`/`provided_document_type`
+ partial unique indexes) + `DocumentService.create_organization_document`
(quota-skipped, `uploaded_by_account_id = NULL`, PENDING, pipeline event) +
`OrganizationDocumentSubmitted` contract event (best-effort publish) +
`INTEGRATION_DOCUMENT_UPLOADED` audit; renumbered pending migrations — batches
`0013`, schemas `0014`, notifications `0015`. Full suite **402 passed**, `ruff`
clean. Phase 4e is next — see §6 and the Phase 4d Implementation Status block.

**Revision 11** — Phase 4e (bulk upload) completed: migration
`0013_organization_upload_batches.py` (batch header + per-item ledger, partial
unique index `uq_organization_upload_batches_org_idem` for `(org, idempotency_key)`
batch idempotency, unique `uq_organization_upload_batch_items_batch_index`);
`OrganizationUploadBatch`/`OrganizationUploadBatchItem` models;
`OrganizationBulkUploadService` with per-item **own** transactions (arch §67–68) —
resolve patient → `create_organization_document` (dup `external_id` → item
REJECTED, rest of the batch continues) → item ACCEPTED + audit, then `_finalize`
rolls up `COMPLETED|PARTIAL|FAILED`; `POST /integration/documents/bulk` (202 new
/ 200 replay by `Idempotency-Key`, `metadata` JSON array `Form` + `files:
list[UploadFile]`, count mismatch / over `integration_max_batch_size` → 422) +
`GET /integration/batches/{id}` and `/items` (read scope, cross-org → 404);
`OrganizationBatchCreated`/`OrganizationBatchCompleted` events
(`organization.batch.created`/`.completed`) + per-item
`organization.document.submitted`; `populate_existing` on `get_batch` so a cached
identity-map header never shadows the finalize counters in the POST response.
Account-api suite **426 passed**, `ruff` clean on Phase 4e paths. Phase 4f is
next — see §6 and the Phase 4e Implementation Status block.

**Revision 6** — Phase 4a (organization self-registration) was planned/staged in
this format; **superseded by Revision 7** (admin onboarding).

**Revision 5** — Phase 4 (API keys) completed; `0009` marked done;
`API_KEY_CREATED/REVOKED` audit actions, api-key schemas/service/endpoints folded
into §4; Phase 5 marked next.

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
| 4 | API keys | [x] done |
| 4a | Organization onboarding (admin) | [x] |
| 4b | Organization context & membership-role authorization | [x] |
| 4c | API-key auth & verification policy | [x] |
| 4d | Integration API & patient resolver | [x] |
| 4e | Bulk upload | [x] |
| 4f | Notifications | [ ] |
| 4g | Organization schemas | [ ] |
| 4h | Monitoring | [ ] |
| 4i | Registry verification + ownership/invite | [ ] |

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
  set exclusively by the registry provider (Phase 4i).

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

### Phase 4 — API keys [x]

**Objective.** Machine-to-machine API keys: list/create/revoke/rotate under
`/organizations/me/api-keys`; raw key shown exactly once; only the HMAC hash
persists; rotating revokes the old key.

**Changes.** Config `integration_api_hmac_key` (added to `_KEY_SETTINGS`,
production ≥32) + `integration_api_key_prefix = "ddorg"`; helpers in new
`app/domain/api_key.py` (`generate_raw_api_key` → `ddorg_<env>_<secret>` with
env `liv|tst`, secret = `secrets.token_urlsafe(43)`; `hash_api_key` =
HMAC-SHA256; `prefix_for_raw_key` = first 12 chars); `OrganizationApiKey` model
+ migration `0009` (`organization_api_keys`, unique `key_hash` index, FK org
CASCADE + account SET NULL, `permissions` JSON); `ApiKeyCreate` /
`ApiKeyResponse` / `ApiKeyCreateResponse` (`raw_key` only on create/rotate);
`OrganizationRepository` api-key queries (all org-scoped) + `find_api_key_by_hash`;
new `OrganizationApiKeyService` (`create_api_key`/`revoke_api_key`/
`rotate_api_key`/`find_by_hash`) + `OrganizationApiKeyServiceDep`; audit
`API_KEY_CREATED`/`API_KEY_REVOKED` (rotate = revoke old + create new); 4 routes
(`GET/POST /me/api-keys`, `DELETE /me/api-keys/{id}` → 204,
`POST /me/api-keys/{id}/rotate`); 404 mapping; config tests updated for the new
key setting.

**Verification.** 23 new tests (14 unit + 9 API) + full account-api suite
**305 pass**; `uvx ruff check apps/account-api` clean. Details in the
Implementation Status block below.

#### Phase 4 Implementation Status

- Files created: `app/domain/api_key.py`,
  `app/services/organization_api_key.py`,
  `migrations/alembic/versions/0009_organization_api_keys.py`.
- Files modified: `app/core/config.py` (+ hmac key + prefix + `_KEY_SETTINGS`
  entry), `app/domain/organization.py` (api-key error), `app/domain/access.py`
  (api-key audit actions), `app/models/organization.py`, `app/models/__init__.py`,
  `app/schemas/organization.py`, `app/repositories/organization.py`,
  `app/dependencies/organization.py` (service dep), `app/api/v1/organizations.py`,
  `app/api/v1/http_errors.py`, `tests/unit/test_config.py`,
  `tests/test_organizations_api.py`, `tests/unit/test_organization.py`.
- New tests: 14 unit (create → hash-only storage + prefix, find_by_hash,
  list, org-scoping, revoke + idempotent re-revoke, rotate = new ACTIVE + old
  REVOKED, audit, migration 0009 round-trip incl. unique `key_hash`) + 9 API
  (auth/admin gates, create raw-once + list hides raw, scopes 422, org-scoped
  list, revoke 204 + cross-org 404, rotate 200 + cross-org 404).
- Full account-api suite **305 pass** (was 282); `uvx ruff check
  apps/account-api` clean.
- Raw key is never persisted or logged; `key_hash` =
  HMAC-SHA256(`integration_api_hmac_key`, raw) hex. Empty dev default is fine
  (warning in dev); production refuses to start (§7).
- `revoke_api_key` is idempotent (already-revoked → no-op, 204). Rotate keeps
  `name`/`permissions`/`expires_at`, issues a fresh raw key, ups `revoked_at`
  on the old.
- `integration_api_hmac_key` joined `_KEY_SETTINGS`; config unit tests updated
  (`VALID_SECRETS` + `SENSITIVE_ENV_VARS`).

---

## 3. Pending phases

Vertical slices; migration numbers from §4.4. Each phase ends with tests +
`docs` status update + a pause to confirm with the user.

### Phase 4a — Organization onboarding (admin) [x]

**Objective.** A `system_admin` provisions organizations and connects a
representative by email. **No public self-registration** (`POST /organizations`)
— the user NEVER creates/claims an organization on their own (see
`docs/development/ORGS/OAI_ONBOARD_IMPL_PLAN.md` §1/§4). Representative
authorization is the `OrganizationMembership.role`; no global
`organization_admin` `AccountRole` is granted.

**Endpoints** (`/api/v1/admin/organizations`, gate: `system_admin`):
- `POST /admin/organizations` → 201 `OrganizationResponse`. Body =
  `{organization: OrganizationCreate, administrator: OrganizationMemberCreate}`.
  One transaction: create `Organization` (ACTIVE, verification PENDING,
  `created_by_account_id` = admin actor) + resolve/create `Account` by email +
  `OrganizationMembership(role=administrator.role, status=ACTIVE)`.
- `POST /admin/organizations/{organization_id}/members` → 201
  `OrganizationMemberResponse` (attach to an existing org; 404 if missing /
  organization not ACTIVE).
- `GET /admin/organizations` → `list[OrganizationResponse]` (all orgs).
- `GET /admin/organizations/{organization_id}` → `OrganizationResponse` (404
  when absent).
- `GET /admin/organizations/{organization_id}/members` →
  `list[OrganizationMemberResponse]`.

**Account resolution.** Normalize email → reuse an existing account if present;
only create a new `Account(status=PENDING, email_normalized UNIQUE)` when there is
no match. Never create a second account for the same email. The representative
finishes registration via the existing OTP flow. No global role is granted.

**Schema.** `OrganizationCreate` — required `name`, `type`, `inn`, `ogrn`;
optional `legal_address`, `email`, `phone`, `website`; INN/OGRN validators are
**shared** with `OrganizationUpdate` (`app/schemas/organization.py`), normalize
to canonical digits (inner whitespace stripped) and checksum-check behind
`integration_validate_inn_checksum`. `OrganizationMemberCreate` — `email`
(Identity-normalized), `role: OrganizationMembershipRole` (default `owner`).
`OrganizationMemberResponse` — membership row (`organization_id`, `account_id`,
`role`, `status`, `joined_at`).

**Service.** `OrganizationService.admin_create_organization(actor, payload,
request)` / `admin_attach_membership(actor, organization_id, payload, request)`:
1. UX pre-check: duplicate `inn`/`ogrn` → 409 (`OrganizationLegalDataConflictError`);
   duplicate `(organization_id, account_id)` membership → 409 on attach.
2. One transaction: org + membership + account (create-only-if-absent) + commit
   + audits `ORGANIZATION_CREATED` + `ORGANIZATION_ADMIN_ADDED`.
3. **Idempotency source of truth = DB unique indexes** `uq_organizations_inn` /
   `uq_organizations_ogrn` (from `0006`) and `uq_organization_memberships_org_account`;
   `IntegrityError` → rollback → 409.
4. Multi-membership safety: `get_active_organization_for_account` is
   deterministic (earliest `joined_at`) + new
   `list_active_organizations_for_account` (no `MultipleResultsFound` on a 2nd
   membership) — hardening for org-context reads (4b consumes them).

**Migration** `0010_organization_onboarding.py` — `organizations.created_by_account_id`
(Uuid FK `accounts.id` ondelete `SET NULL`, index) + `organization_memberships.role`
String(16) `OrganizationMembershipRole` (`owner|admin|member`), server default
`'MEMBER'` (uppercase), existing rows default `member`. Downgrade drops both.

**Boundaries.** `Organization.email`/`phone` are contact data — never derived from
the account identity. Audit metadata carries no legal data, contacts, secrets or
emails. Representative notification is **recorded** at onboarding (audit); the
delivery/email lands in Phase 4f (notifications). `/organizations/me/*` resource
authorization migrates from the legacy global `organization_admin` `AccountRole`
check to `OrganizationMembership.role` in 4b — onboarding itself grants no global
role. API-key policies stay 4c.

**Accept.** system_admin-only (non-admin → 403); org + OWNER membership created
in one transaction; account reused (not duplicated) on email match; INN/OGRN
duplicate → 409 via both pre-check and unique-index paths; attach to existing
org; audit `ORGANIZATION_CREATED` + `ORGANIZATION_ADMIN_ADDED` with no sensitive
metadata; a non-system-admin account can never create/claim an org.

#### Phase 4a Implementation Status

- `app/domain/organization.py` — `OrganizationMembershipRole` (`owner|admin|member`),
  `OrganizationMembershipNotFoundError` (reserved), `OrganizationMembershipConflictError`
  (duplicate same-pair membership / org not ACTIVE). `app/domain/access.py` —
  `ORGANIZATION_CREATED` + `ORGANIZATION_ADMIN_ADDED`.
- `models/organization.py` — `organizations.created_by_account_id` (FK accounts
  SET NULL, ix) + `organization_memberships.role`
  (`native_enum=False` → uppercase member name; `server_default='MEMBER'`).
- Migration `0010_organization_onboarding.py` — batch-mode FK add on
  `organizations` (named `fk_organizations_created_by_account_id_accounts`;
  SQLite requires batch + named FK) + plain `role` add on memberships; round-trip
  tested (upgrade → columns/indexes + `MEMBER`/`OWNER` values, downgrade → clean).
- Schemas (`app/schemas/organization.py`) — `OrganizationCreate` (required
  name/type/inn/ogrn), `OrganizationMemberCreate` (Identity-normalized email,
  role default `owner`), `OrganizationAdminCreate`, `OrganizationMemberResponse`;
  INN/OGRN validators factored into shared `normalize_inn_digits` /
  `normalize_ogrn_digits` reused by `OrganizationUpdate`.
- Service (`app/services/organization.py`) — `admin_create_organization` (org +
  owner membership + account resolve-or-create in ONE transaction, commits, then
  `ORGANIZATION_CREATED` + `ORGANIZATION_ADMIN_ADDED` audits; `IntegrityError`
  → rollback → 409) and `admin_attach_membership` (404 missing org / 409 not
  ACTIVE / 409 same-pair duplicate via pre-check + unique index). No global role
  is ever granted.
- Repo (`app/repositories/organization.py`) — `list_organizations`,
  `list_memberships`, `get_membership`, `get_active_organization_for_account`
  deterministic (earliest `joined_at`, id tie-break, `scalars().first()`),
  `list_active_organizations_for_account`.
- Router `app/api/v1/admin_organizations.py` (`/api/v1/admin/organizations`,
  gate `require_roles(RoleCode.SYSTEM_ADMIN)`): POST /, GET /, GET /{id},
  POST /{id}/members, GET /{id}/members; registered in `app/api/v1/__init__.py`;
  401/403/404/409 mapped via `raise_for` (+ `OrganizationMembershipConflictError`
  → 409 in `http_errors.py`).
- Tests: `tests/test_organizations_admin_api.py` (new; 401/403 gate, 201 create
  with OWNER membership + PENDING rep account + NO global role, account reuse,
  409 dup INN/OGRN, 409 dup pair, 404 missing / 409 inactive org, cross-org
  multi-membership, audit rows) + `tests/unit/test_organization.py` (service
  unit tests, deterministic resolution, migration 0010 round-trip). Full suite
  **335 passed**; `ruff check` clean (app + new migration; pre-existing
  findings in `0003`/`0005` untouched).

### Phase 4b — Organization context & membership-role authorization [x]

**Objective.** Replace the global `organization_admin` `AccountRole` as the
org-authorization source for `/organizations/me/*` with a check on
`OrganizationMembership.role ∈ {owner, admin}`.

**Changes.** Refactor `require_organization_admin()` / `_resolve_organization_admin_membership`
in `app/dependencies/organization.py` to authorize via the resolved membership
role; explicit current-org selection for multi-membership accounts (no implicit
"first membership" on write endpoints); drop the legacy global `organization_admin`
`AccountRole` check (onboarding never granted it); every sub-resource stays
org-scoped (no IDOR). Tests:
multi-org account manages each org without ambiguity, role downgrade `owner→member`
loses access, isolation kept. Deps: 4a. **Accept:** org management works without
any global `organization_admin` role; ambiguous multi-org access is resolved
explicitly.

#### Phase 4b Implementation Status

- Deps (`app/dependencies/organization.py`) — new `OrganizationContext`
  dataclass (account + organization + ACTIVE membership); `get_my_organization`
  (management current-org: ACTIVE membership + `owner|admin`, `member` → 403
  "insufficient organization membership role"); explicit current-org selection:
  single ACTIVE membership implicit, several → `X-Organization-Id` header
  (missing/ambiguous → 400, unknown → 404). `get_my_organizations` (list);
  `get_scoped_organization` (any member, foreign/unknown → 404);
  `get_scoped_organization_manager` (`owner|admin` for member-reads). The legacy
  global `organization_admin` `AccountRole` check is **dropped** — onboarding
  never granted it; `OrganizationAdmin` keeps its name but now resolves the
  membership role.
- Repo (`app/repositories/organization.py`) — `get_active_membership` (ACTIVE
  filter) + `list_active_memberships_for_account` (org-context base). Service —
  `list_organizations_for_account` (`GET /organizations`).
- Router (`app/api/v1/organizations.py`) — new `GET /organizations` (my orgs),
  `GET /organizations/{id}` (my org read, 404 foreign), `GET
  /organizations/{id}/members` (my org's members, `owner|admin` gate). `/me/*`
  unchanged in shape — still resolved current-org, now role-gated by
  membership instead of the global role.
- Tests: `tests/test_organizations_context_api.py` (new; list-my-orgs, no
  membership 403, scoped get 200/404, member reads-context-not-manages,
  owner lists members, foreign members 404, ambiguous 400 → explicit header
  200, unknown header 404, write endpoint explicit-org scoping, single
  membership implicit, owner→member downgrade closes manage but keeps read)
  + `tests/unit/test_organization.py` (service lists ACTIVE-only, repo
  `get_active_membership` ACTIVE/LEFT, `list_active_memberships_for_account`).
  Existing `/me/*` tests updated: memberships now carry `role=OWNER`, no global
  role seeded. Full suite **347 passed** (was 335); `ruff check` clean.

### Phase 4c — API-key auth & verification policy [x]

Deps module + `OrganizationApiContext`, scopes, Redis rate limit,
`OrganizationApiRequest` writes (`0011`), `request_id` (echoed `X-Request-Id`).
**Verification gate** (locked): integration additionally requires
`verification_status ≠ REJECTED`; `Organization.status = ACTIVE` is
necessary-not-sufficient — PENDING verification never grants unrestricted
production access. Tests: 401/403/429 matrix + unverified/rejected org. Deps: 4b.
**Accept:** a key authenticates, is org-scoped, rate-limited, verification-gated
and audited.

**Phase 4c Implementation Status** (Revision 9, `[x]`):
- `app/dependencies/integration.py` — `OrganizationApiContext`,
  `get_current_organization_from_api_key`, `require_api_key_permission`,
  `ApiKeyRateLimiterDep`; `GET /integration` single endpoint `POST
  /integration/documents` stub (501) registers in `app/api/v1/integration.py`.
- `app/services/rate_limit.py` — per-key minute window on `redis_client`
  (config `integration_rate_limit_per_minute=120`, overridable in tests).
- `app/models/organization.py` + `migrations/.../0011_organization_api_requests.py`
  — `organization_api_requests` (non-PII; org/api_key NULLable for failed auth).
- `app/middleware/request_logging.py` — `X-Request-Id` echo + best-effort
  `OrganizationApiRequest` writes via `request.app.state.api_request_db_factory`.
- `app/core/config.py` — `integration_rate_limit_per_minute`,
  `integration_request_log_sample`; HTTP error mappings for 401/403 (4c).
- Tests: `tests/test_organizations_integration_api.py` (401 no/missing/
  unknown/revoked/expired, 403 inactive/rejected/missing-scope, pre-seeded 429,
  happy 501 + request logged with echoed id + failed-auth recorded, audit,
  `last_used_at`); `tests/unit/test_organization.py` (migration 0011
  round-trip, `ApiKeyRateLimiter` window/ttl/isolation). Full suite **367
  passed**; `ruff` clean.

### Phase 4d — Integration API & patient resolver [x]

`OrganizationPatientResolver` (§4.9) + `POST /integration/documents`,
`GET /integration/documents/{id}`; extend `DocumentService` (`0012` document
columns incl. `organization_id`/`organization_branch_id`/`external_id`/
`idempotency_key`/`provided_document_type`); event `OrganizationDocumentSubmitted`.
Tests: upload → status, doc-type conflict (422), `external_id` idempotency,
MIME/size, resolver race recovery. Deps: 4c + resolver. **Accept:** org uploads a
doc end-to-end through the existing pipeline.

**Phase 4d Implementation Status** (Revision 10, `[x]`):
- Migration `0012_organization_document_source.py` — documents `organization_id`
  / `organization_branch_id` / `external_id` / `idempotency_key` /
  `provided_document_type` + partial unique indexes
  (`uq_documents_organization_external_id`, `uq_documents_organization_idempotency_key`;
  `WHERE organization_id IS NOT NULL`).
- `app/models/document.py` + `app/repositories/document.py` — source columns,
  `get_organization_document`, `find_by_organization_external_id`,
  `find_by_organization_idempotency_key`.
- `app/services/patient_resolver.py` — `OrganizationPatientResolver.resolve_by_email`
  (email-only identity; `get_or_create_by_identity` → PENDING account default;
  IntegrityError→rollback→reload race recovery); `ResolvedPatient` dataclass.
- `app/services/organization_document.py` — `OrganizationDocumentService`
  (idempotency by `external_id` then `Idempotency-Key`, branch resolution,
  org-event best-effort publish, `INTEGRATION_DOCUMENT_UPLOADED` audit);
  `OrganizationDocumentSubmitResult(document, patient_id, replayed)`.
- `app/services/documents.py` — `DocumentService.create_organization_document`
  (skip quota, `uploaded_by_account_id=None`, status PENDING, pipeline event,
  single commit) + `publish_organization_submitted`.
- `app/schemas/integration.py` — `IntegrationDocumentSubmit` (email-only
  patient_email, `DocumentType` default OTHER), `IntegrationDocumentResponse`
  (literal `"processing"`), `IntegrationDocumentStatusResponse`.
- `app/api/v1/integration.py` — real `POST /integration/documents` (201 new /
  200 replay, explicit `Form()` fields + `UploadFile` because model-in-Form
  conflicts with UploadFile in FastAPI 0.141) and `GET …/{document_id}`
  (org-scoped read); `raise_for` maps `InvalidPatientIdentityError` (422),
  `OrganizationBranchNotFoundError` (404), `OrganizationDocumentIdempotencyConflictError`
  (409), `FileTooLargeError` (413), `UnsupportedFileTypeError` (415).
- `packages/contracts/contracts/events/organization_document_submitted.py` —
  `OrganizationDocumentSubmitted` (pydantic `BaseModel`; routing key passed at
  publish time); exported; 2 round-trip tests.
- `app/dependencies/integration.py` — `OrganizationDocumentServiceDep`
  (composes `Depends(get_document_service)`).
- Tests: `tests/unit/test_patient_resolver.py` (8 cases incl. race monkeypatch);
  `tests/unit/test_integration_documents.py` (11: source columns, quota skip,
  pipeline event, submit+audit+event, replays, conflict, branches, phone reject,
  org-scoped GET); `tests/test_integration_documents_api.py` (201 shape,
  `X-Request-Id`, 422 doc-type/phone/missing-email, 415 MIME, 413 oversized,
  404 branch, idempotent replay, GET scoping, same-email dedup);
  `tests/test_organizations_integration_api.py` (4c happy-path upgraded from 501
  stub to real 201). Migration round-trips in `tests/unit/test_organization.py`.
  Full suite **402 passed**; `ruff` clean.

### Phase 4e — Bulk upload [x]

DB `0013`; `OrganizationBulkUploadService`; API `POST /integration/documents/bulk`,
`GET /integration/batches/{id}(/items)`; batch events; per-item **own**
transactions; partial failures; idempotency `(org, external_id)`. Tests: batch
state machine, per-item failures, duplicates, no giant transaction. Deps: 4d.
**Accept:** 100-doc batch, partial failures tracked per item, resubmission
idempotent.

**Phase 4e Implementation Status** (Revision 11, `[x]`):
- Migration `0013_organization_upload_batches.py` — `organization_upload_batches`
  (header: `organization_id`, `api_key_id`, `idempotency_key`, `status` ACCEPTED,
  counters, `created_at`/`completed_at`) + `organization_upload_batch_items`
  (per-item metadata + outcome: `patient_email`, `document_type`, `external_id`,
  `branch_code`, `title`, `status`, `error_code`/`error_message`); partial unique
  index `uq_organization_upload_batches_org_idem` (`idempotency_key IS NOT NULL`)
  + unique `uq_organization_upload_batch_items_batch_index`; CASCADE/SET NULL
  FKs, downgrade-safe; wiring + round-trip verified.
- `app/models/organization.py` — `OrganizationUploadBatch` +
  `OrganizationUploadBatchItem` (UUID PKs, enums as VARCHAR
  `native_enum=False`, `items` selectin relationship ordered by `item_index`).
- `app/domain/organization.py` — `OrganizationBatchNotFoundError` (404),
  `OrganizationBatchSizeLimitExceededError` (422 against
  `integration_max_batch_size`), `OrganizationBatchConflictError` (reserved 409).
- `app/repositories/organization.py` — `find_batch_by_idempotency_key`,
  `get_batch` (org-scoped items read with `populate_existing` so a cached
  identity-map header never shadows the finalize commit in the POST response),
  `list_batch_items` (ordered by `item_index`).
- `app/services/organization_bulk_upload.py` — `OrganizationBulkUploadService`
  (`submit_batch`/`create_batch`/`get_batch`/`get_batch_items`); per-item
  sessions from `request.app.state.api_request_db_factory` (fallback
  `async_session_factory`); per-item error codes
  `duplicate_external_id | patient_resolution_failed | branch_not_found |
  file_too_large | unsupported_file_type | internal_error` (message ≤ 512);
  `_finalize` → `COMPLETED|PARTIAL|FAILED` + `OrganizationBatchCompleted`.
- `app/api/v1/integration.py` — real `POST /integration/documents/bulk` (202 new
  / 200 replay by `Idempotency-Key`; `metadata` JSON array `Form` + `files:
  list[UploadFile]`; len(files) ≠ len(items) → 422, malformed JSON → 422, over
  `integration_max_batch_size` → 422) and `GET /integration/batches/{id}` +
  `…/items` (read scope, cross-org → 404); `raise_for` maps batch 404/422.
- `app/dependencies/integration.py` — `get_organization_bulk_upload_service` +
  `OrganizationBulkUploadServiceDep` (composes `Depends(get_db)`, `await
  get_publisher()`, `StorageService.from_settings()`).
- `app/schemas/integration.py` — `BulkUploadItemMetadata` (mirrors
  `IntegrationDocumentSubmit`), `BulkUploadRequest` (`items` ≥1), bulk response
  schemas; `app/core/config.py` — `integration_max_batch_size` (default 100);
  `AuditAction.INTEGRATION_BATCH_CREATED`.
- `packages/contracts/contracts/events/organization_batch_created.py` +
  `organization_batch_completed.py` — `OrganizationBatchCreated` /
  `OrganizationBatchCompleted` (routing keys `organization.batch.created` /
  `organization.batch.completed`; per-item `organization.document.submitted`
  reuses `OrganizationDocumentSubmitted`); exported + 2 round-trip tests.
- Tests: `tests/unit/test_bulk_upload.py` (10: create header/items, over-limit,
  all-accept COMPLETED + events, idempotent replay without re-processing,
  partial failure, dup `external_id`, unknown branch FAILED, org-scoped reads,
  migration 0013 wiring + round-trip);
  `tests/test_bulk_upload_api.py` (14: 202 shape + side effects, `X-Request-Id`,
  replay → 200, scope 403, auth, count-mismatch / bad-JSON / empty / over-limit
  422, partial failure items, GET batch + items 200, cross-org 404,
  `document_type` round-trip). Account-api suite **426 passed**; `ruff` clean.

### Phase 4f — Notifications [ ]

DB `notifications` (in `0015`); `NotificationService`; extend `notification-worker`
(provider `send_message`, consume `notification.requested`); hook after analysis
completed/failed for org-sourced docs. Tests: row created, email has no medical
data, worker delivery. Deps: 4d. **Accept:** client receives "document
processed/failed" email with org name + secure link, no medical data.

### Phase 4g — Organization schemas [ ]

DB `0014`; `OrganizationSchemaService`; API schemas CRUD + publish (immutable).
Tests: versioning, publish-immutability, JSON-Schema validation. Deps: 4b.
**Accept:** org drafts/publishes versioned schemas without touching the canonical
model.

### Phase 4h — Monitoring [ ]

`GET /organizations/me/api-usage` aggregates; `OrganizationApiRequest` volume;
metrics/log notes; retention purge (§7 open decision 7). Tests: aggregation
filters by org, no PII columns. Deps: 4c. **Accept:** org sees requests/day,
success/error, docs, batches, failures.

### Phase 4i — Registry verification + ownership/invite [ ]

Add `OrganizationRegistryProvider` `Protocol` + `OrganizationVerificationResult`;
**no** provider implementation; `Organization.created_by_account_id` as the
ownership anchor for future invite/claim flows (join existing org by INN).
Deps: 4b. **Accept:** a future `FederalRegistryProvider` injects without changing
`OrganizationService`; ownership/membership remain separate concepts.

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
first-12 mod 11 mod 10). Phase 4a additionally normalizes away **inner**
whitespace so only canonical digits persist.

`OrganizationMembershipRole` (Phase 4a): `owner|admin|member` — the
**organization-scoped** role (column on `organization_memberships`). Owner = the
first representative a system admin connected for the org. Authorization for
`/organizations/me/*` uses this column since 4b (`owner|admin` manage; the
legacy global `organization_admin` `AccountRole` check is dropped — onboarding
grants **no** global role).

`AuditAction` additions (each in its phase): `ORGANIZATION_UPDATED` ✓ (Ph1),
`ORGANIZATION_BRANCH_CREATED` / `_UPDATED` / `_DEACTIVATED` ✓ (Ph2),
`ORGANIZATION_LICENSE_CREATED` / `_UPDATED` / `_DEACTIVATED` ✓ (Ph3),
`API_KEY_CREATED` / `_REVOKED` ✓ (Ph4),
`ORGANIZATION_CREATED` + `ORGANIZATION_ADMIN_ADDED` (4a — actor/org/request only;
metadata `{account_id, role}`; no legal data/contacts/emails),
`API_KEY_AUTH_FAILED`, `INTEGRATION_DOCUMENT_UPLOADED`,
`INTEGRATION_BATCH_CREATED` (string values → fits `length=64`).

Config additions: `integration_api_hmac_key` (empty default; goes in
`_KEY_SETTINGS`, min 32 — production guard) ✓ (Ph4), `integration_api_key_prefix =
"ddorg"` ✓ (Ph4), `integration_rate_limit_per_minute = 120`,
`integration_max_batch_size = 100`, `integration_validate_inn_checksum = True`
✓ (Ph1), `integration_request_log_sample = 1.0`.

### 4.3 Database schema

Conventions: `Uuid` PK `default=uuid4`, `DateTime(timezone=True)` UTC via
`utcnow()`, enums `native_enum=False`, names via `Base.metadata` convention.
All new columns nullable for existing rows (never force NOT NULL on prod data).

| Table | Key columns / constraints |
|---|---|
| `organizations` (modified) | + `inn` String(12) unique · `ogrn` String(13) unique · `legal_address` Text · `email` · `phone` · `website` · `verification_status` (default `UNVERIFIED`) · `created_by_account_id` FK accounts.id SET NULL ix (4a) |
| `organization_memberships` | `organization_id` FK CASCADE · `account_id` FK CASCADE · `role` `OrganizationMembershipRole` (default `member`) (4a) · `position` · `status` · `joined_at`/`left_at` · `UniqueConstraint(organization_id, account_id, name="uq_organization_memberships_org_account")` |
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

### 4.4 Migrations (10 on top of `0005`; each downgrade-safe, independently reviewable)

| Migration | Contents |
|---|---|
| `0006_organization_legal_data.py` ✓ | org legal columns + `verification_status` (server default `'UNVERIFIED'`) + `uq_organizations_inn`/`_ogrn` |
| `0007_organization_branches.py` ✓ | `organization_branches` + `(organization_id, code)` unique index (see note §7) |
| `0008_organization_licenses.py` ✓ | `organization_licenses` + `(organization_id, license_number)` unique index (see note §7) |
| `0009_organization_api_keys.py` ✓ | `organization_api_keys` + unique `key_hash` index (see note §7) |
| `0010_organization_onboarding.py` ✓ | `organizations.created_by_account_id` (FK SET NULL, ix) + `organization_memberships.role` (server default `'MEMBER'`) |
| `0011_organization_api_requests.py` ✓ | `organization_api_requests` + indexes |
| `0012_organization_document_source.py` ✓ | `documents` source columns + partial unique indexes (org-scoped `external_id`/`idempotency_key`) |
| `0013_organization_upload_batches.py` | batches + items (drop items first on downgrade) |
| `0014_organization_document_schemas.py` | `organization_document_schemas` |
| `0015_notifications.py` | `notifications` |

### 4.5 API-key architecture

- **Format:** `ddorg_<env>_<secret>`, env ∈ `liv|tst`, secret = `secrets.token_urlsafe(43)` (256-bit). `prefix` = first 12 chars for display. ✓ (Ph4, `app/domain/api_key.py`)
- **Hashing:** `HMAC_sha256(settings.integration_api_hmac_key, raw_key)` hex; only `key_hash` persisted — raw key never stored/logged (kept as `Authorization: Bearer <key>`). ✓
- **Creation:** `create(org, name, scopes, expires_at?, created_by)` → `(record, raw_key)`; raw shown **once** (create/rotate responses). `last_used_at` updated best-effort in the auth dependency (Ph5). ✓
- **Status:** `active|revoked|expired`; inactive org ⇒ key unusable regardless. ✓ (Ph5 for the auth wiring)
- **Revoke/rotate:** revoke is idempotent → 204; rotate issues a new ACTIVE key keeping name/scopes/expiry, old goes `REVOKED` with `revoked_at` set. ✓

### 4.6 Authentication & authorization

- Onboarding (`/api/v1/admin/organizations`, 4a): JWT `get_current_account` →
  `require_roles(RoleCode.SYSTEM_ADMIN)` → 403 `"insufficient roles"` otherwise.
  Representative authorization = `OrganizationMembership.role` (`owner` default);
  the global `organization_admin` `AccountRole` is **never** granted by onboarding.
- Management (`/organizations/me/*`): JWT `get_current_account` →
  `get_my_organization` (ACTIVE membership) → 403
  `"no active organization membership"` / `"insufficient organization role"`.
  Authorized by the resolved `OrganizationMembership.role ∈ {owner, admin}`
  (4b — the legacy global `ORGANIZATION_ADMIN` `AccountRole` check is dropped;
  onboarding never granted it). Multi-membership: current-org selection is
  **explicit** — a single ACTIVE membership is implicit; several require
  `X-Organization-Id` (ambiguous → 400 `"ambiguous organization context"`,
  unknown → 404). Every sub-resource scoped by `organization.id` (no IDOR).
  Context reads (4b): `GET /organizations` (all my orgs),
  `GET /organizations/{id}` (my org, foreign → 404),
  `GET /organizations/{id}/members` (`owner|admin`).
- Integration (`/integration/*`): `Bearer` → hash → `find_by_hash` → 401
  (none/revoked/expired) → org status ≠ ACTIVE → 403 → **verification gate**:
  `verification_status = REJECTED` → 403 (4c) → `OrganizationApiContext(
  organization, api_key, permissions)`. Per-endpoint scope
  `require_api_key_permission(scope)`; Redis sliding-window rate limit
  `rl:{api_key_id}:{minute}` vs `integration_rate_limit_per_minute` → 429.

### 4.7 Endpoints

Management (JWT + member; role = `OrganizationMembership.role`, `owner|admin`
manage, `member` reads context only — 4b):

| Method/Path | Request → Response | Notes |
|---|---|---|
| `POST /admin/organizations` · `GET /admin/organizations` · `POST/GET /admin/organizations/{id}/members` · `GET /admin/organizations/{id}` | `OrganizationAdminCreate` → `OrganizationResponse` 201 · list · attach/list members · get | **4a (next)**; `system_admin` gate; membership role (no global role); **no public `POST /organizations`** |
| `GET /organizations` · `GET /organizations/{id}` · `GET /organizations/{id}/members` | list my orgs · org context reads | **✓ 4b**; membership-role protected (members read context; members list owner|admin) |
| `GET/PATCH /organizations/me` ✓ | — / `OrganizationUpdate` → `OrganizationResponse` | Ph1 |
| `GET/POST /organizations/me/branches` · `PATCH/DELETE /…/{id}` | `BranchCreate/Update` → `BranchResponse` · 204 | ✓ Ph2; dup code 409; DELETE = soft deactivate |
| `GET/POST /organizations/me/licenses` · `PATCH/DELETE /…/{id}` | `LicenseCreate/Update` → `LicenseResponse` · 204 | ✓ Ph3; dup number 409; DELETE = soft revoke; auto `EXPIRED` on list/get |
| `GET/POST /organizations/me/api-keys` · `DELETE/Rotate /…/{id}` | `ApiKeyCreate` → response (**raw once**) · 204 · `POST …/{id}/rotate` | ✓ Ph4; list hides raw; rotate returns new raw key |
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

- `OrganizationCreate` **4a (admin)** — required `name`, `type`, `inn`, `ogrn`; optional `legal_address`, `email`, `phone`, `website`; shared INN/OGRN validators (canonical digits, checksum). `OrganizationMemberCreate` **4a** — `email` (Identity-normalized) + `role` (`OrganizationMembershipRole`, default `owner`); `OrganizationMemberResponse` **4a** — membership row. `OrganizationUpdate` ✓ — optional name/inn/ogrn/legal_address/email/phone/website; INN/OGRN normalized + checksum-checked; legal-data change → `PENDING` (re-verification).
- Branch ✓: `code ^[A-Za-z0-9_-]{1,32}$`, `name ≤255`, `address`, `phone`; PATCH `""` → `NULL`.
- License ✓: `license_number ≤64`, `license_type`, `status`, `issued_at`, `expires_at`, `scope`, `issuer`; `expires_at` must not precede `issued_at`; PATCH `""` clears `scope`/`issuer`; explicit `status` change allowed.
- ApiKey ✓: `name ≤128`, `scopes` (required, non-empty list of the 4 scopes), `expires_at?`; `ApiKeyResponse` hides `key_hash`; `raw_key` present only on `ApiKeyCreateResponse` (create/rotate).
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

### 4.15 Organization onboarding & access policy (4a)

- **Flow (admin):** `system_admin` → `POST /admin/organizations` →
  `Organization` (ACTIVE, verification PENDING, `created_by_account_id` = admin
  actor) + `OrganizationMembership` (ACTIVE, role `owner` default or `admin`)
  for the representative, in **one transaction** (account resolved/created
  within it). No global `organization_admin` `AccountRole` is granted —
  representative authorization is the membership role.
- **No public self-registration:** a regular ACTIVE account cannot
  `POST /organizations`; organization creation/attachment is exclusively
  system-admin onboarding.
- **Account resolution:** normalize email → reuse existing `Account` (no
  duplicates — `email_normalized` UNIQUE); only create a new **PENDING** account
  when there is no match. The representative completes registration via the
  existing OTP flow. Never a second account for the same email.
- **Multi-membership:** one account may hold ACTIVE memberships in N orgs; attach
  across orgs is allowed. A second membership for the **same** `(organization_id,
  account_id)` → 409 (unique constraint `uq_organization_memberships_org_account`).
- **Idempotency:** `uq_organizations_inn` / `uq_organizations_ogrn` are the
  source of truth; service pre-check only improves UX. `IntegrityError` is
  caught, rolled back and mapped to 409.
- **Status vs. verification (locked):** `Organization.status = ACTIVE` is
  *necessary but not sufficient* for integration access. Integration (4c+)
  requires `verification_status ≠ REJECTED` + ACTIVE membership role
  (`owner|admin`) + key scope. PENDING verification never implies unrestricted
  production access. `GET/POST /organizations/me/api-keys` and management
  endpoints are **not** gated by verification (management ≠ production data
  access).
- **Identities are separate:** `Account.email`/`phone` are authentication
  identity; `Organization.email`/`phone` are contact data — never derived from
  the representative's identity.
- **Ownership vs. membership:** `created_by_account_id` records the creating
  system-admin (for investigation/support/verification/invite); ownership
  (membership role) and membership remain separate concepts (4i reuses the
  creator anchor for invite/claim by INN).
- **Audit:** `ORGANIZATION_CREATED` + `ORGANIZATION_ADMIN_ADDED` =
  actor_account_id + organization + request (IP/UA via `AuditService.record`);
  metadata = `{account_id, role}` only — never legal data, contact fields,
  secrets or emails.

---

## 5. Tests

- **Unit** (`tests/unit/`): `test_inn_ogrn.py` ✓ (checksums), `test_organization.py` ✓ (service + 0006–0009 round-trips + api-key hash/rotate; + 4a admin onboarding: org+OWNER membership in one transaction, account reuse (no dup), duplicate INN/OGRN → 409 pre-check and `IntegrityError`→409, audit actions, migration 0010 round-trip; + 4c migration 0011 round-trip + `ApiKeyRateLimiter` window/TTL/isolation; + 4d migration 0012 round-trip), `test_config.py` ✓ (integration secrets), `test_api_key.py`, `test_patient_resolver.py` ✓ (8 resolver cases incl. race recovery), `test_integration_documents.py` ✓ (11: source columns, quota skip, pipeline event, submit+audit+event, replays, branches, phone reject, org-scoped GET), `test_bulk_upload.py`, `test_schema.py`.
- **API**: `tests/test_organizations_api.py` ✓ (existing `/me/*` gates, now membership-role); new `tests/test_organizations_admin_api.py` **4a** (401, 403 non-system-admin gate, 201 create-with-owner, email/account reuse, 409 dup INN/OGRN, 409 same-(org,account) membership, 404 missing/inactive org, multi-org attach, audit rows, no global role granted); new `tests/test_organizations_context_api.py` **4b** (list my orgs + no-membership 403, scoped get 200/foreign 404, member reads-context-not-manages, owner lists members, ambiguity 400 → explicit `X-Organization-Id` 200 / unknown 404, write endpoint explicit-org scoping, owner→member downgrade loses manage, implicit current-org for single membership); new `tests/test_organizations_integration_api.py` **4c** (401 no/missing/unknown/revoked/expired key, 403 org-inactive / verification-REJECTED / missing scope, pre-seeded 429 window, happy 201 + `X-Request-Id` echo + `organization_api_requests` row on success and failed auth, `API_KEY_AUTH_FAILED` audit, `last_used_at`, key org-scoping); new `tests/test_integration_documents_api.py` **4d** (201 shape + audit/account/patient side effects, `X-Request-Id` echo, 422 invalid doc-type/phone/missing email, 415 MIME mismatch, 413 oversized, 404 unknown branch, 409 conflicting keys, idempotent replay by `external_id` and `Idempotency-Key` (201→200), GET org-scoped status 200/403/404, same-email dedup); `tests/test_integration_api.py`.
- **Security**: cross-org 404, revoked/expired 401, inactive org 403, missing scope 403, no duplicate docs on retry (concurrency via `ASGITransport`).
- **Run**: `uv run --project apps/account-api pytest apps/account-api` + `uvx ruff check apps packages tests`. S3/RabbitMQ-leg tests live in root `tests/integration` (marked `integration`).

---

## 6. Implementation order

1. Phase 1 — Organization core. [x]
2. Phase 2 — Branches. [x]
3. Phase 3 — Licenses. [x]
4. Phase 4 — API keys. [x]
5. Phase 4a — Organization onboarding (admin). [x] (done)
6. Phase 4b — Organization context & membership-role authorization. [x] (done)
7. Phase 4c — API-key auth & verification policy. [x] (done)
8. Phase 4d — Integration API + patient resolver. [x] (done)
9. Phase 4e — Bulk upload. [x] (done)
10. Phase 4f — Notifications. [ ]
11. Phase 4g — Organization schemas. [ ]
12. Phase 4h — Monitoring. [ ]
13. Phase 4i — Registry verification + ownership/invite. [ ]

Each phase: implement → update this status → pause for confirmation.

---

## 7. Conventions & decisions

### Gotchas (verified)

- SQLAlchemy stores `str, Enum` members by **name** (`native_enum=False`); migration backfill/defaults must use uppercase (e.g. `'UNVERIFIED'`).
- Full alembic chain is not SQLite-portable (0002 uses PG `btrim`); migration tests exercise individual revisions in isolation.
- Unique *constraints* cannot be `ALTER`ed on SQLite (`NotImplementedError`) — implement them as **unique indexes** (`op.create_index(..., unique=True)`) named like the model constraint (pattern: 0006 inn/ogrn, 0007 branch code, 0008 license number, 0009 key_hash).
- `PATCH ""` clears a field → `NULL`; verification status can only move **to `PENDING`** via the human API.
- `Organization.status = ACTIVE` is necessary-not-sufficient for integration (§4.15); `/organizations/me/*` is authorized by the resolved `OrganizationMembership.role ∈ {owner, admin}` (4b — no global `organization_admin` `AccountRole`; onboarding grants **no** global role).
- Multi-membership: `get_active_organization_for_account` is deterministic (earliest `joined_at`) for legacy reads; 4a fixes resolution + adds `list_active_organizations_for_account`; 4b makes **current-org selection explicit** on `/organizations/me/*` writes — single ACTIVE membership is implicit, several require `X-Organization-Id` (ambiguous → 400, unknown → 404); context reads (`GET /organizations`, `GET /organizations/{id}`) stay membership-scoped.
- Unique DB indexes are the idempotency source of truth for INN/OGRN: always catch `IntegrityError` → rollback → 409 (concurrent admin onboarding).
- INN/OGRN validation normalizes away **all** whitespace (canonical digits stored), not just leading/trailing.
- `Organization.email`/`phone` are contact data; never auto-link to `Account` identity fields.
- `uv run` at the workspace root resolves all members incl. ai-worker → `torch` (no mac-x86 wheel); use `uv run --project apps/account-api …`.
- Follow `docs/development/CONTRIBUTING.md`: `Annotated` service aliases, router `raise_for`, service commits once.

### Open decisions (defaults chosen; none block a phase)

1. **INN/OGRN checksum** — enforce lengths always; checksum behind `integration_validate_inn_checksum=True` (disabled if registry has odd cases). ✓ applied in Ph1.
2. **Rate limit / batch size** — 120 req/min/key, max 100 items — configurable.
3. **Integration read of canonical** — status + `document_date` only in v1; `read_canonical` scope possible later.
4. **Notification timing** — process-completed/-failed only; "received" is optional P1 (two-emails risk).
5. **Org schema format** — JSON Schema, published immutable; not yet consumed by ai-worker.
6. **API-key scopes** — the 4 of §4.2; no `full`/per-type scopes.
7. **`organization_api_requests` retention** — 90 days; purge in 4h.
8. **Org docs quota** — no free-plan cap (server-side submissions).
9. **Bulk processing** — synchronous per-item in-request; RabbitMQ consumer is P1.
10. **Registrable legal data** — `inn`/`ogrn` required when a `system_admin`
    registers an organization via `POST /admin/organizations` (4a); `legal_address`
    optional. Relax later if a use case needs it.
11. **Verification policy** — integration requires `verification_status ≠ REJECTED`; management endpoints are not verification-gated. §4.15.
12. **Global role** — onboarding grants **no** global `organization_admin`
    `AccountRole` (representative authorization = `OrganizationMembership.role`);
    the legacy global-role check on `/organizations/me/*` is **resolved**:
    migrated to membership-role auth in 4b (done). Not a security boundary of its own.
13. **Multi-org per account** — allowed by default (no cap in 4a); a per-account org cap would be an explicit product decision, not a schema consequence.

### Risks (mitigations in place)

- Concurrent account/patient creation → `email_normalized` UNIQUE + reload pattern; explicit concurrency tests.
- Concurrent org onboarding (same INN/OGRN, two system admins) → DB unique index + `IntegrityError`→409; explicit concurrency test (4a).
- Multi-membership `MultipleResultsFound` 500 → deterministic membership resolution (4a) + explicit current-org selection on writes (4b).
- IDOR in integration reads → mandatory org-scope checks returning 404; security tests per resource.
- Duplicate docs on retry → partial unique `(org, external_id)` + `(org, idempotency_key)`.
- Org schema/canonical coupling → strict separation (metadata only).
- Notification data leakage → template-driven body (org name + availability only).
- Large bulk in one transaction → per-item transactions + bounded batch size.
- Migration integrity → nullable columns for existing rows; PG downgrade verification per `docs/development/MIGRATIONS.md`.
- Secret material → `INTEGRATION_API_HMAC_KEY` in `_KEY_SETTINGS` production guards.
- API-key sprawl/leakage → prefix display, single-show raw, revoke/rotate/expiry, `last_used_at`.