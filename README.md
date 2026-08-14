# pdf-ai-platform

Monorepo: user cabinet for uploading PDFs, GPU-based conversion with
[Maker](https://github.com/datalab-to/marker), AI analysis and retrieval over a
vector database.

See [STRUCTURE.md](./STRUCTURE.md) for the full layout, the RabbitMQ-on-a-separate-VPS
setup and how the web frontend fits in.

## Quickstart

Prerequisites: [uv](https://docs.astral.sh/uv/) ≥ 0.8, Docker, Node ≥ 20.

```bash
# 1. Local dev infra (Postgres, RabbitMQ, MinIO/S3, Qdrant)
make compose-dev

# 2. Python workspace (one venv, single uv.lock)
make setup

# 3. Web frontend
cd apps/web && npm install && npm run dev
```

## Layout at a glance

```text
apps/                 Python services (uv workspace members) + web SPA
  account-api         FastAPI: auth, documents, presigned S3 uploads, jobs
  marker-worker       GPU worker: RabbitMQ -> Marker -> S3 (runs on GPU VPS)
  marker-orchestrator Decides when the GPU node should run (queue depth, heartbeat)
  ai-worker           Reads converted docs, extracts to schema, embeds to Qdrant
  web                 React + Vite SPA (not a uv member)
packages/             Shared Python libraries (workspace members)
  contracts           Event contracts & schemas shared by all services
  messaging           RabbitMQ publish/consume helpers
  storage             S3 helpers (download/upload/presign)
  observability       logging (structlog) + metrics (prometheus)
infrastructure/       Docker Compose and config per VPS
tests/integration     Cross-service integration tests
```

## Working with uv

Commands run from the repo root:

```bash
uv sync --all-packages        # install everything into .venv
uv lock                       # re-resolve and pin dependencies
uv run --project apps/account-api uvicorn app.main:app --reload
uv run --project apps/ai-worker pytest
```

## CI / CD

`.github/workflows/`: `test.yml`, `build.yml` (images -> registry),
`deploy-main.yml`, `deploy-marker.yml` (GPU image). Trigger rules are
path-scoped per service.
