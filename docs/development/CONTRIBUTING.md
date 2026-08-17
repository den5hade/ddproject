# Contributing

Conventions and rules for adding code.

## Layering (account-api)

```text
domain (enums, aggregate rules)         app/domain/*
Pydantic schema (request/response)      app/schemas/<domain>.py
repository (only SQL, no logic)         app/repositories/<entity>.py
service (invariants, events, commit)    app/services/<domain>.py
router (HTTP, Depends, errors → HTTP)   app/api/v1/<resource>.py
dependencies (auth/ABAC/RBAC)           app/dependencies/*
```

Rules:

- Repository **never commits**; service **commits once** at the end.
- Services raise domain exceptions; routers map them to `HTTPException`.
- Reuse enums from `app/domain/*` (type-safe).
- Foreign-data access **always** goes through `require_patient_access` —
  never ad-hoc checks.
- JSON columns use `sa.JSON` (portable; tests run on sqlite).
- No large router functions — keep HTTP/Depends/error mapping at the edge.

## Boundary rules

- Medical/structured data → PostgreSQL; binaries → S3; embeddings → Qdrant;
  events → RabbitMQ. AI is not the source of truth.
- Keep the "Does NOT" boundary of each service
  (see [services/](../services/)) — push back on drift.

## Lint & test

```bash
uvx ruff check apps packages tests
uv run --project apps/account-api pytest apps/account-api
```

Mocks: feature switches (`ai_feature`) and messaging gateways are mocked in
tests (as `RabbitNotificationGateway(None)`).

## Docs

- This documentation is the single source of truth for how the system works.
- Documentation ≠ task tracker: track work in GitHub Issues, not in `.md` files.
- Architecture-affecting changes should add/update an ADR in
  [docs/decisions/](../decisions/).