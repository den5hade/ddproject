# RabbitMQ

Transport for commands/events between services. RabbitMQ is a **transport, not
a database** — no business state is reconstructed from queues.

## Topology

```text
account-api ── document.uploaded ──▶ marker-worker ── document.converted ──▶ ai-worker
                                    ◀── document.conversion.requested ── (orchestrator)
```

- Topic exchange: `pdf.events`
- Routing key for auth: `auth.otp.requested`
- Document routing keys: `document.*` (see [EVENTS.md](EVENTS.md))

## Queues

```text
document.convert
document.extract
document.index
```

## Dead-letter queues (DLQ)

```text
document.convert.dlq
document.extract.dlq
document.index.dlq
```

## Retry policy

- Workers retry each message up to 3 times, then the message moves to the DLQ.
- Retries and redelivery are **idempotent**: a worker must skip work already
  completed for the given `document_version_id`.

## TTL & consumer behavior

- TTL: TODO — define per-queue message TTL if needed.
- Consumers use manual ack; unacked messages survive worker crashes.
- The broker lives on its own VPS (Rabbit VPS) and is never exposed on a
  public port (overlay network only).

## Configuration

```env
RABBITMQ_URL                # or RABBITMQ_HOST/PORT/USER/PASSWORD/VHOST
```

Broker-unreachable fallback: `pdf-messaging` publishers degrade gracefully
(e.g. the notification gateway logs the OTP instead of failing the request —
dev convenience only).
