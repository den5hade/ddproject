# Auth & Security Fix Implementation Plan

Comprehensive implementation plan for the issues identified in `.dev/Security.md`
(cross-checked against the codebase), additional findings discovered during
verification, and corrections from the post-review audit of this plan.

**Revision 2** — incorporates review corrections: real `AccountStatus` values,
route-level exception wiring, atomic refresh rotation, refresh-time status
check, consumer recreation per attempt, corrected poison-message analysis,
OTP state cleanup on delivery failure, identity canonicalization,
`APP_ENV`-based secret validation, version-upload `encounter_id` decision.

**Revision 3** — progress tracking + locked decisions: F5-B implemented as a
direct DB session lookup per request (no Redis cache); F6 ships a full DLQ via
a dead-letter exchange in the shared `messaging.Consumer`; F10 scoped to the
account-api `Settings`. Unit tests live in
`apps/account-api/tests/unit/` (not root `tests/unit/`). Execution order
followed the footer constraints (F10 early, F5 after F2).

Status legend: `[ ]` pending · `[x]` done.

---

## 1. Findings summary

| # | Severity | Finding | Primary location | Status |
|---|----------|---------|------------------|--------|
| F1 | Critical | Live credentials in plaintext `.env`; weak shared dev secrets | `.env`, `infrastructure/development/.env` | confirmed · ops rotation pending |
| F2 | High | Disabled accounts keep using valid access tokens | `app/dependencies/auth.py:20-46` | fixed (`3062f02`) |
| F3 | High | Document can be attached to another patient's encounter | `app/services/documents.py:125-127` | fixed (`5d4e935`) |
| F4 | High | OTP codes logged in plaintext when publisher unavailable | `app/services/notifications.py:34-41` | fixed (`64ee3af`) |
| F5 | Medium | Logout does not invalidate issued access tokens; refresh rotation is racy | `app/services/auth.py:89-106`, `app/dependencies/auth.py` | fixed (`76290cf`) |
| F6 | Medium | Document-event consumer dies silently on broker or handler failure | `app/consumers/document_events.py:58-77` | fixed (`ac25958`) |
| F7 | Medium | OTP identity not validated/canonicalized; arbitrary strings become accounts and Redis keys | `app/schemas/auth.py:8-15`, `app/repositories/account.py:43-48`, `app/services/otp.py:36-46` | fixed (`c7771a6`) |
| F8 | High | `verify_otp` auto-reactivates BLOCKED/DELETED accounts on login | `app/services/auth.py:85-86` | fixed (`3062f02`) |
| F9 | High | `verify_otp` never sets `email_verified_at` / `phone_verified_at` despite proving identity ownership | `app/services/auth.py:79-87` | fixed (`3062f02`) |
| F10 | High | No startup validation of security-critical settings; empty defaults silently issue tokens that break after config change | `app/core/config.py:42-48` | fixed (`1dc60e1`) |
| F11 | Minor | `AuthSession.touch()` dead code; `last_used_at` semantics unclear | `app/domain/auth_session.py:78-80` | fixed (`76290cf`) · doc note pending |

Positive observations (no action needed): JWT algorithm allowlist, refresh
tokens stored only as HMACs, refresh-token rotation exists, constant-time OTP
comparison, basename-normalized upload paths in the storage worker.

---

## 2. Detailed fixes

### F1 — Credential hygiene (Critical, ops + config)

**Status:** repository-level guardrails already in place (`.gitignore`,
`.env.example` placeholders only); operations checklist below remains open.

**Problem.** Real-looking S3/SMTP credentials and DB/RabbitMQ passwords sit in
plaintext `.env` files. The same weak secrets (`super-secret-*`, `pdf123`) are
duplicated across the root `.env` and `infrastructure/development/.env`.
Credentials were also pasted into a chat conversation.

**Verified scope.** `.env` is *not* tracked in git and never was
(`git log --all -- .env` is empty; `.gitignore` blocks `.env*`). No history
rewrite required for this repo. This does **not** make exposed credentials
safe — rotation is still required.

**Plan.**

*Repository-level:*

- [x] Ensure no real credentials are ever committed (already satisfied by
      `.gitignore`; keep `.env.example` placeholders only).

*Operations checklist (cannot be proven by code/tests — track separately):*

- [ ] Rotate S3 access key/secret (cloud.ru tenant).
- [ ] Rotate SMTP password.
- [ ] Generate distinct strong values per environment: `JWT_SECRET_KEY`,
      `AUTH_HMAC_KEY`, `AUTH_OTP_PEPPER`, `AUTH_PIN_PEPPER`, DB and RabbitMQ
      passwords (do **not** share between root `.env` and
      `infrastructure/development/.env`).
- [ ] Never paste secrets into chats/tickets.
- [ ] Note: rotating `AUTH_HMAC_KEY` or `JWT_SECRET_KEY` invalidates all
      active sessions/tokens — users must re-login (documented in
      `docs/security/AUTHENTICATION.md` update, see §3 Docs).

**Acceptance criteria.** Old credentials no longer authenticate anywhere;
each env file has unique secrets; no secrets in git or chat artifacts.

---

### F2 + F8 — Account status enforcement, including at refresh time (High)

**Status:** done (`3062f02`). Implementation notes: `refresh` commits the
pending revocation before raising on inactive accounts (otherwise the
request-scoped rollback would resurrect the session); PENDING→ACTIVE is the
only promotion path; `/auth/verify` catches `AccountInactiveError`.

**Problem.**

- `get_current_account` (`app/dependencies/auth.py:20-46`) validates the JWT
  signature/expiry and loads the account but never checks `account.status`.
  A disabled account keeps full API access until its access token expires.
- Worse, `verify_otp` (`app/services/auth.py:85-86`) **auto-reactivates** any
  non-ACTIVE account — including `BLOCKED` and `DELETED`:

  ```python
  if account.status != AccountStatus.ACTIVE:
      account.status = AccountStatus.ACTIVE
  ```

- `AuthService.refresh` (`app/services/auth.py:99`) loads the account only to
  read its `id` and never checks status either — a BLOCKED/DELETED account
  with a valid refresh token can keep refreshing indefinitely.

**Real enum values** (`app/domain/account.py:8-12`): `PENDING`, `ACTIVE`,
`BLOCKED`, `DELETED`. There is no SUSPENDED/BANNED.

**Loginability matrix (normative).**

| Status | OTP login | Existing access token | Refresh |
|--------------|-----------|-----------------------|---------|
| `PENDING` | allowed; promoted to `ACTIVE` on first successful login | n/a (no tokens yet) | n/a |
| `ACTIVE` | allowed | allowed | allowed |
| `BLOCKED` | rejected `403` | rejected `401` | rejected `401` |
| `DELETED` | rejected `403` | rejected `401` | rejected `401` |

**Plan.**

1. New domain exception `AccountInactiveError` in `app/services/auth.py`
   (next to the other auth errors).
2. Register it in `_EXCEPTION_STATUS` (`app/api/v1/http_errors.py`) as
   `403 Forbidden`.
3. **Route wiring:** `/auth/verify` currently catches only
   `OtpVerificationError` (`app/api/v1/auth.py:46-49`). Add
   `AccountInactiveError` to its `except` clause so it maps through
   `raise_for(exc)` instead of becoming a `500`. Same for any other auth
   route that can raise it.
4. In `verify_otp`: delete the auto-reactivation block; allow promotion
   **only** `PENDING → ACTIVE`; raise `AccountInactiveError` for
   `BLOCKED`/`DELETED`.
5. In `get_current_account` (`app/dependencies/auth.py`): after loading the
   account, return `401 Unauthorized` ("account is disabled") unless
   `status == ACTIVE`. Use 401 so clients treat re-login as futile rather
   than a permissions problem.
6. In `refresh`: after loading the account, raise `RefreshTokenError`
   ("session account is disabled") when status is not `ACTIVE` — revoking the
   session here too is acceptable defense-in-depth.

**Acceptance criteria.**

- BLOCKED account: existing tokens get `401` on every protected endpoint;
  OTP login returns `403`; refresh returns `401`.
- PENDING account: can complete first login and becomes ACTIVE exactly once.
- No code path flips BLOCKED/DELETED back to ACTIVE.

---

### F9 — Mark identity verified on successful OTP (High)

**Status:** done (`3062f02`), including the forced-failure rollback test
(`test_verify_failure_rolls_back_verification`).

**Problem.** A successful email/phone OTP proves ownership of that identity,
but `verify_otp` never writes `email_verified_at` / `phone_verified_at`
(`app/models/account.py:30-39`). Accounts stay permanently "unverified"
despite verified login. Related: `last_login_at`
(`app/models/account.py:51-53`) is never updated.

**Atomicity note (review correction).** Per repo layering rules
(`docs/development/CONTRIBUTING.md`), the service commits once at the end.
Setting these attributes on the `Account` instance before calling
`_establish_session` already places them in the **same transaction** as
session creation — no extra commit logic is needed. What must be added is a
rollback test proving verification timestamps do not persist if session
creation fails.

**Plan.**

In `AuthService.verify_otp`, after the status check from F2/F8:

```python
now = datetime.now(UTC)
if detect_channel(identity) == "email":
    if account.email_verified_at is None:
        account.email_verified_at = now
else:
    if account.phone_verified_at is None:
        account.phone_verified_at = now
account.last_login_at = now
```

Notes:

- Reuse the shared channel detection from F7 (single source of truth).
- Only set the timestamp if currently NULL (first verification wins).
- The commit happens in `_establish_session` (single service-level commit).

**Acceptance criteria.**

- After email-code login, `accounts.email_verified_at` is set and stays set;
  phone login sets `phone_verified_at`; `last_login_at` updates each login.
- Rollback test: forcing session creation to fail leaves verification
  timestamps unset (transaction rolled back).

---

### F10 — Fail fast on insecure configuration (High)

**Status:** done (`1dc60e1`). Scope decision (revision 3): account-api
`Settings` only (auth/JWT/HMAC secrets live here); worker `Settings` classes
can adopt the same pattern in a follow-up. Conditional checks: S3 creds when
`s3_endpoint_url` set, `ai_api_key` when `ai_feature=true`;
`rabbitmq_password` skipped when a full `RABBITMQ_URL` is provided.

**Problem.** `Settings` defaults `auth_hmac_key=""`,
`jwt_secret_key="change-me-in-production"` (`app/core/config.py:42-48`). An
instance started without proper env silently issues tokens under an empty/weak
key; they become unresolvable after any config change (root cause of the
2026-08-21 "refresh token does not exist" incident).

**Design decision (review correction).** Do **not** gate enforcement on the
`debug` flag alone — a production deployment accidentally started with
`DEBUG=true` would bypass all checks. Introduce an explicit environment
setting instead.

**Plan.**

1. Add `environment: str = "development"` to `Settings` (values:
   `development` | `production`; env var `APP_ENV`/`ENVIRONMENT`).
2. On startup (in `Settings.model_post_init` or app lifespan):
   - **production**: fail hard (raise) when any of the following are empty,
     below a minimum length (< 32 chars for keys/secrets), equal to known
     placeholders (`change-me*`, `super-secret-*`, `pdf123`, `minioadmin`),
     or identical across two different settings:
     `jwt_secret_key`, `auth_hmac_key`, `auth_otp_pepper`,
     `auth_pin_pepper`, `postgres_password`, `rabbitmq_password`,
     `s3_key_secret`. Also validate S3/SMTP/Qdrant credentials where the
     corresponding feature is enabled.
   - **development**: log a warning naming the offending setting — the
     warning must **never include the secret value itself**.
3. Keep failure at import/startup time so orchestrators restart-loop visibly
   instead of serving with weak secrets.

**Acceptance criteria.** Production boot without real secrets fails
immediately with a message naming the missing/weak setting (no secret
contents); dev boot warns only; `DEBUG=true` does not bypass production
checks.

---

### F3 — Encounter/document cross-patient isolation (High)

**Status:** done (`5d4e935`), including the dedicated
`DocumentVersionCreateRequest` (preferred option) and the defense-in-depth
isolation join in `list_by_encounter`.

**Problem.** `DocumentService.create_document`
(`app/services/documents.py:103-136`) persists `data.encounter_id` without
checking that the encounter belongs to `medical_record.id`. The FK constraint
only guarantees the encounter exists. Documents uploaded for Patient A can be
attached to Patient B's encounter; `list_by_encounter`
(`app/repositories/document.py:59-65`) then exposes A's document metadata to
B's authorized viewers via `EncounterService.list_encounter_documents`
(`app/services/encounter.py:77-79`).

**Version-upload decision (review finding).**
`DocumentCreateRequest.encounter_id` (`app/schemas/document.py:20`) is shared
by both the create-document and add-version routes, but
`DocumentService.add_version` silently ignores it. **Decision: remove
`encounter_id` from the version-upload flow.** Versions must not mutate
document routing; the invariant "document's encounter belongs to its medical
record" then stays checkable in exactly one place (create). Implementation:
use a dedicated `DocumentVersionCreateRequest` (without `encounter_id`) for
the version route, or ignore-and-document explicitly — preferred is the
dedicated schema so the API contract stops advertising the field.

**Plan.**

1. In `create_document`, load the encounter when `data.encounter_id` is set
   and validate before insert:

   ```python
   if data.encounter_id is not None:
       encounter = await self._encounters.get(data.encounter_id)
       if encounter is None or encounter.medical_record_id != medical_record.id:
           raise EncounterNotFoundError("encounter does not belong to patient")
   ```

   Raising `EncounterNotFoundError` (already mapped to 404) avoids leaking
   existence of other patients' encounters.
2. **Route wiring:** the documents route catches a fixed exception tuple
   (`DocumentNotFoundError`, `DocumentQuotaExceededError`,
   `FileTooLargeError`, `UnsupportedFileTypeError` —
   `app/api/v1/documents.py:60-68`). Add `EncounterNotFoundError` to it (or
   migrate the route to the central `raise_for` pattern) so the new check
   returns `404` instead of a `500`.
3. Remove `encounter_id` from the version-upload request schema (see decision
   above); update route signature and OpenAPI-visible models accordingly.
4. Defense-in-depth (optional): make `list_by_encounter` join
   `Document.medical_record_id == encounter.medical_record_id` so legacy bad
   rows stop resolving.

**Acceptance criteria.** Uploading a document with another patient's
`encounter_id` returns 404 and writes nothing; listing documents by encounter
never returns documents whose `medical_record_id` differs from the
encounter's; version upload no longer accepts `encounter_id`.

---

### F4 — Never log OTP codes; clean up state on delivery failure (High)

**Status:** done (`64ee3af`). Dev convenience path (item 4) not
implemented — default absent per plan. Test conftest now uses a
`StubNotificationGateway`; `RabbitNotificationGateway(None)` semantically
means "broker down".

**Problem.** `RabbitNotificationGateway.send_otp`
(`app/services/notifications.py:33-41`) logs the raw code at INFO level when
the publisher is `None`. Additionally, only the `publisher is None` case is
handled — an exception raised by `publisher.publish()` propagates unhandled.

**Plan.**

1. Remove the plaintext-log fallback. When `self._publisher is None`, raise a
   new `NotificationUnavailableError` registered as `503 Service Unavailable`
   in `http_errors.py`; `/auth/request-otp` must catch it and map via
   `raise_for` (its current `except` handles only `RateLimitError`).
2. Wrap `await self._publisher.publish(...)` in try/except and raise the same
   `NotificationUnavailableError` on failure.
3. **State cleanup:** by the time delivery fails, the code is already in
   Redis (`OtpService.issue`). On delivery failure, delete the code key (and
   attempts key) before raising, so no valid code lingers for an identity
   whose owner never received it. Implementation options: catch in
   `AuthService.request_otp` around `send_otp` and call
   `self._otp_service.revoke(identity)` (new small method), or pass a cleanup
   callback into the gateway — prefer the service-level try/except to keep
   the gateway dumb.
4. If a dev convenience path is truly needed, gate it behind explicit
   `settings.debug and settings.log_otp_to_console` (default off) and log
   **without** the code (identity + expiry only). Default: absent.

**Acceptance criteria.** With broker down: request-otp returns 503, nothing
OTP-related appears in logs, and Redis holds no live code for the identity
after the failed request. Grep of logs for `\bcode=\d{6}\b` finds nothing.

---

### F7 — Strict identity validation and canonicalization (Medium)

**Status:** done (`c7771a6`). Single source of truth:
`app/domain/identity.py` (`Identity.parse`, reuses `IdentityKind`);
`detect_channel` and `AccountRepository` delegate to it; schema validators
canonicalize before any DB/Redis access. Known consequence: accounts created
with non-E.164 phones can no longer log in (data cleanup out of scope).

**Problem.** `RequestOtpRequest.identity` / `VerifyOtpRequest.identity`
(`app/schemas/auth.py:8-15`) validate length only.
`AccountRepository.get_or_create_by_identity`
(`app/repositories/account.py:34-51`) treats every non-email string as a
phone number verbatim; `OtpService` embeds the raw string into Redis keys
(`app/services/otp.py:36-46`). Arbitrary junk creates accounts and pollutes
Redis. Canonicalization gap: account lookup matches
`email OR email_normalized`, but the OTP Redis key uses the raw string —
`User@Example.com` and `user@example.com` share an account yet get separate
OTP/rate-limit keys, and the notification receives non-canonical text.

**Plan.**

1. Create `app/domain/identity.py` with a canonicalization function and two
   strict patterns:
   - email: `^[^@\s]+@[^@\s]+\.[^@\s]+$` → canonical form lowercase+stripped;
   - phone: E.164 `^\+[1-9]\d{7,14}$` → canonical form as-is.
   Return a small value object (`Identity(kind, canonical)`) or raise
   `ValueError`.
2. Apply it in `RequestOtpRequest` / `VerifyOtpRequest` via a Pydantic
   validator (422 on invalid input, before touching DB/Redis).
3. Use the canonical value everywhere downstream: account lookup, account
   creation (`email_normalized`, `phone_e164`), Redis keys, and notification
   identity. Replace the implicit "else it's a phone" branches in
   `AccountRepository.get_by_identity` / `get_or_create_by_identity` and
   `detect_channel` with checks against the same patterns (single source of
   truth).
4. Store phones only in E.164; reject creation otherwise.

**Acceptance criteria.** `"not-an-email"` / `"12345"` are rejected with 422
and create no account row or Redis key; `User@Example.com` and
`user@example.com` share one OTP/rate-limit key; existing valid flows
unchanged.

---

### F5 — Atomic refresh rotation + access-token session validation (Medium)

**Status:** done (`76290cf`). Plan A: `AuthSessionRepository.revoke_if_valid`
— one conditional `UPDATE..RETURNING`, event parity via
`AuthSession.record_revocation_event()`. Plan B (locked decision):
`get_current_account` loads the session by `sid` PK per request — no cache,
revocation effective immediately; missing/garbled/unknown/revoked/expired
`sid` → 401.

**Problem A — racy rotation.** `AuthService.refresh`
(`app/services/auth.py:89-106`) does get → revoke → save as separate steps.
Two concurrent requests with the same refresh token can both observe a valid
session before either commits; both rotate successfully and reuse goes
undetected.

**Problem B — stale access tokens.** Access tokens carry a `sid` claim
(`app/core/security.py:23-39`) but nothing validates it. Logout/refresh
revocation kills only the refresh session; a stolen access token works until
its 15-minute expiry.

**Plan A — make rotation atomic (repository-level).**

Add `AuthSessionRepository.revoke_if_valid(hmac) -> AuthSession | None`
implementing a single conditional statement:

```sql
UPDATE auth_sessions
SET revoked_at = now(), last_used_at = now()
WHERE refresh_token_hmac = :hmac
  AND revoked_at IS NULL
  AND expires_at > now()
RETURNING *;
```

(With SQLAlchemy: `update(...).returning(...)`; asyncpg executes it as one
atomic statement.) Exactly one concurrent caller gets the row back; the loser
gets `None` → `RefreshTokenError`. This also fixes `last_used_at` (F11) for
free. Alternative if a domain-method flow is preferred:
`SELECT ... FOR UPDATE` then revoke in the same transaction — but the
conditional UPDATE is simpler and lock-free.

**Plan B — sid validation on protected requests.**

In `get_current_account`, after decoding claims, verify `claims["sid"]` maps
to a live session:

- Load session by PK (`AuthSessionRepository.get_by_id` already exists,
  `app/repositories/auth_sessions.py:81-83`); require not revoked and not
  expired; return `401` otherwise.
- **Decision (revision 3):** no Redis cache — the per-request session lookup
  is the same cost class as the existing account fetch, and revocation takes
  effect immediately (no stale window, no invalidation logic). A short-TTL
  cache can be added later only if profiling demands it.

**Post-revocation behavior (review addition — document and test).** With
Plan B active, refreshing rotates the session, so the access token issued
before refresh becomes invalid immediately. Both transitions need tests:

- logout invalidates the still-unexpired access token;
- refresh invalidates the previous access token.

**Acceptance criteria.** Concurrent double-refresh yields exactly one success
and one 401 (integration test with two parallel tasks); revoked/unknown `sid`
→ 401; logout/refresh invalidate prior access tokens immediately (no cache).

---

### F6 — Resilient document-event consumer (Medium)

**Status:** done (`ac25958`). Full DLQ: the shared `messaging.Consumer`
declares a FANOUT `<queue>_dlx` + durable `<queue>_dlq` and passes
`x-dead-letter-exchange` on the main queue, so aio_pika's reject-without-
requeue lands failed messages in the DLQ; `run_consumer` reconnects with a
fresh `Consumer` per attempt (1s→30s backoff with jitter, reset after
sustained success), logs handler failures structurally and keeps consuming;
`main.py` awaits the cancelled consumer task. Deploy note: queues must be
recreated once at rollout (`PRECONDITION_FAILED` otherwise).

**Problem (corrected analysis).** Two distinct failure modes in
`app/consumers/document_events.py` + `packages/messaging/messaging/consumer.py`:

1. **Broker-start failure:** `run_consumer` catches, warns, and returns — the
   task spawned in `main.py:22` dies unsupervised; documents stay `pending`
   until full API restart.
2. **Handler failure:** `_handle` uses `async with message.process()`, and
   aio_pika's default is `requeue=False` (verified against installed aio_pika
   `message.py:403`) — so a handler exception **rejects/drops the message
   silently**, and because the exception propagates out of `_handle` into the
   `async for` loop, it also **kills the consumer task**. There is no infinite
   redelivery loop, but there is silent data loss plus consumer death.
3. **Instance reuse hazard:** `Consumer.start()`
   (`messaging/consumer.py:30-39`) assigns connection/channel/queue
   incrementally; after a partial failure the instance holds stale state and
   is not safely restartable.
4. **Shutdown hygiene:** `main.py:29` cancels `consumer_task` but never
   awaits it.

**Plan.**

1. Reconnect loop in `run_consumer`; instantiate a **fresh `Consumer` inside
   each attempt** (never reuse across failures); exponential backoff 1s → 30s
   cap with jitter; reset backoff after sustained success; keep
   `CancelledError` propagation.
2. Wrap `await _handle(message)` in try/except inside the loop:
   - transient errors (DB/storage/publish unavailable): log with exc_info,
     decide ack-vs-requeue by policy (see 3);
   - malformed/unsupported events already return cleanly — keep dropping them
     with a warning.
3. Dead-letter policy: bind a `document_events_dlq` queue and publish failed
   messages there (or nack without requeue after N deliveries — use the
   `x-death` header/redelivery flag) so nothing disappears without a trace.
   Minimum viable: structured error log with event type + message id before
   permanent drop; DLQ preferred.
4. `main.py` shutdown: `consumer_task.cancel()` followed by
   `await asyncio.gather(consumer_task, return_exceptions=True)`.
5. Optional: metric/log line per retry for alerting.

**Acceptance criteria.** Start stack with RabbitMQ down, then start RabbitMQ
→ consumer connects without restarting account-api and consumes messages
published during downtime; a handler exception neither crashes the consumer
nor loses the message silently (DLQ/log entry present); SIGTERM shuts down
cleanly without "Task was destroyed" warnings.

---

### F11 — Session metadata cleanup (Minor)

**Status:** code done (`76290cf`) — `touch()` deleted;
`last_used_at` == revocation time for rotated sessions. The DB_MODELS.md
documentation note lands in the Phase 8 wrap-up.

**Problem.** `AuthSession.touch()` (`app/domain/auth_session.py:78-80`) is
never called; `last_used_at` equals `created_at` forever.

**Plan.**

- [ ] F5 Plan A already updates `last_used_at` atomically during rotation.
      After that lands, delete `touch()` as dead code and document in
      `docs/data/DB_MODELS.md`: for rotated sessions `last_used_at` ==
      revocation time; for login-created sessions it equals creation.

**Acceptance criteria.** No dead code; column semantics documented.

---

## 3. Documentation updates

- [ ] `docs/security/AUTHENTICATION.md`: secret rotation invalidates all
      sessions; status-enforcement matrix (§F2/F8); sid-check behavior and
      post-revocation token lifetime (F5).
- [ ] `docs/data/DB_MODELS.md`: `email_verified_at` / `phone_verified_at` /
      `last_login_at` semantics (set on OTP login, F9); `last_used_at`
      semantics (F11).
- [ ] `docs/development/EXCEPTION_HANDLING.md`: register new exceptions
      (`AccountInactiveError`, `NotificationUnavailableError`) in examples.

## 4. Tests

Location conventions: API tests in `apps/account-api/tests/`, unit tests in
`apps/account-api/tests/unit/` (pytest, sqlite per conftest).

- [x] **auth flow** (`test_auth_flow.py`):
  - BLOCKED account → protected endpoint 401; OTP login 403; refresh 401
    (F2/F8);
  - PENDING account → login ok, becomes ACTIVE exactly once (F2);
  - email OTP login sets `email_verified_at`; phone OTP sets
    `phone_verified_at`; `last_login_at` updates (F9);
  - rollback: forced session-creation failure leaves verification timestamps
    unset (F9);
  - invalid identities → 422, no account row, no Redis key (F7);
  - `User@Example.com` vs `user@example.com` share one rate-limit key (F7);
  - concurrent double-refresh → one 200, one 401 (F5-A);
  - logout/refresh invalidate prior access token (F5-B).
- [x] **documents** (`test_documents_api.py`): upload with foreign
      `encounter_id` → 404, nothing persisted; encounter listing isolation;
      version upload rejects/ignores `encounter_id` per schema change (F3).
- [x] **notifications**
      (`apps/account-api/tests/unit/test_notifications.py`): publisher
      `None` → raises `NotificationUnavailableError`; `publish()` raising →
      same error; no code in caplog; Redis code deleted after failed request
      (F4).
- [x] **config** (`apps/account-api/tests/unit/test_config.py`): production env
      without secrets / with placeholders / with short secrets → startup error
      naming setting; development → warning only; `DEBUG=true` does not bypass
      production checks (F10).
- [x] **consumer** (`apps/account-api/tests/unit/test_document_events.py`):
      broker-start failure → retries with fresh `Consumer`, recovers when
      broker returns; disconnect → backoff doubling + reset-after-success;
      handler exception → message rejected to DLQ, loop survives;
      malformed event dropped with warning; cancellation closes cleanly
      (F6).
- [x] **dependencies** (`test_auth_flow.py` + new
      `apps/account-api/tests/unit/test_auth_sessions_repository.py`):
      revoked/unknown/expired `sid` → 401; conditional-rotation guard
      semantics (winner-once, expired ignored, `last_used_at == revoked_at`)
      (F5).

Regression gate: `make test` (or `uv run pytest apps/account-api/tests`) green;
lint/typecheck clean.

## 5. Implementation order

1. **Account status enforcement end-to-end** — F2+F8 incl. refresh-time
   status check, `AccountInactiveError`, route + http_errors wiring.
   → done, `3062f02` (F9 included).
2. **Cross-patient isolation** — F3 encounter validation, route exception
   mapping, remove `encounter_id` from version uploads.
   → done, `5d4e935`.
3. **Identity validation & canonicalization** — F7 shared value object,
   schema validators, canonical Redis keys.
   → done, `c7771a6`.
4. **Secret startup validation** — F10 `APP_ENV`-gated, all infra
   placeholders.
   → done first (`1dc60e1`), per the footer constraint.
5. **OTP delivery hardening** — F4 fail-closed gateway, publish-failure
   handling, Redis cleanup.
   → done, `64ee3af`.
6. **Atomic rotation + session-valid access tokens** — F5 conditional-update
   repository method, then sid check (direct DB lookup), post-revocation
   tests; includes F11 cleanup.
   → done, `76290cf`.
7. **Resilient consumer** — F6 reconnect loop, in-loop error policy, DLQ,
   awaited shutdown.
   → done, `ac25958`.
8. **Wrap-up** — docs updates (§3), credential rotation checklist execution
   (F1 ops), full regression run.
   → pending.

Each phase is independently shippable; run lint/typecheck/tests after each.
Executed order so far: 4 → 1 → 3 → 2 → 5 → 6 → 7 (footer constraints honored:
F10 before everything; F5 after F2).

## 6. Out of scope

- Git history rewrite (verified unnecessary — `.env` never committed).
- Migration files (all fixes are code-level; no schema changes required).
- Notification-worker internals beyond the gateway contract.
- Proof that rotated credentials are dead (operational, outside repo tests).


Implement F10 early enough that tests and local configuration cannot accidentally use weak secrets.
Implement F5 session validation only after F2 status enforcement, because session validation must reject inactive accounts consistently.