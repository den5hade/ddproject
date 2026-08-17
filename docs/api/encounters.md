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
- View/update: patient owner or grant holder
  (`can_edit_medical_data` for edits).

## Behavior

- `specialist_id` is filled from the acting account
  (account → person → specialist); `organization_id` from membership if any.
- Documents linked to an encounter keep `medical_record_id = patient's record`.

## Fields

`type` (`consultation/follow_up/procedure/admission/telemedicine/other`),
`status` (`scheduled/in_progress/completed/cancelled/no_show`),
`started_at`, `ended_at`, `reason`, `summary`.
