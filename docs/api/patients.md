# Patients API

Patient + Medical Record profile.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/patients/me` | Own patient (auto-created on first call) |
| `PATCH` | `/api/v1/patients/me` | Update own person data |
| `GET` | `/api/v1/patients/{id}` | Owner or specialist with access grant |

## Authorization

- Patient: own patient only.
- Specialist: requires an active `PatientAccessGrant` (see
  [security/ACCESS_CONTROL.md](../security/ACCESS_CONTROL.md)).

## Behavior

- `Patient` is auto-created together with a `MedicalRecord` in one transaction
  (invariant: patient ⇒ medical record).
- `GET /patients/{id}` returns `403`/`404` for anyone without ownership or a
  grant.

## Related

- [access.md](access.md) — grants
- [documents.md](documents.md) — per-patient uploads
- [encounters.md](encounters.md) — per-patient encounters
