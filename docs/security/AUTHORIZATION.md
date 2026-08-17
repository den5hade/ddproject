# Authorization

How the platform decides what an actor may do. Two mechanisms work together,
and for medical data one alone is **not enough**:

- **RBAC** — role → permissions. Answers "what can a `specialist` do?".
- **ABAC / resource authorization** — permission + relationship to the
  resource. Answers "may *Dr. Ivanov* see *Patient #123*?".

## RBAC (see [RBAC.md](RBAC.md) for roles/codes)

```text
Account ── AccountRole ── Role ── RolePermission ── Permission
```

## ABAC via access grants (see [ACCESS_CONTROL.md](ACCESS_CONTROL.md))

```text
Specialist
    │
    └── PatientAccessGrant
              │
              ├── can_view_documents
              ├── can_upload_documents
              ├── can_view_extractions
              ├── can_view_analytics
              ├── can_create_encounters
              └── can_edit_medical_data
```

## Decision model

```text
Can Dr. Petrov read Document X?
  = authenticated
  AND account.active
  AND role grants the permission
  AND patient_access_grant exists (patient → specialist)
  AND grant active AND not expired
  AND grant flag set (e.g. can_view_documents)
  AND document belongs to that patient's medical_record
```

RBAC flags alone are never sufficient for medical data — resource ownership +
grant + expiry are mandatory.

## Least privilege

`system_admin` **does not** get automatic access to medical records. If such
access is needed it is a separate privileged permission (`medical_data_admin`)
and always audited.