# Access API

Manage who may access a patient's medical data.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/patients/{id}/access-grants` | Grant access (patient owner) |
| `GET` | `/api/v1/patients/{id}/access-grants` | List grants |
| `PATCH` | `/api/v1/patients/{id}/access-grants/{gid}` | Update flags / expiry |
| `DELETE` | `/api/v1/patients/{id}/access-grants/{gid}` | Revoke (status=revoked) |

## Authorization

Grant CRUD: patient owner only.

## Behavior

- Grant targets an account (specialist) + optional organization.
- Flags: `can_view_documents`, `can_upload_documents`,
  `can_view_extractions`, `can_view_analytics`, `can_create_encounters`,
  `can_edit_medical_data`.
- Optional `expires_at`; `access_reason`
  (`treatment/consultation/diagnosis/follow_up`).
- Every grant/revoke writes an audit entry.

## Contract

The full decision algorithm lives in
[security/ACCESS_CONTROL.md](../security/ACCESS_CONTROL.md) — every access
check runs through `require_patient_access`.