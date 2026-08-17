# Access Control

This is the **central security contract** for medical data access. Every
patient-medical-data endpoint must go through the `require_patient_access`
dependency; ad-hoc checks are not allowed.

## Model

```text
Patient ── patient_access_grants ── Account (specialist)
```

Table: `patient_access_grants` (see [data/DB_MODELS.md](../data/DB_MODELS.md)).

| column | notes |
|--------|-------|
| patient_id | target patient |
| account_id | granting account (specialist) |
| organization_id | optional scope |
| can_view_documents / can_upload_documents / can_view_extractions / can_view_analytics / can_create_encounters / can_edit_medical_data | boolean flags, default false |
| status | `active / revoked / expired` |
| expires_at | optional; NULL = no expiry |
| access_reason | `treatment / consultation / diagnosis / follow_up` |
| granted_by_account_id | who granted |

## Decision algorithm

```text
Can actor access patient record?

1. Is account authenticated?                     NO → deny
2. Is account active?                            NO → deny
3. Does account have the required permission?    NO → deny
4. Is actor the patient?                         YES → ALLOW
5. Does an active PatientAccessGrant exist?      NO → deny
6. Is grant expired or revoked?                  YES → deny
7. Does grant contain the required flag?         NO → deny
8. ALLOW
9. Write audit event
```

Return `403` (or `404` to avoid revealing a patient's existence).

## Dependency signature

```python
require_patient_access(
    patient_id,
    *,
    can_view_documents=False,
    can_upload_documents=False,
    can_view_extractions=False,
    can_view_analytics=False,
    can_create_encounters=False,
    can_edit_medical_data=False,
)
```

## Rules

- `system_admin` never gets automatic medical access (least privilege).
- Every allow **and** deny writes an `AuditLog` row.
- Grants are time-boxed and revocable; both `status` and `expires_at` are
  checked on every evaluation.

## Endpoints

```text
POST   /patients/{id}/access-grants          (patient grants access)
GET    /patients/{id}/access-grants
PATCH  /patients/{id}/access-grants/{gid}
DELETE /patients/{id}/access-grants/{gid}    (revoke → status=revoked)
```
