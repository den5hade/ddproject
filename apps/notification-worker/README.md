# notification-worker

Async worker that consumes delivery events from RabbitMQ and sends them to
users via a pluggable provider (email / console). It handles two event types:

- **OTP login codes** — `AuthOtpRequested` (`auth.otp.requested`), published by
  **account-api**.
- **Document notifications** — `NotificationRequested`
  (`notification.requested`), published by **account-api** when an
  organization-sourced document finishes processing or fails (Phase 4f).

This keeps credential and document-notification delivery outside the API
request path. After a `NotificationRequested` delivery attempt the worker
reports the outcome back on `notification.delivered` (`NotificationDelivered`)
so account-api can move the row to SENT/FAILED.

## How it works

```
 account-api ──► RabbitMQ pdf.events ──► queue "auth_otp" ──► notification-worker
  (publisher)     exchange=topic                 │              │
                 routing=auth.otp.requested      ▼              │
                 routing=notification.requested Consumer       │
                                            (aio-pika)         │
                                            ┌────────────────┐  │
                                            │ validate event │  │
                                            │ pick provider  │  ▼
                                            │ send/send_message ► SMTP (email)
                                            └────────────────┘    or console log
                                                       │
                                    NotificationDelivered (notification.delivered)
                                                       ▼
                                                account-api
                                          (notification_result consumer)
```

- **Consumption**: `Consumer` (from the `pdf-messaging` package) declares a
  **durable queue** bound to the topic exchange; `prefetch_count=10`; messages
  are acked only after successful handling (`message.process()`).
- **Validation**: the body is parsed into the `AuthOtpRequested` /
  `NotificationRequested` Pydantic contract, dispatched on `message.type`;
  malformed events are logged and dropped (ack'ed) without delivery.
- **Delivery**: chosen by `NOTIFICATION_PROVIDER` (see below). A failed
  `NotificationRequested` delivery is still ack'ed (no infinite requeue) and
  reported back as `status="failed"` with the error message.
- **Result reporting**: the worker publishes `NotificationDelivered` on
  `notification.delivered` after each document-notification attempt (best
  effort — a broker hiccup drops the result, the row stays PENDING).

## Message contract

`packages/contracts/contracts/events/auth_otp_requested.py`:

| Field | Type | Meaning |
| --- | --- | --- |
| `request_id` | UUID | Correlation id of the request |
| `identity` | str | Email address or phone number to deliver to |
| `channel` | `"email" \| "phone"` | Delivery channel |
| `code` | str | 6-digit one-time code |
| `expires_at` | datetime (UTC) | When the code stops being valid |

`packages/contracts/contracts/events/notification_requested.py`:

| Field | Type | Meaning |
| --- | --- | --- |
| `notification_id` | UUID | Row id in `notifications` (account-api) |
| `account_id` | UUID | Recipient account |
| `organization_id` | UUID \| None | Source organization (if any) |
| `type` | str | `document_received` / `document_processed` / `document_processing_failed` |
| `channel` | str | `email` |
| `to` | str | Recipient address |
| `subject` / `body` | str | Rendered template — org name + secure link only, **no medical data** |
| `resource_type` / `resource_id` | str / UUID | Target resource (`document`, id) |

`packages/contracts/contracts/events/notification_delivered.py`:

| Field | Type | Meaning |
| --- | --- | --- |
| `notification_id` | UUID | Row id being reported on |
| `status` | `sent" \| "failed"` | Delivery outcome |
| `error_message` | str \| None | Present on failure |

## Providers

Provider is selected once by `NOTIFICATION_PROVIDER` in
`app/providers/__init__.py:get_provider()` (implements `send` for OTP codes and
`send_message` for document notifications):

| Provider | Env | Behavior |
| --- | --- | --- |
| `console` (default) | — | Logs the code (`otp_delivery to=... channel=... code=...`) or the message (`notification_delivery to=... channel=... subject=...`). Dev/test only. |
| `smtp` | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_TLS` | Sends an email via StartTLS; SMTP I/O runs in a thread (`asyncio.to_thread`) so the loop stays responsive. Own channel is `email`; a `phone` event raises. `send` and `send_message` share the same delivery path. |

To add a provider: implement the `NotificationProvider` protocol in
`app/providers/base.py`, add a `build_provider()` factory, and branch on it in
`get_provider()`.

## Configuration

All settings from environment / `.env` (`app/config.py`):

| Env var | Default | Purpose |
| --- | --- | --- |
| `RABBITMQ_URL` | `""` | Full AMQP DSN; wins over the parts below |
| `RABBITMQ_HOST` | `localhost` | Broker host (used when `RABBITMQ_URL` empty) |
| `RABBITMQ_PORT` | `5672` | Broker port |
| `RABBITMQ_USER` / `RABBITMQ_PASSWORD` | `""` | Credentials |
| `RABBITMQ_VHOST` | `/` | Virtual host |
| `NOTIFICATION_QUEUE` | `auth_otp` | Durable queue name |
| `NOTIFICATION_ROUTING_KEYS` | `auth.otp.requested,notification.requested` | Comma-separated routing keys to bind |
| `NOTIFICATION_PROVIDER` | `console` | `console` or `smtp` |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | — | SMTP server |
| `SMTP_FROM` | `no-reply@ddproject.local` | Sender address |
| `SMTP_USE_TLS` | `true` | StartTLS on connect |

## Run

```bash
# Local (from repo root; the shared packages are part of the uv workspace)
RABBITMQ_URL=amqp://pdf:pdf123@localhost:5672/ uv run --project apps/notification-worker python -m app.main

# Docker (build context is the monorepo root)
docker build -f apps/notification-worker/Dockerfile -t pdf-ai-platform/notification-worker .
```

In production the worker is defined in `infrastructure/main-vps/docker-compose.yml`
and takes its configuration from the shared `.env` (RabbitMQ on a separate VPS
is addressed via the overlay network DSN).

## Tests

```bash
PYTHONPATH=apps/notification-worker .venv/bin/python -m pytest apps/notification-worker/tests -q
```

## Layout

```text
app/
  main.py           aio-pika consume loop + event dispatch
  config.py         pydantic-settings configuration
  providers/
    base.py         NotificationProvider protocol
    console.py      log-based delivery (default)
    smtp.py         SMTP email delivery
tests/
```