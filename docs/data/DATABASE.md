# Database

> Purpose: **WHY and HOW** we use PostgreSQL. The concrete schema lives in
> [DB_MODELS.md](DB_MODELS.md).

## Why PostgreSQL

- Source of truth for all structured (medical) data.
- ACID transactions across aggregate boundaries (patient + medical record,
  document + versions + jobs, etc.).
- FK integrity on a strict medical data model.
- JSON columns for flexible extraction payloads alongside typed columns.

## Boundaries

| Boundary | Owner |
|----------|-------|
| PostgreSQL | structured/medical data (source of truth) |
| S3 | binaries/original artifacts |
| Qdrant | embeddings/chunks (search index, rebuildable) |
| RabbitMQ | commands/events in transit, never durable business state |
| Redis | ephemeral OTP codes, rate limiting |

## Aggregates

```text
Account → Person → Patient/Specialist
Patient → MedicalRecord (1:1)
MedicalRecord → Documents, Encounters, Extractions, ProcessingJobs
Patient → PatientAccessGrant → Account (specialist)
Account → AuditLog
```

## Relationships summary

- `accounts.person_id` — 1:1 to `persons`.
- `patients.person_id` — UNIQUE (one person → one patient row).
- `medical_records.patient_id` — UNIQUE (one patient → one record).
- `documents.medical_record_id` — documents hang off the record, not the user.
- `documents.uploaded_by_account_id` ≠ patient — the uploader is tracked
  separately.
- `document_versions` — immutable; `UNIQUE(document_id, version)`.

## Indexes

Cover foreign keys used in access checks and listings:
`account_roles.account_id`, `patient_access_grants.patient_id` /
`.account_id`, `documents.medical_record_id`, `documents.encounter_id`,
`encounters.medical_record_id`, `document_processing_jobs.document_id`,
`audit_logs.patient_id` / `.actor_account_id`.

## Transactions

One service operation = one transaction committed once at the end of the
service layer. Repositories never commit; invariants (e.g. patient ⇒ medical
record) are created together in a single transaction.

## Migrations

Alembic at `migrations/alembic/`; see [development/MIGRATIONS.md](../development/MIGRATIONS.md).

## Backup & retention

TODO: document snapshot/PITR strategy, retention windows per data class, and
deletion flows. See [DATA_LIFECYCLE.md](DATA_LIFECYCLE.md).