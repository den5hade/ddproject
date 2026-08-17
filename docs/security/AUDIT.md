# Audit

Append-only record of who did what, when, and on whose data. Required for a
medical system.

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
  `VIEW_MEDICAL_RECORD`, etc.
- Grant create/revoke → `GRANT_ACCESS` / `REVOKE_ACCESS`

## Query

`GET /audit-logs?patient_id=&actor_id=&limit=` (admin only).

## Guarantees

- Append-only: no ad-hoc deletion.
- Audit entries survive data deletion (retention policy governs, not ad-hoc
  cleanup).
