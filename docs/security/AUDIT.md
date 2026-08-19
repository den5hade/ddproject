# Audit

Append-only record of who did what, when, and on whose data. Required for a
medical system.

**Implementation status:** implemented in account-api M5 (`AuditService` +
`AuditLogRepository` + `GET /audit-logs`). Note: `Account` inherits SQLAlchemy
`Base.metadata`, so the mapped column is `metadata_`; API responses expose it
as `metadata` via a Pydantic alias.

## Table

`audit_logs` (see [data/DB_MODELS.md](../data/DB_MODELS.md)).

| column | notes |
|--------|-------|
| actor_account_id | who (nullable) |
| action | see actions below |
| resource_type / resource_id | what was accessed |
| patient_id | whose data (nullable) |
| ip_address | source (VARCHAR(45)) |
| user_agent | client UA (VARCHAR(512)) |
| metadata | JSON extras |
| created_at | when |

## Actions (`AuditAction`)

```text
LOGIN              LOGOUT
VIEW_PATIENT       VIEW_MEDICAL_RECORD
VIEW_DOCUMENT      DOWNLOAD_DOCUMENT
UPLOAD_DOCUMENT
CREATE_ENCOUNTER   UPDATE_ENCOUNTER
GRANT_ACCESS       REVOKE_ACCESS
VIEW_ANALYTICS
```

## Where entries are written

- `POST /auth/verify` / `/auth/refresh` → `LOGIN`
- `POST /auth/logout` → `LOGOUT`
- `require_patient_access` allow/deny → `VIEW_PATIENT`, `VIEW_DOCUMENT`,
  `VIEW_MEDICAL_RECORD`, etc. (every evaluation writes an entry, including
  denials with the reason in `metadata`)
- Grant create/update/revoke → `GRANT_ACCESS` / `REVOKE_ACCESS`

## Query

`GET /audit-logs?patient_id=&actor_id=&action=&limit=&offset=` — admin only
(`system_admin`). Response rows include `actor_account_id`, `action`,
`resource_type` / `resource_id`, `patient_id`, `ip_address`, `user_agent`,
`metadata`, `created_at`.

## Guarantees

- Append-only: no ad-hoc deletion.
- Audit entries survive data deletion (retention policy governs, not ad-hoc
  cleanup).
