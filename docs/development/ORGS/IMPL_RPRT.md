# Organization Domain — Implementation Report

**Status:** `implemented` — phases 1–4i complete, account-api suite **501
passed**, `ruff` clean on the org paths. Commits `9b683b7` → `04041cc`.

**Purpose.** Two audiences in one file:

1. **Frontend development agent** — a self-contained contract to build the
   System Admin *organization onboarding* UI and the post-login *organization
   management* UI: entities, enums, authorization matrix, endpoints with
   request/response shapes, screens to build and integration conventions.
2. **Feature summary** — what the organization contour now is, phase by phase,
   for PM/review/onboarding.

**Sources.** `docs/development/ORGS/IMPL_ARCH.md` (architecture), `IMPL_SPEC.md`
(canonical spec), `IMPL_PLAN.md` (status-tracked plan); domain data model in
`docs/data/DB_MODELS.md`. Implementation lives in `apps/account-api/`
(models/schemas/services/repositories/api), `apps/notification-worker/` and
`packages/contracts/`.

---

## 1. Executive summary

The org contour turns `Organization` from a bare domain entity into a full
integration slice of the platform:

- **Admin onboarding** — a `system_admin` provisions an organization and
  connects its representative by email; there is **no public
  `POST /organizations`** self-registration.
- **Representative authorization** — an **organization-scoped** role on
  `OrganizationMembership` (`owner | admin | member`); a global
  `organization_admin` `AccountRole` is never granted.
- **Org management** — owner/admin maintain legal data, branches, licenses,
  API keys, document schemas and view API-usage via `/organizations/me/*`.
- **Integration API** — machine-to-machine `Bearer <api-key>` upload of single
  and bulk medical documents through the *existing* processing pipeline, with
  patient resolution by email, idempotency and org-scoped reads.
- **Notifications** — org-sourced documents notify the client by email
  (org name + secure link only, never medical data).

Everything reuses existing infrastructure: JWT/OTP auth, RBAC, the
document-processing pipeline, S3, RabbitMQ, `AuditLog`.

---

## 2. Feature summary (phase by phase)

| Phase | Headline | New tables / migration | Endpoints added |
|---|---|---|---|
| 1 | Organization core — legal data + INN/OGRN | `organizations` columns, `0006` | `GET/PATCH /organizations/me` |
| 2 | Branches | `organization_branches`, `0007` | `/organizations/me/branches` CRUD |
| 3 | Licenses | `organization_licenses`, `0008` | `/organizations/me/licenses` CRUD |
| 4 | Machine-to-machine API keys | `organization_api_keys`, `0009` | `/organizations/me/api-keys` CRUD + rotate |
| 4a | Admin organization onboarding | `0010` (`created_by_account_id`, membership `role`) | `/api/v1/admin/organizations` (5 routes) |
| 4b | Org context + membership-role auth | — | `GET /organizations`, `/organizations/{id}`, `/{id}/members` |
| 4c | API-key auth + verification policy | `organization_api_requests`, `0011` | `/integration/documents` stub, rate limit, request log |
| 4d | Integration API + patient resolver | documents source columns, `0012` | `POST /integration/documents`, `GET /integration/documents/{id}` |
| 4e | Bulk upload | `organization_upload_batches`(+items), `0013` | `POST /integration/documents/bulk`, `GET /integration/batches/{id}`(+`/items`) |
| 4f | Notifications | `notifications`, `0015` | notification-worker `send_message` + delivery round-trip |
| 4g | Organization document schemas | `organization_document_schemas`, `0014` | `/organizations/me/schemas` CRUD + publish |
| 4h | Monitoring / API usage | `0016` (usage index) | `GET /organizations/me/api-usage` + retention purge |
| 4i | Registry verification extension point | — (pure Python) | `OrganizationRegistryProvider` `Protocol` (no provider) |

Account-api suite grew to **501 tests**; notification-worker suite 11.

---

## 3. Domain & data model

```
Account ──< OrganizationMembership >── Organization
                                              │
                          ┌───────────────────┼───────────────────┐
                          │                   │                   │
              organization_branches  organization_licenses  organization_api_keys
                          │                   │                   │
              ...schemas  OrganizationRequest Log              upload batches/items
                 │
                 ▼
            Document (org-sourced: organization_id + source columns)
                 │
                 ▼
        existing processing pipeline → canonical → Notification
```

### 3.1 Entities and fields

**Organization** (`/organizations/me` response shape)

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `name` | string | 1–255 |
| `type` | enum | `clinic · hospital · private_practice · laboratory` |
| `status` | enum | `active · inactive` |
| `inn` | string\|null | canonical 10/12 digits, unique org-wide |
| `ogrn` | string\|null | canonical 13 digits, unique org-wide |
| `legal_address` | string\|null | ≤2000 |
| `email` / `phone` / `website` | string\|null | contact data, not identity |
| `verification_status` | enum | `unverified · pending · verified · rejected` |
| `created_by_account_id` | UUID\|null | the `system_admin` who onboarded it | 
| `created_at` / `updated_at` | datetime | serialized Europe/Moscow |

**OrganizationMembership** (role-scoped, 1 account : N orgs)

| Field | Type | Notes |
|---|---|---|
| `organization_id` / `account_id` | UUID | unique pair (`uq_organization_memberships_org_account`) |
| `role` | enum | `owner · admin · member` — **authorization source** for org management |
| `status` | enum | `pending · active · left` |
| `joined_at` | datetime | |

**OrganizationBranch**

| Field | Type | Notes |
|---|---|---|
| `id` / `organization_id` | UUID | |
| `code` | string | `^[A-Za-z0-9_-]{1,32}$`, unique per org (e.g. `MOSCOW_MAIN`, `SPB_01`) |
| `name` | string | 1–255 |
| `address` / `phone` | string\|null | |
| `status` | enum | `active · inactive` (soft-deactivate) |

**OrganizationLicense**

| Field | Type | Notes |
|---|---|---|
| `id` / `organization_id` | UUID | |
| `license_number` | string | ≤64, unique per org |
| `license_type` | string | ≤64, e.g. «стоматология», `radiology` |
| `status` | enum | `active · expired · suspended · revoked · pending` |
| `issued_at` / `expires_at` | date\|null | `expires_at` must not precede `issued_at` |
| `scope` / `issuer` | string\|null | |

**OrganizationApiKey**

| Field | Type | Notes |
|---|---|---|
| `id` / `organization_id` | UUID | |
| `name` | string | 1–128 |
| `prefix` | string | first 12 chars of `ddorg_<env>_<secret>`, for display |
| `status` | enum | `active · revoked · expired` |
| `permissions` | list[enum] | 4 scopes (see §4) |
| `created_by_account_id` / `created_at` / `expires_at` / `revoked_at` / `last_used_at` | | `last_used_at` best-effort |

**OrganizationDocumentSchema**

| Field | Type | Notes |
|---|---|---|
| `id` / `organization_id` | UUID | |
| `name` | string | 1–128, one draft per name at a time |
| `description` | string\|null | |
| `document_type` | enum | platform `DocumentType` (see below) |
| `schema_definition` | object | structural JSON-Schema-like registry shape |
| `version` | int | monotonic per `(org, name)` |
| `status` | enum | `draft · published` — **published is immutable** |
| `published_at` | datetime\|null | |

**OrganizationUploadBatch / Item** (integration, visible in usage stats)

- Batch statuses: `accepted · processing · completed · partial · failed`.
- Item statuses: `pending · accepted · rejected` (+ `error_code`/`error_message`,
  e.g. `duplicate_external_id`, `patient_resolution_failed`, `branch_not_found`,
  `file_too_large`, `unsupported_file_type`, `internal_error`).

**Notification**

- Types: `document_received · document_processed · document_processing_failed`.
- Statuses: `pending · sent · failed · read`. Channel: `email`.
- Server-side; the client app does not need a notifications page in this phase.

**Document source columns** (org-sourced documents)

- `organization_id`, `organization_branch_id`, `external_id`,
  `idempotency_key`, `provided_document_type`; `uploaded_by_account_id` stays
  `NULL` for API uploads.

### 3.2 Serialized enum values (JSON picks up these lowercase strings)

- **DocumentType**: `lab_result · doctor_report · prescription ·
  discharge_summary · imaging_report · referral · medical_certificate · other`
- **DocumentStatus**: `pending · uploaded · processing · completed · failed ·
  deleted`

---

## 4. Authorization model (UI gating matrix)

Three actor kinds, three trust domains — never mixed:

| Actor | Credential | Scope of access | Gates used by UI |
|---|---|---|---|
| System admin (platform operator) | JWT + `RoleCode.SYSTEM_ADMIN` | `/api/v1/admin/organizations` only | full **org onboarding** UI |
| Org owner / admin | JWT + **ACTIVE** `OrganizationMembership.role ∈ {owner, admin}` | `/organizations/me/*` + context writes | full **org management** UI |
| Org member | JWT + ACTIVE membership, role `member` | context reads only (`GET /organizations`, `GET /organizations/{id}`) | read-only shell, no management |
| Machine | `Authorization: Bearer <api-key>` | integration endpoints by **scope** | none (backend tooling) |

**Current-org selection (multi-membership).** An account may hold ACTIVE
memberships in several organizations.

- One ACTIVE membership → implicit (no header needed).
- Several → write/`/me/*` calls must send **`X-Organization-Id: <org-id>`**;
  missing/ambiguous → **400** `ambiguous organization context`; unknown id →
  **404**.
- `GET /organizations` returns *all* my orgs — drive an org switcher from it,
  then send the picked `id` as `X-Organization-Id` on `/me/*` calls.

**Verification gate (locked).** `Organization.status = ACTIVE` is *necessary but
not sufficient* for integration access. Integration requires
`verification_status ≠ rejected`. Management endpoints (`/organizations/me/*`)
are **not** verification-gated (management ≠ production data access).

**API-key scopes** (`permissions`):

```
organization.documents.upload       organization.documents.bulk_upload
organization.documents.read         organization.jobs.read
```

---

## 5. API reference

All routes live under `/api/v1`. Datetimes serialize to Europe/Moscow. Lists are
flat (no pagination in v1). The middleware echoes `X-Request-Id`.

### 5.1 Admin onboarding — `system_admin` only

`OrganizationAdminCreate` = `{ organization: OrganizationCreate,
administrator: OrganizationMemberCreate }`.

`OrganizationCreate` (required `name`, `type`, `inn`, `ogrn`; optional
`legal_address`, `email`, `phone`, `website`). `inn` is normalized to canonical
10-or-12 digits and checksum-validated (`integration_validate_inn_checksum`);
`ogrn` to 13 digits.

`OrganizationMemberCreate` = `{ email, role: "owner" | "admin" | "member"
(default "owner") }`.

| Method | Path | Success | Errors |
|---|---|---|---|
| `POST` | `/admin/organizations` | **201** `OrganizationResponse` | 403 non-admin · 409 dup INN/OGRN · 422 invalid |
| `GET` | `/admin/organizations` | 200 `OrganizationResponse[]` | 403 |
| `GET` | `/admin/organizations/{id}` | 200 `OrganizationResponse` | 403 · 404 |
| `POST` | `/admin/organizations/{id}/members` | **201** `OrganizationMemberResponse` | 403 · 404 org · 409 duplicate pair / org not ACTIVE · 422 |
| `GET` | `/admin/organizations/{id}/members` | 200 `OrganizationMemberResponse[]` | 403 · 404 |

One create call = one transaction: org (ACTIVE, verification PENDING,
`created_by_account_id` = admin) + account resolve-or-create by email (new
accounts are PENDING) + owner membership. Audit writes
`ORGANIZATION_CREATED` + `ORGANIZATION_ADMIN_ADDED`.

### 5.2 Organization management — JWT + membership role (`owner|admin`; context reads any member)

**Context**

| Method | Path | Gate | Success |
|---|---|---|---|
| `GET` | `/organizations` | any member | 200 list of my orgs |
| `GET` | `/organizations/{id}` | member (foreign → 404) | 200 |
| `GET` | `/organizations/{id}/members` | `owner\|admin` | 200 `OrganizationMemberResponse[]` |

**Profile**

| Method | Path | Success | Notes |
|---|---|---|---|
| `GET` | `/organizations/me` | 200 `OrganizationResponse` | |
| `PATCH` | `/organizations/me` | 200 | ≥1 field; INN/OGRN change → `verification_status = pending`; `""` clears a field |

**Branches** (dup `code` → 409; DELETE is soft-deactivate → 204)

| Method | Path | Success |
|---|---|---|
| `GET` / `POST` | `/organizations/me/branches` | 200 `BranchResponse[]` / 201 |
| `GET` / `PATCH` | `/organizations/me/branches/{id}` | 200 / 200 |
| `DELETE` | `/organizations/me/branches/{id}` | 204 |

**Licenses** (dup `license_number` → 409; DELETE soft-revokes → 204; past-due
ACTIVE licenses auto-flip to `expired` on read)

| Method | Path | Success |
|---|---|---|
| `GET` / `POST` | `/organizations/me/licenses` | 200 / 201 |
| `GET` / `PATCH` | `/organizations/me/licenses/{id}` | 200 / 200 |
| `DELETE` | `/organizations/me/licenses/{id}` | 204 |

**API keys** (raw key shown **once**; list hides it)

| Method | Path | Success | Notes |
|---|---|---|---|
| `GET` / `POST` | `/organizations/me/api-keys` | 200 `ApiKeyResponse[]` / 201 `ApiKeyCreateResponse` | POST body = `{name, scopes[], expires_at?}` |
| `DELETE` | `/organizations/me/api-keys/{id}` | 204 | idempotent revoke |
| `POST` | `/organizations/me/api-keys/{id}/rotate` | 200 `ApiKeyCreateResponse` | new ACTIVE key, old → `revoked` |

**Document schemas** (dup draft name / re-publish → 409; edit after publish →
422)

| Method | Path | Success |
|---|---|---|
| `GET` / `POST` | `/organizations/me/schemas` | 200 / 201 |
| `PATCH` | `/organizations/me/schemas/{id}` | 200 (draft only) |
| `POST` | `/organizations/me/schemas/{id}/publish` | 200 (freezes version) |

**Usage** (`?from=YYYY-MM-DD&to=YYYY-MM-DD`; default trailing 30 days, max span 90;
reversed or over-span → 422)

| Method | Path | Success |
|---|---|---|
| `GET` | `/organizations/me/api-usage` | 200 `OrganizationApiUsageResponse` (counts/dates only, **no PII**) |

### 5.3 Integration API — machine (informational for the UI team)

Auth: `Authorization: Bearer <ddorg_...>`; per-endpoint scope; rate limit
120 req/min/key → 429; org inactive or verification `rejected` → 403; bad key →
401.

| Method | Path | Scope | Success | Notes |
|---|---|---|---|---|
| `POST` | `/integration/documents` | `documents.upload` | 201 new / **200 idempotent replay** | multipart form (`patient_email`, `document_type?`, `external_id?`, `branch_code?`, `title?`) + file; 409 on conflicting keys |
| `POST` | `/integration/documents/bulk` | `bulk_upload` | 202 new / 200 replay | `metadata` JSON array + `files[]`; > `integration_max_batch_size` (100) or count mismatch → 422 |
| `GET` | `/integration/documents/{id}` | `documents.read` | 200 status | cross-org → 404 |
| `GET` | `/integration/batches/{id}` | `documents.read` | 200 `OrganizationBatchResponse` (incl. items) | cross-org → 404 |
| `GET` | `/integration/batches/{id}/items` | `documents.read` | 200 `OrganizationBatchItemResponse[]` | cross-org → 404 |

### 5.4 Common error semantics

| Code | Meaning |
|---|---|
| 400 | ambiguous org context (missing `X-Organization-Id`, multi-membership) |
| 401 | bad / missing / revoked / expired API key |
| 403 | insufficient role (non-admin calling admin endpoints, `member` on management) · org inactive · verification `rejected` · missing key scope |
| 404 | cross-org / not found (IDOR policy: foreign resources read as 404, **never** 403) |
| 409 | duplicate INN/OGRN · branch code · license number · `(org, account)` membership · draft name · re-publish · idempotency conflict |
| 413 | file too large |
| 415 | unsupported file type |
| 422 | schema/validation · malformed bulk metadata · usage range out of bounds ·
| 429 | rate limit exceeded |

---

## 6. Example payloads

**Create org + connect owner** → `POST /api/v1/admin/organizations`

```json
{
  "organization": {
    "name": "ООО Медицинский центр",
    "type": "clinic",
    "inn": "7707083893",
    "ogrn": "1027700132195",
    "legal_address": "г. Москва, ул. Ленина, 10",
    "email": "info@clinics.ru",
    "phone": "+7 (495) 000-00-00",
    "website": "https://clinic.example"
  },
  "administrator": {
    "email": "director@clinic.example",
    "role": "owner"
  }
}
```

```json
// 201
{
  "id": "6d8f…-uuid","name": "ООО Медицинский центр","type": "clinic",
  "status": "active","inn": "7707083893","ogrn": "1027700132195",
  "legal_address": "г. Москва, ул. Ленина, 10","email": "info@clinics.ru",
  "phone": "+7 (495) 000-00-00","website": "https://clinic.example",
  "verification_status": "pending","created_by_account_id": "admin-uuid",
  "created_at": "2026-09-18T12:00:00+03:00","updated_at": "2026-09-18T12:00:00+03:00"
}
```

**Attach an existing org's representative** → `POST
/api/v1/admin/organizations/{org_id}/members`

```json
{ "email": "doctor@clinic.example", "role": "admin" }
```

**Create branch** → `POST /api/v1/organizations/me/branches`
(with `X-Organization-Id` if multi-membership)

```json
{ "code": "MOSCOW_MAIN", "name": "Головной офис", "address": "г. Москва, ул. Ленина, 10", "phone": "+7 (495) 000-00-00" }
```

**Create API key** → `POST /api/v1/organizations/me/api-keys`

```json
{ "name": "Production", "scopes": ["organization.documents.upload", "organization.documents.read"] }
```

```json
// 201 — raw_key only here and on rotate
{ "id": "…", "organization_id": "…", "name": "Production", "prefix": "ddorg_liv_aBc…",
  "status": "active", "permissions": ["organization.documents.upload","organization.documents.read"],
  "created_by_account_id": "…", "created_at": "…", "expires_at": null, "revoked_at": null,
  "last_used_at": null, "raw_key": "ddorg_liv_aBcD_eFgH…" }
```

**Create + publish a schema**

```json
// POST /organizations/me/schemas
{ "name": "cbc", "document_type": "lab_result",
  "schema_definition": { "type": "object", "properties": { "hemoglobin": { "type": "number" } } } }
// POST /organizations/me/schemas/{id}/publish  →  version: 1, status: "published"
```

**Usage query** → `GET /api/v1/organizations/me/api-usage?from=2026-08-19&to=2026-09-18` — response uses `from`/`to` keys, `days[]`, `total_*`/`overall_*` roll-ups (no PII).

---

## 7. Frontend: screens & flows to build

The web app (`apps/web`) currently has no admin or org-management area; routes are
auth/documents/medical-record/profile. Below are the flows to add, gated exactly
as in §4. UI copy should be Russian (matches existing `lib/i18n/strings.ts`).

### 7.1 System Admin — Organization onboarding UI (new, role-gated)

Landing: **Organizations** screen — list from `GET /admin/organizations`, a
search box filtering by **INN / OGRN / name** (client-side filter; the API list is
flat), rows showing name, INN, status badge, verification badge, and actions
`[Open]` `[Add administrator]` `+ Add organization`.

1. **Create organization** ("Create and connect") — one form, one submit →
   `POST /admin/organizations`:
   - Organization: `name *`, `type *` (select), `INN *`, `OGRN *`, legal address,
     email, phone, website.
   - Administrator: `email *`, `role` (default **Owner**).
   - 409 on duplicate INN/OGRN → show message and offer to open the existing org.
2. **Add administrator** to an existing org → `POST
   /admin/organizations/{id}/members` — `email *`, `role`. 409 on duplicate
   membership.
3. **Organization detail** — `GET /admin/organizations/{id}`: legal data,
   `status`, `verification_status`, `created_by_account_id`, created/updated.
4. **Members list** — `GET /admin/organizations/{id}/members` (role, status,
   joined_at).

### 7.2 Org owner/admin — Organization management UI (post-login, role-gated)

Context:

- **Org switcher** — drive from `GET /organizations` (all my orgs with active
  membership). Persist the selection; send it as **`X-Organization-Id`** on all
  `/organizations/me/*` calls. Accounts with a single membership do not need the
  header. Handle **400 ambiguous** (prompt to pick) and **404 unknown**.
- **Shell** — if the current membership role is `member`, show context read-only
  (no management tabs).

Tabs:

1. **Settings / legal data** — `GET|PATCH /organizations/me`. INN/OGRN change
   warns that verification resets to `pending`. PATCH supports `""` to clear a
   field, ≥1 field required.
2. **Branches** — list, create (`code` incl. pattern `^[A-Za-z0-9_-]{1,32}$`),
   edit, soft-deactivate (DELETE → row disappears from *active* list, history
   kept). Dup code → 409.
3. **Licenses** — list with status badges (`active`/`expired`/`suspended`/`revoked`/`pending`), create/edit, soft-revoke. Note auto-`expired` on read for past-due licenses; `expires_at` must be ≥ `issued_at`.
4. **API keys** — list showing `name`, `prefix` (masked), status, `expires_at`, `last_used_at`; create (modal with **copy-now** raw key — it is never shown again, only `prefix` persists); revoke; rotate (returns a new raw key showing once). Scope multi-select of the 4 scopes.
5. **Document schemas** — list of drafts + published versions (`name`, `document_type`, `version`, `status`); create draft, edit draft, **publish** (freezes; further edits require a new version). One draft per name; re-publish → 409; edited-after-publish → 422.
6. **API usage** — date-range picker (`from`/`to`, default last 30 days, max 90) hitting `/organizations/me/api-usage`; render/day series and totals. No PII — safe to display.
7. **Members** — `GET /organizations/{id}/members` (owner/admin only).

---

## 8. Frontend implementation notes

- After the API is running locally, regenerate the typed client:
  `npm run generate:api` → `openapi-typescript http://localhost:8000/openapi.json
  -o src/lib/api/schema.d.ts`. The committed `schema.d.ts` predates the org
  work — regenerate before using org endpoints.
- Use the existing `openapi-fetch` client (`src/lib/api/client.ts`), react-query
  hooks per feature (`src/features/<feature>/hooks.ts`), query keys in
  `src/lib/query/keys.ts`, i18n strings in `src/lib/i18n/strings.ts`, and the
  UI primitives in `src/components/ui/` (button, input, card, select, tabs,
  menu, badge…).
- Add role-aware routing: the auth guard layout already protects authed pages;
  add a `system_admin`-only guard for the admin section and an
  `owner|admin`-only guard for the management tabs (mirror §4).
- **Timezones**: the API serializes all datetimes to **Europe/Moscow** —
  display them as-is (no client offset math).
- No pagination in v1 — org/branch/license/key/schema lists are flat arrays.

---

## 9. Semantic gotchas

- **Raw API key is shown exactly once** — on `POST /me/api-keys` and `/rotate`
  responses (`raw_key` field). Lists always hide it; only `prefix` is stored and
  shown.
- **Soft deletes only**: branch DELETE → `inactive`; license DELETE → `revoked`;
  api-key DELETE → `revoked`. Historical documents keep their branch source.
- **409 duplicate cases**: INN/OGRN (org-wide), branch `code`, license
  `license_number`, membership `(org, account)`, schema draft name, re-publish.
- **Cross-org transparency**: reading another org's resource returns **404, not
  403** (IDOR policy) — the UI should swallow 404s on foreign ids, not treat
  them as permissions errors.
- **Licenses auto-expire on read**: an ACTIVE license past `expires_at` is
  returned as `expired` (lazy transition — no scheduled job).
- **Verification semantics**: verification `rejected` blocks integration; a
  `pending` status remains usable for management endpoints.
- **Integration idempotency** manifests as 201→200 replays by `external_id` /
  `Idempotency-Key`; conflicting keys → 409. UI-agnostic but relevant for the
  bulk-upload monitoring UI.
- Rate limit is **120 requests/minute per key** → 429.

---

## 10. Run & verify

```bash
# API tests + lint (org phases 1–4i): 501 tests
uv run --project apps/account-api pytest apps/account-api
uvx ruff check apps/account-api

# Web app
cd apps/web && npm i && npm run dev        # http://localhost:5173
npm run generate:api                       # refresh schema.d.ts from local API
npm run test && npm run lint
```

To exercise the System Admin UI you first need an account with
`RoleCode.SYSTEM_ADMIN`; assign it through the admin accounts roles endpoint
(`/api/v1/admin/accounts/{account_id}/roles`). An org owner/admin is created
simply by onboarding an organization with their email (they complete login via
the standard OTP flow).