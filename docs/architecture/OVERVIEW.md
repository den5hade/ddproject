# System Architecture — Overview

> This is the top-level architecture document. It describes components only —
> tables, schemas and contracts live in their own docs.

## Physical topology

```text
                    Internet
                       │
                       ▼
                  nginx (web + reverse proxy)
                       │
                       ▼
              ┌────────────────────────────┐
              │         Main VPS          │
              │  (24/7, source of truth)  │
              │                           │
              │  web SPA (React)          │
              │  account-api (FastAPI)    │
              │  marker-orchestrator      │
              │  ai-worker                │
              │  PostgreSQL               │
              │  Qdrant                   │
              │  RabbitMQ (see note)      │
              └──────┬─────────────┬──────┘
                     │             │
        ┌────────────┴──────┐      │
        │   Rabbit VPS      │      │
        │  (broker only)    │      │
        └───────────────────┘      │
                     ┌─────────────┴─────────────┐
                     │        GPU VPS            │
                     │  (ephemeral, ON/OFF)      │
                     │  marker-worker (CUDA)     │
                     └──────────┬───────────────┘
                                ▼
                               S3
```

Three machines joined by one private overlay network (Tailscale/WireGuard):

| Host | Runs | Availability |
|------|------|--------------|
| Main VPS | web SPA, account-api, orchestrator, ai-worker, postgres, qdrant | 24/7 |
| Rabbit VPS | RabbitMQ (broker only, listens on the tailnet interface) | 24/7 |
| GPU VPS | marker-worker (Marker + CUDA), pulls image from registry | ON/OFF, ephemeral |

Why a dedicated RabbitMQ host: the Main VPS is already loaded; a separate broker
can fail and scale independently. RabbitMQ is **never exposed on a public port**;
the ephemeral GPU node's changing public IP does not matter on the overlay.

> Note: `STRUCTURE.md` puts RabbitMQ on its own host. The dev stack
> (`infrastructure/development`) runs everything on one machine.

## Logical components

```text
                         Internet
                            │
                            ▼
                     Account API
                            │
               ┌────────────┼────────────┐
               ▼            ▼            ▼
          PostgreSQL      S3        RabbitMQ
                                         │
                        ┌────────────────┴───────────────┐
                        ▼                                ▼
                 Marker Worker                      AI Worker
                 GPU VPS (ephemeral)                 CPU (Main VPS)
                        │                                │
                        ▼                                ▼
                       S3                    PostgreSQL  Qdrant
```

## What is always running vs. dynamic

- **Always running (Main VPS):** account-api, ai-worker, marker-orchestrator,
  PostgreSQL, Qdrant, RabbitMQ, nginx, web assets.
- **Dynamic (GPU VPS):** marker-worker — started by the orchestrator when the
  conversion queue grows past a threshold, stopped after an idle timeout.
- **Source of truth:** PostgreSQL (medical/structured data).
- **Binary files:** S3 (originals, converted Markdown/JSON).
- **Vector index:** Qdrant (embeddings/chunks — a search index, never the
  source of truth).

## Repository vs. deployment

The monorepo groups code, not deployment:

```text
Repository                 Deployment
account-api                Main VPS: account-api, ai-worker, marker-orchestrator
marker-worker              GPU VPS: marker-worker
marker-orchestrator        Rabbit VPS: RabbitMQ
ai-worker
```

**Monorepo ≠ deployment unit.** Marker is a separate service on a separate
ephemeral machine; it is not "part of Account API".
