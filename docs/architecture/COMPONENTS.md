# Components

Per-service responsibilities and boundaries. See the individual docs in
[services/](../services/) for detail.

## account-api (FastAPI) — Main VPS

Responsibilities:

```text
Authentication (OTP, JWT, refresh rotation)
Authorization (RBAC roles/permissions)
Patients
Medical Records
Documents metadata + versions
Encounters
Access grants
Audit log
Analytics API
```

Does NOT:

```text
run Marker
process PDFs
run LLM
generate embeddings
store binary files locally
own the medical database (writes structured data via services/repositories)
```

Talk to PostgreSQL; publish `document_uploaded` events; generate presigned S3
URLs. See [ACCOUNT_API.md](../services/ACCOUNT_API.md).

## marker-worker — GPU VPS

Ephemeral, stateless converter. `consume → process → publish`:

```text
RabbitMQ
   │  document_id + S3 key
   ▼
Marker Worker
   ├─ download PDF from S3
   ├─ convert with Marker (marker-pdf, CUDA)
   ├─ validate result
   ├─ upload MD/JSON to S3
   └─ publish document_converted
```

No local DB, no local files, no knowledge of users beyond IDs. See
[MARKER_WORKER.md](../services/MARKER_WORKER.md).

## marker-orchestrator — Main VPS

Permanent service that decides **when the GPU node must exist**:

- monitors RabbitMQ queue depth
- tracks the worker heartbeat
- calls the provider API (`provider/provider.py`) to start/stop the GPU VPS

Scaling policy lives in `scaling/policy.py`, decision state in
`state/repository.py`. See [MARKER_ORCHESTRATOR.md](../services/MARKER_ORCHESTRATOR.md).

## ai-worker — Main VPS

Consumes `document_converted`, downloads the Markdown, classifies the document,
extracts fields per schema with an LLM, validates with Pydantic, chunks, embeds
and stores vectors in Qdrant. Publishes analysis events.

**Not the owner of the medical DB** — writes flow through domain services.
See [AI_WORKER.md](../services/AI_WORKER.md).

## web — Main VPS (built assets)

React + Vite SPA. Talks only to `/api/*` (proxied by nginx → same origin, no
CORS). PDFs/post images upload **through account-api** (multipart); binaries
are staged in a shared temp dir and moved to S3 by objectstorage-worker, so
large files never pass through nginx persistence layers.

## Shared packages (`packages/`)

| Package | Purpose | Key deps |
|---------|---------|----------|
| `pdf-contracts` | Event contracts + schemas shared across services | pydantic |
| `pdf-messaging` | RabbitMQ wrappers: declare queues, publish, consume, retry | aio-pika |
| `pdf-storage` | S3 download/upload/presigned URLs | boto3 |
| `pdf-observability` | structlog config + Prometheus metrics helpers | structlog, prometheus-client |

## Boundary principles

1. **PostgreSQL** — source of truth (medical/structured data).
2. **S3** — source of binary artifacts.
3. **Qdrant** — search/index layer.
4. **RabbitMQ** — transport, not a database.
5. **AI is not the source of truth** — output is validated (Pydantic + domain
   rules) before persistence.
