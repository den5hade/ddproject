# Testing

How the platform is tested.

## Test layout

```text
tests/                       cross-service (integration)
apps/account-api/tests/
  conftest.py                fixtures (app_client, db, mocks)
  test_auth_flow.py          registration → OTP → token → /auth/me
  unit/
    test_auth_session.py
    test_otp.py
    test_security.py
```

## Levels

- **Unit (domain + service)** — sqlite `create_all` (no migrations): status
  state machines, invariants (patient ⇒ medical record), grant rules, document
  version rotation.
- **API** (fixture `app_client`) — following `test_auth_flow.py`: register
  patient, upload document, create encounter, grant/revoke access, expect
  `403` for a specialist without a grant.
- **RBAC** — seeding is idempotent; account without a role → `403` on admin
  routes.
- **Integration** — `tests/integration/` for cross-service flow.

## Run

```bash
uv run --project apps/account-api pytest apps/account-api
uvx ruff check apps packages tests
```

## Mocking

- Feature switches (`ai_feature`) and messaging/notification gateways are
  mocked (e.g. `RabbitNotificationGateway(None)`).
- External services (S3, RabbitMQ, Redis) are stubbed in unit/API tests;
  real ones are exercised via `make compose-dev` / integration tests.