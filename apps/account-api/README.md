# account-api

User cabinet API: registration, OTP auth, refresh-token sessions, PDF/image
uploads to S3.

> Architecture and behavior docs live in the repo-wide [docs/](../../docs/README.md):
> [Account API](../../docs/services/ACCOUNT_API.md),
> [DB models](../../docs/data/DB_MODELS.md),
> [Authentication](../../docs/security/AUTHENTICATION.md).

## How it works

### Registration & OTP auth (`POST /v1/auth/*`)

1. User registers with **email or phone number**.
2. Service publishes a notification event; a **notification worker** delivers the
   **OTP code** (email / SMS).
3. User submits the OTP code.
4. On successful verification the service issues an **access token** (JWT) and a
   **refresh token** (opaque), and persists an `authentication_session` row.

Tokens are setup:
- `access_token` — short-lived, stateless JWT used on every request.
- `refresh_token` — long-lived, opaque; stored in DB only as an **HMAC hash**
  (never the plain value, never plain SHA-256).
- Refresh rotation: each refresh issues a new refresh token and revokes the old
  session (see `AuthSession.revoke()`).

### `AuthSession` aggregate

One row per device/login, tracking full session lifecycle:

| Field | Purpose |
| --- | --- |
| `id` | Session UUID |
| `user_id`, `user_type` | Owning user |
| `refresh_token_hmac` | HMAC of the refresh token (opaque, non-recoverable) |
| `user_agent`, `ip_address`, `platform`, `app_version` | Client metadata |
| `device_id` | Optional device fingerprint (multi-device sessions) |
| `expires_at`, `revoked_at`, `created_at`, `last_used_at` | Lifecycle timestamps |
| `_domain_events` | Internal buffer emitting `SessionRevokedEvent` (and future events) |

Key methods:
- `create(...)` — factory for a new session.
- `revoke()` — revokes the session and appends `SessionRevokedEvent`.
- `is_valid()` — `True` while not revoked and not expired.

### File uploads (`POST /v1/documents/*`)

Once registered, a user can upload **PDF or image** files:

1. Client requests a presigned S3 upload URL.
2. Upload worker moves the object into cloud.ru **S3-compatible object storage**.
3. Document metadata and processing jobs are tracked via the pdf-contracts
   event bus (uploaded -> conversion requested -> converted -> completed).

**Quota:**
- Free (not subscribed) users are limited to **10 documents**.
- Subscribed users have an unlimited (or higher) quota.
- Quota is enforced at upload time; exceeded attempts are rejected.

## Layout

```text
app/
  main.py          FastAPI app entrypoint
  api/v1/          HTTP endpoints: auth, documents, jobs, users
  core/            config, database, security (JWT/HMAC, OTP)
  models/          persistence models (User, AuthSession, ...)
  schemas/         Pydantic request/response models
  services/        business logic: auth/session, documents, jobs, storage
  repositories/    data access layer
  middleware/      HTTP middleware (auth, request id, CORS, ...)
  dependencies/    FastAPI dependencies (JWT, session, storage)
tests/
```

Shared infrastructure comes from the workspace packages: `pdf-contracts`
(event schemas), `pdf-messaging` (RabbitMQ pub/consume), `pdf-storage` (S3),
`pdf-observability` (structured logging + metrics).

## Run

```bash
# From the repo root
uv run --project apps/account-api uvicorn app.main:app --reload
```

Worker (notification / upload) and the dev stack (Postgres, RabbitMQ,
S3/MinIO) come up via the repo Makefile:

```bash
make compose-dev
```