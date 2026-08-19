# Access Control

This is the **central security contract** for medical data access. Every
patient-medical-data endpoint must go through the `require_patient_access`
dependency; ad-hoc checks are not allowed.

**Implementation status:** implemented in account-api M5
(`app/dependencies/access.py`: `require_patient_access` + wrappers
`require_document_access` / `require_encounter_access` / `require_job_access`,
backed by `AccessService.allows`). All M2–M4 medical routes are gated through it.

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

1. Is account authenticated?                  NO → 401
2. Is actor the patient (owner)?              YES → ALLOW (audit)
3. Is account status active?                  NO → deny
4. Does account hold role `specialist`?       NO → deny
5. Does an active (non-expired) grant exist?  NO → deny
6. Does grant contain the required flag?      NO → deny
7. ALLOW
8. Write audit event (allow / deny + reason)
```

> Strict rule: a non-owner **must also hold `RoleCode.SPECIALIST`** — an active
> grant alone (e.g. for a `client` account) is not sufficient. Grant CRUD is
> owner-only (`require_patient_owner`).

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
- Grant insert/update/revocation is restricted to the owning patient
  (`require_patient_owner`); grant recipients manage nothing.

## Endpoints

```text
POST   /patients/{id}/access-grants          (patient grants access — owner only)
GET    /patients/{id}/access-grants          (owner only)
PATCH  /patients/{id}/access-grants/{gid}    (owner only; empty body → 422)
DELETE /patients/{id}/access-grants/{gid}    (owner only; revoke → status=revoked)
```
