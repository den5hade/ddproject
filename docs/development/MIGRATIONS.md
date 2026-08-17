# Migrations

Alembic-based schema migrations for account-api.

## Location

```text
migrations/
  alembic/
    env.py
    script.py.mako
    versions/
      0001_initial.py
      0002_medical_models.py
```

## Workflow

```bash
# From the repo root
alembic -c alembic.ini revision --autogenerate -m "descriptive_name"
alembic upgrade head
alembic downgrade -1
```

## Current state

- `0001_initial` — initial `users` / `auth_sessions` schema.
- `0002_medical_models` — accounts/persons/medical MVP schema (20 tables),
  renaming `users` → `accounts`, single-role `user_type` → `account_roles`,
  plus patients/specialists/documents/encounters/grants/audit.

## Conventions

- UUID PKs, UTC timestamps, enums stored as VARCHAR (`native_enum=False`).
- Migrations must be **downgrade-safe** (verified on PG before merge).
- Model changes land with models in `apps/account-api/app/models/` + a
  matching migration revision.

## Deferred tables (not yet migrated)

```text
observations   diagnoses   medications   patient_consents
```

Design in [data/DB_MODELS.md](../data/DB_MODELS.md) §deferred; target
migration `0003`.