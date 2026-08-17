# Auth API

Passwordless OTP login. Full protocol detail (Redis keys, token model, session
rotation) is in [security/AUTHENTICATION.md](../security/AUTHENTICATION.md).
Machine-readable schemas: `/openapi.json`.

## Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `POST` | `/api/v1/auth/request-otp` | none | Send OTP to email/phone |
| `POST` | `/api/v1/auth/verify` | none | Swap OTP for access + refresh tokens |
| `POST` | `/api/v1/auth/refresh` | none | Rotate refresh token |
| `POST` | `/api/v1/auth/logout` | none | Revoke current session |
| `GET` | `/api/v1/auth/me` | Bearer | Current account profile |

## Behavior

- `identity` is a valid **email** or **phone**; the delivery channel is
  detected from the value.
- Rate limit: max 1 request per 60 s → `429`.
- Code TTL 5 min; 5 consecutive wrong attempts burn the code.
- Refresh rotation: each refresh revokes the previous session (reuse detection).
- Refresh tokens are stored in the DB **only as HMAC-SHA256**, never plain.

## Error model

| Condition | HTTP |
|-----------|------|
| OTP requested too often | `429` |
| Invalid/expired code | `400` |
| Unknown/expired/revoked refresh token | `401` |
| Missing/invalid/expired access token | `401` |
