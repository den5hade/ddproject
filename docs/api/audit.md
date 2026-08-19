# Audit API

Read-only access to the append-only audit log of who accessed what medical
data, when, and from where.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/audit-logs` | Query audit entries (admin) |

## Authorization

`system_admin` only (`require_roles(RoleCode.SYSTEM_ADMIN)`); any other role →
`403`. Unauthenticated → `401`.

## Query parameters

| param | notes |
|-------|-------|
| `patient_id` | filter entries touching this patient |
| `actor_id` | filter entries by acting account |
| `action` | filter by `AuditAction` (e.g. `VIEW_DOCUMENT`, `LOGIN`) |
| `limit` | max rows, default 100, cap 500 (`le=500`)
| `offset` | pagination |

## Response

Each entry: `id`, `actor_account_id`, `action`, `resource_type`,
`resource_id`, `patient_id`, `ip_address`, `user_agent`, `metadata`, `created_at`.

## Behavior

- Entries are written for every `require_patient_access` allow **and** deny
  (denial reason in `metadata`), grant create/update/revoke, and
  `LOGIN` / `LOGOUT`.
- The DB column is `metadata_` (SQLAlchemy reserves `metadata` on `Base`);
  JSON output uses `metadata`.

Contract details in [security/AUDIT.md](../security/AUDIT.md).