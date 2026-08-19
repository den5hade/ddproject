# Encounters API

A specific visit/contact with a specialist. One encounter may have several
documents.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/patients/{id}/encounters` | Create encounter |
| `GET` | `/api/v1/patients/{id}/encounters` | List for a patient |
| `GET` | `/api/v1/encounters/{id}` | Get one |
| `PATCH` | `/api/v1/encounters/{id}` | Update status/ended_at/summary |
| `GET` | `/api/v1/encounters/{id}/documents` | Documents of the encounter |

## Authorization

- Create: specialist with `can_create_encounters` grant flag, or the patient
  owner.
- View: patient owner or any active grant holder.
- Update (`status`/`ended_at`/`summary`): patient owner or grant holder with
  `can_edit_medical_data`.

## Behavior

- `POST /patients/{id}/encounters` returns `201`; a new encounter starts in
  `status=scheduled`.
- `specialist_id` is filled from the acting account
  (account → person → specialist); `organization_id` from active membership
  if any — both resolved inline by the service.
- `GET /patients/{id}/encounters` returns `404` for anyone without ownership or
  a grant (hides the patient's existence). `GET`/`PATCH /encounters/{id}`
  without access return `403`.
- `PATCH /encounters/{id}` requires at least one of `status`, `ended_at`,
  `summary` (`422` otherwise).
- `GET /encounters/{id}/documents` lists documents whose `encounter_id` is this
  encounter; those documents keep `medical_record_id = patient's record`.

## Fields

`type` (`consultation/follow_up/procedure/admission/telemedicine/other`),
`status` (`scheduled/in_progress/completed/cancelled/no_show`),
`started_at`, `ended_at`, `reason`, `summary`.
