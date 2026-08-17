# ADR-006: Access grants instead of specialist_id on Patient

- **Status**: Accepted
- **Date**: Proposed at project inception

## Context

RBAC roles alone cannot express "Dr. Ivanov may view Patient #123". Conidered:
`patient.specialists` array, foreign keys directly on the Patient row.

## Decision

Use an explicit **`patient_access_grants`** table: patient → account
(specialist), optional organization, boolean permission flags, `status`,
`expires_at`, `access_reason`. A role defines capabilities; a grant defines
access to one patient.

## Consequences

- Time-boxed, revocable, auditable access (RBAC + ABAC + grant + org).
- `system_admin` never gets automatic medical access (least privilege).
- More joins at check time; centralized in the `require_patient_access`
  dependency (see [ACCESS_CONTROL](../security/ACCESS_CONTROL.md)).