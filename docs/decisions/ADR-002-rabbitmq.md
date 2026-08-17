# ADR-002: RabbitMQ as transport

- **Status**: Accepted
- **Date**: Proposed at project inception

## Context

Workers must be decoupled from the API; long-running conversions/extractions
cannot be synchronous HTTP.

## Decision

RabbitMQ for commands/events between services. It is a **transport, not a
database** — no business state is reconstructed from queues. Broker lives on
its own VPS, never exposed on a public port.

## Consequences

- Events carry IDs + storage keys, never file payloads (S3 carries binaries).
- Needs DLQ/retry and idempotent consumers
  (see [messaging/](../messaging/)).
- Adds operational surface: broker VPS, monitoring.

## Status note

Finalize per-queue TTL, consumer concurrency, and poison-message policy.