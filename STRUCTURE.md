# STRUCTURE.md

This describes the monorepo layout, the build/dependency model, and how every
deployment piece fits together.

## 1. Physical architecture

```text
                    GitHub
                       │
                 Container Registry
                       │
       ┌───────────────┴───────────────┐
       │                               │
       ▼                               ▼
  Main VPS                        GPU VPS
   (24/7)                       (ON/OFF, stateless)
       │                               │
 ┌─────┴──────────────┐                │
 │ nginx (web + rev)  │                │
 │ account-api        │                │
 │ marker-orchestrator│                │
 │ ai-worker          │                │
 │ RabbitMQ ──────────┼─ Tailscale ────┤
 │ PostgreSQL         │                │
 │ Qdrant             │                │
 └─────┬──────────────┘                │
       │                               │
       ▼                               ▼
      S3 ◄────────────────────────────────
```

Three machines, one private overlay network (Tailscale or WireGuard):

| Host      | Runs                                                    | Availability |
|-----------|---------------------------------------------------------|--------------|
| Main VPS  | web SPA, account-api, orchestrator, ai-worker, postgres, qdrant | 24/7    |
| Rabbit VPS| RabbitMQ (broker only, listens on the tailnet interface) | 24/7         |
| GPU VPS   | marker-worker (Marker + CUDA), pulls image from registry | ON/OFF, ephemeral |

Why a dedicated RabbitMQ host: the Main VPS is already loaded; separating the
broker lets Rabbit fail/scale independently. All machines join the overlay
network, so RabbitMQ is **never exposed on a public port** and the ephemeral
GPU node's changing public IP does not matter.

---

## 2. Git & dependency model

- **One git repository** for the whole monorepo — services share code, commits
  are atomic (a contract change can land together with its consumers), and CI
  triggers are path-scoped.
- **uv workspace**: the root `pyproject.toml` is a *virtual* workspace root
  (no package of its own). Each item under `apps/*` (Python) and `packages/*`
  is a workspace member with its own `pyproject.toml`. **One shared `uv.lock`**
  at the root pins identical versions everywhere.
- `apps/web` is **not** a uv member (Node/TypeScript project with its own
  `package.json`).
- Shared packages are real packages (`pdf-contracts`, `pdf-messaging`,
  `pdf-storage`, `pdf-observability`) built in-memory by uv; apps declare them
  by name in their `dependencies`, tagged `[tool.uv] package = false` because
  they are not meant to be published.

Useful commands (from the root):

```bash
uv sync --all-packages                       # one venv with every member
uv run --project apps/account-api pytest     # run one app
uv lock                                      # re-lock
uvx ruff check apps packages tests           # lint everything
```

---

## 3. Service responsibilities

### apps/account-api (FastAPI) — Main VPS
Registration/auth, user cabinet, document metadata, job state, and presigned
S3 uploads. Talks to PostgreSQL. Publishes `document_uploaded` events.
JWT lives in an httpOnly cookie; nginx keeps the SPA and API same-origin.

### apps/marker-worker — GPU VPS
Not a web service. `consume → process → publish`:

```text
RabbitMQ
   │  document_id + S3 key
   ▼
Marker Worker
   ├─ download PDF from S3
   ├─ convert with Marker (marker-pdf, CUDA)
   ├─ upload MD/JSON to S3
   └─ publish document_converted
```

Fully stateless: no local DB, no local files. This is what lets you power the
VPS on/off and swap GPU providers freely.

### apps/marker-orchestrator — Main VPS
Permanent service that decides **when the GPU node must exist**:
- monitors RabbitMQ queue depth
- tracks the worker's heartbeat
- calls the provider API (`provider/provider.py`) to start/stop the GPU VPS

Scaling policy lives in `scaling/policy.py`, decision state in `state/repository.py`.

### apps/ai-worker — Main VPS
Consumes `document_converted`, downloads the markdown, extracts fields per
schema with an LLM (`pipeline/extraction.py`), validates, chunks, embeds and
stores vectors in Qdrant. Publishes `document_analysis_requested` /
`document_completed` events.

### apps/web — Main VPS (built assets)
React + Vite SPA. Talks only to `/api/*`, proxied by nginx to account-api
(same origin → no CORS). PDFs upload **directly to S3 via presigned URLs**;
large files never pass through the servers.

---

## 4. Shared packages (packages/)

| Package            | Purpose                                              | Key deps      |
|--------------------|-------------------------------------------------------|---------------|
| `pdf-contracts`    | Event contracts + schemas shared across services      | pydantic      |
| `pdf-messaging`    | RabbitMQ wrappers: declare queues, publish, consume, retry | aio-pika  |
| `pdf-storage`      | S3 download/upload/presigned URLs                     | boto3         |
| `pdf-observability`| structlog config + Prometheus metrics helpers         | structlog, prometheus-client |

Event flow between services:

```text
account-api ──document_uploaded──▶ marker-worker ──document_converted──▶ ai-worker ──document_analysis_requested──▶ (llm)
                                                ◀──── document_conversion_requested ──── (orchestrator)
```

---

## 5. Deployment

### infrastructure/development
Local stack: PostgreSQL, RabbitMQ, MinIO (S3), Qdrant.
`make compose-dev` brings it up for running services locally.

### infrastructure/main-vps
`docker-compose.yml`: nginx, account-api, marker-orchestrator, ai-worker,
postgres, qdrant. Python images build from the **repo root** so they can
`COPY packages/`. The web assets are published to a `web-dist` volume served
by nginx. `.env.example` documents every variable; `RABBITMQ_URL` points at
the rabbit-vps tailnet IP.

### infrastructure/rabbitmq-vps
`docker-compose.yml`: RabbitMQ with management. Bind ports to the **tailnet
interface IP** in production; keep 15672 inside the mesh. `.env.example` has
the credentials.

### infrastructure/marker-vps
- `docker-compose.yml`: only `marker-worker` (with NVIDIA device reservation).
- `systemd/marker-worker.service`: oneshot unit to start/stop the node.
- `scripts/startup.sh`: boot sequence — docker login, tailscale join, pull
  image, compose up. `scripts/shutdown.sh`: compose down (callable by the
  orchestrator to save money).

GPU VPS needs **no repo access at all** — it only pulls
`registry/…/marker-worker:tag`.

### CI/CD (`.github/workflows/`)
- `test.yml` — uv pytest for Python + `npm run build` for web.
- `build.yml` — every Python app + web → container registry.
- `deploy-main.yml` — on changes to main services/web/infra, pulls & restarts
  on Main VPS via SSH.
- `deploy-marker.yml` — rebuilds just the GPU image on `apps/marker-worker/**`
  or `packages/**` changes.

---

## 6. Directory map

```text
pdf-ai-platform/
├── .github/workflows/       # test, build, deploy-main, deploy-marker
├── apps/
│   ├── account-api/         # FastAPI (uv member)
│   ├── marker-worker/       # GPU worker (uv member)
│   ├── marker-orchestrator/ # scaling decision service (uv member)
│   ├── ai-worker/           # LLM extraction + embeddings (uv member)
│   └── web/                 # React + Vite SPA (Node, NOT a uv member)
├── packages/
│   ├── contracts/           # pdf-contracts
│   ├── messaging/           # pdf-messaging
│   ├── storage/             # pdf-storage
│   └── observability/       # pdf-observability
├── infrastructure/
│   ├── development/         # local stack (postgres, rabbitmq, minio, qdrant)
│   ├── main-vps/            # prod compose + nginx conf + env
│   ├── rabbitmq-vps/        # rabbitmq-only compose + env
│   └── marker-vps/          # gpu compose + systemd + startup/shutdown
├── migrations/alembic/      # DB migrations (account-api)
├── tests/integration/       # cross-service tests
├── Makefile                 # setup / lock / lint / test / web / compose helpers
├── pyproject.toml           # uv workspace root (virtual)
├── uv.lock                  # single dependency lockfile
└── .env.example             # shared env reference
```