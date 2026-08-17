# ADR-005: Account ≠ Patient

- **Status**: Accepted
- **Date**: Proposed at project inception

## Context

Early model tied `User → Documents`. Specialists, patients, medical records and
access modeling require separating identity from medical subject.

## Decision

Separate **Account** (technical login) from **Person** (physical subject), and
Person from **Patient** / **Specialist**. One person can be both patient and
specialist. Patient → MedicalRecord is 1:1.

## Consequences

- Clean 1:1 `accounts.person_id`; UNIQUE `patients.person_id`.
- `uploaded_by_account_id` ≠ patient — uploader is tracked separately.
- Migration `0002` renamed `users` → `accounts` accordingly
  (see [DB_MODELS](../data/DB_MODELS.md)).