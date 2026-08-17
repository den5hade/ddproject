# Privacy

> Status: placeholder. Consent and legal-retention specifics are not yet
> implemented (models deferred). This page lists the intended privacy posture
> and TODOs.

## Intent

- Medical data is confidential: access only through explicit, time-boxed,
  audited grants (see [ACCESS_CONTROL.md](ACCESS_CONTROL.md)).
- `system_admin` has no automatic medical access (least privilege).
- All access is audited (see [AUDIT.md](AUDIT.md)).

## Consent vs. Access (separate concepts)

Access (`patient_access_grants`) is *operational* — who can view now.
Consent (`patient_consents`) is *legal* — for which purpose the data may be
used.

Planned consent purposes:

```text
CONSULTATION
DOCUMENT_ACCESS
AI_ANALYSIS
DATA_SHARING
```

Each consent: `status`, `granted_at`, `revoked_at`, `expires_at`,
`granted_by`. Model is deferred.

## Data minimization

- Only the fields needed for the product are collected (see
  [data/DB_MODELS.md](../data/DB_MODELS.md)).
- Passwords/refresh tokens are never stored in plain text (HMAC-hashed).
- AI output is validated before it enters the medical DB.

## TODOs

- Define retention windows per data class (see [DATA_LIFECYCLE.md](../data/DATA_LIFECYCLE.md)).
- Implement `patient_consents`.
- Document deletion / right-to-be-forgotten flows.
- Encrypt sensitive columns / at-rest encryption.