# RBAC — Roles & Permissions

Implemented in PostgreSQL (`roles`, `permissions`, `account_roles`,
`role_permissions`). Models in `apps/account-api/app/models/role.py`,
enums in `apps/account-api/app/domain/`.

## Roles (`RoleCode`)

```text
CLIENT
SPECIALIST
ORGANIZATION_ADMIN
SYSTEM_ADMIN
SUPPORT
```

## Permissions (`PermissionCode`)

```text
medical_record.read / medical_record.write
document.read / document.upload / document.download
encounter.read / encounter.create / encounter.update
analytics.read
user.manage
organization.manage
```

## Role → permission seeding

| Role | Permissions |
|------|-------------|
| `client` | `document.read/upload/download`, `medical_record.read` |
| `specialist` | + `encounter.*`, `medical_record.write`, `analytics.read` |
| `system_admin` | everything |

Seeding is idempotent (`RbacRepository.seed_defaults()`), run at startup and
via `POST /admin/rbac/seed`.

## Admin endpoints

You can assign in spite of these docs:

```text
POST /admin/rbac/seed
POST /admin/accounts/{id}/roles          assign roles
GET  /admin/accounts/{id}/roles
GET  /admin/accounts/{id}/permissions
```

## Dependencies

```text
require_roles(*codes)          → 403 on missing role
require_permission(code)       → 403 on missing permission
```

## Limits

RBAC answers *global* capability only. Access to a **specific patient** is
checked separately through `patient_access_grants`
(see [ACCESS_CONTROL.md](ACCESS_CONTROL.md)).