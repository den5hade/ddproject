# Authentication & Session Flow

> Passwordless OTP login with JWT access tokens and rotating refresh tokens.
> Every flow lives under `POST /api/v1/auth/*`; protected endpoints use
> `Authorization: Bearer <access_token>`.

## How the pieces fit together

```
                ┌────────────────────────── account-api ──────────────────────────┐
 Client        │                                                                  │
 ───┐          │   POST /auth/request-otp ──────► AuthService.request_otp()       │
    │  body    │          │  ┌──────────┐   ┌───► OtpService (Redis)              │
    │  identity│          └──┤ can_req/ │   │    otp:code / otp:attempts /        │
    ├──────────►           ┌─┤  issue   │   │    otp:ratelimit (TTL 5 min)        │
    │  OTP over│           │ └──────────┘   │    └─► code stored, 6 digits        │
    │  email/  │           │  publish       │                                     │
    │  SMS     │◄──────────┼────────────────┼── AuthOtpRequested ─┐               │
    └──────────┤           │                │   routing "auth.otp.requested"      │
               │           │                │           │                         │
               │   POST /auth/verify ───────┼───────────┘  (RabbitMQ topic:       │
               │      code + identity       │       pdf.events)    ▼              │
               │   ◄───────── access_token ─┼─────────────────┐  notification-    │
               │            refresh_token   │                 │  worker (email /  │
               │   (JSON body)              │                 │  SMS provider)    │
               │                            │                 └────► delivers OTP │
               │   POST /auth/refresh ◄─────┼───── rotate refresh token           │
               │   POST /auth/logout  ◄─────┼───── revoke session                 │
               │   GET  /auth/me      ◄─────┼───── Bearer JWT, load user          │
               └────────────────────────────┴─────────────────────────────────────┘
```

## Endpoints

| Method | Path | Auth | Purpose | Success | Errors |
| --- | --- | --- | --- | --- | --- |
| `POST` | `/api/v1/auth/request-otp` | none | Request a one-time code | `202` `{"detail":"OTP sent"}` | `429` rate limit |
| `POST` | `/api/v1/auth/verify` | none | Swap OTP for tokens | `200` `TokenResponse` | `400` wrong/expired code |
| `POST` | `/api/v1/auth/refresh` | none | Rotate refresh token | `200` `TokenResponse` | `401` unknown/expired/revoked |
| `POST` | `/api/v1/auth/logout` | none | Revoke current session | `204` | `401` unknown token |
| `GET` | `/api/v1/auth/me` | Bearer | Current user profile | `200` `UserResponse` | `401` missing/invalid token |

One-time codes are identity-based: `identity` is either a valid **email** or a
**phone number**. The channel is detected from the value
(`detect_channel` in `app/services/notifications.py`).

## 1. Request OTP (`request_otp`)

1. **Rate limit** — `OtpService.can_request()` increments
   `otp:ratelimit:<identity>` in Redis. A brand-new key gets a 60 s TTL; more
   than **1 request per 60 s** raises `RateLimitError` → HTTP `429`.
2. **Account upsert** — `AccountRepository.get_or_create_by_identity()` looks up
   `accounts` by `email`/`phone` and creates the row on first login.
3. **Issuance** — `generate_otp()` produces a 6-digit, cryptographically random
   code (`secrets.randbelow`). `OtpService.issue()` stores it under
   `otp:code:<identity>` with a **5-minute TTL** and resets the attempts counter.
4. **Delivery** — `RabbitNotificationGateway.send_otp()` publishes an
   `AuthOtpRequested` event (`request_id`, `identity`, `channel`, `code`,
   `expires_at`) to the RabbitMQ topic exchange **`pdf.events`** with routing
   key **`auth.otp.requested`**. The `notification-worker` consumes that event
   and delivers the code (email via SMTP, or logs it with the `console`
   provider). If the broker is unreachable the gateway falls back to logging
   the code (dev convenience only).
5. Everything commits in one database transaction.

### Redis key inventory

| Key | TTL | Semantics |
| --- | --- | --- |
| `otp:code:<identity>` | 300 s | Current valid code |
| `otp:attempts:<identity>` | 300 s | Consecutive wrong attempts |
| `otp:ratelimit:<identity>` | 60 s | OTP request counter |

## 2. Verify OTP (`verify_otp`)

`OtpService.verify()` compares codes with **constant-time comparison**
(`hmac.compare_digest`) and enforces brute-force resistance:

- wrong code → increment `otp:attempts:<identity>`; on the **5th** wrong
  attempt the stored code is *deleted* (the code is "burned", a fresh `request-otp`
  is required);
- matches are one-time use — the code key is deleted immediately on success.

On success `AuthService.verify_otp()` establishes a session (see below) and
returns:

```json
{
  "access_token": "<JWT>",
  "refresh_token": "<opaque, 86 chars>",
  "token_type": "bearer"
}
```

## 3. Token model

### Access token (stateless JWT)

Signed with the configured `JWT_SECRET_KEY` / `JWT_ALGORITHM` (HS256), short
`JWT_ACCESS_EXPIRE_MINUTES` (default **15 min**).

```json
{
  "sub": "7f…a3",            // account UUID
  "user_type": "user",       // session snapshot (user | subscriber)
  "sid": "c2…19",            // auth session UUID
  "type": "access",          // decode rejects anything else
  "iat": "…",
  "exp": "…"
}
```

`decode_access_token()` (in `app/core/security.py`) raises `ExpiredTokenError`
or `InvalidTokenError` on failure; `get_current_account` maps both to `401`.

### Refresh token (opaque, rotating)

`secrets.token_urlsafe(64)` → 86-character opaque string. It is **never stored
in plain text**: only the **HMAC-SHA256** of the token is persisted
(`hash_refresh_token`), so a database leak cannot be replayed as live tokens.
The HMAC secret is `AUTH_HMAC_KEY`; it must be set in production.

## 4. Session lifecycle

Each successful login creates one row in `auth_sessions` via the
`AuthSession` aggregate (`app/domain/auth_session.py`):

| Field | Purpose |
| --- | --- |
| `id` | Session UUID (also embedded in the JWT as `sid`) |
| `account_id`, `user_type` | Owning account (session snapshot of the type) |
| `refresh_token_hmac` | HMAC of the refresh token, not the token itself |
| `user_agent`, `ip_address` | Detected from the request |
| `device_id`, `platform`, `app_version` | Optional, passed by the client |
| `expires_at` | `now + JWT_REFRESH_EXPIRE_DAYS` (default **30 days**) |
| `revoked_at` | Set when the session is revoked |
| `created_at`, `last_used_at` | Lifecycle bookkeeping |

A session is **valid** only while `revoked_at IS NULL AND expires_at > now`.

### Refresh rotation

`POST /auth/refresh`:

1. HMAC hash the presented refresh token and look up its session.
2. Session must exist and be valid; otherwise `401`.
3. **Revoke the current session** (`revoke()`, emits `SessionRevokedEvent`).
4. Create a **new session** for the same user, carrying over `device_id` /
   `platform` / `app_version`.
5. Return a fresh `access_token` + new `refresh_token`.

This is rotation: the old refresh token is useless after the response. Because
the HMAC lookup happens against the *old* token, a rotated token that is
reused hits a **revoked** (or missing) session → `401`, which also gives you a
reuse-detection primitive (a stolen token played twice is flagged).

### Logout

`POST /auth/logout` revokes the session bound to the presented refresh token
and emits `SessionRevokedEvent`.

### Domain events

`AuthSession` buffers `SessionCreatedEvent` / `SessionRevokedEvent`;
`_dispatch_events()` currently logs them (wiring into the event bus is a
future step). OTP delivery itself already goes through RabbitMQ.

## 5. Protected endpoint example (`/auth/me`)

`get_current_account` (in `app/dependencies/auth.py`):

1. `HTTPBearer` extracts the token — missing → `401`.
2. `decode_access_token` validates signature, expiry and `type=access` →
   failures → `401` with `WWW-Authenticate: Bearer`.
3. `AccountRepository.get_by_id(claims["sub"])` loads the account → missing → `401`.

## Error model

| Condition | HTTP | Detail |
| --- | --- | --- |
| OTP requested too often | `429` | `too many OTP requests, retry later` |
| Missing/invalid/expired code | `400` | `invalid or expired OTP code` |
| Unknown/expired/revoked refresh token | `401` | `refresh token is unknown, expired, or revoked` |
| Missing/invalid/expired access token | `401` | `missing bearer token` / `invalid access token` / `access token expired` |

## Production checklist

Required environment (see `.env.example`; none of these live in code):

- `JWT_SECRET_KEY` — **must be random & rotated from the dev default**
  (`change-me-in-production`).
- `AUTH_HMAC_KEY` — **required for refresh-token hashing**; empty default is
  insecure and only safe when generated by the app at startup expectations.
- `RABBITMQ_URL` (or `RABBITMQ_HOST/PORT/USER/PASSWORD/VHOST`) — OTP event bus.
- `REDIS_URL` — OTP storage (`redis://localhost:6379/0` default).
- `JWT_ACCESS_EXPIRE_MINUTES`, `JWT_REFRESH_EXPIRE_DAYS` — token lifetimes.

## Notes & trade-offs

- **No passwords** — OTP replaces them; security rests on the delivery channel
  + 6-digit entropy + 5-attempt burn + 60 s request throttle.
- **Refresh tokens are HMAC-only in the DB** — the plain value exists only on
  the client and is never recoverable from storage.
- **Rotation by design** — each refresh kills the previous token, bounding the
  exposed window for a stolen token.
- `AuthSession` `expires_at` uses UTC; SQLite (dev/tests) returns naive
  datetimes which are normalized to UTC in `AuthSessionRepository.from_row`.