# Development Setup

Environment and workspace orientation for contributors.

## Workspace model

- **uv workspace**: root `pyproject.toml` is a virtual root; each item under
  `apps/*` (Python) and `packages/*` is a member with its own `pyproject.toml`.
  One shared `uv.lock` pins identical versions.
- `apps/web` is **not** a uv member (Node/TypeScript, own `package.json`).
- Shared packages (`pdf-contracts`, `pdf-messaging`, `pdf-storage`,
  `pdf-observability`) are real packages built in-memory by uv
  (`[tool.uv] package = false` — not published).

## Install

```bash
make setup            # uv sync --all-packages
make compose-dev      # Postgres, RabbitMQ, MinIO, Qdrant (docker)
```

Web:

```bash
cd apps/web && npm install
```

## Environment variables

Copy `.env.example` → `.env`. Key variables (see also
[security/AUTHENTICATION.md](../security/AUTHENTICATION.md)):

```env
JWT_SECRET_KEY        # rotate from dev default in production
AUTH_HMAC_KEY         # required for refresh-token HMAC
RABBITMQ_URL
REDIS_URL
JWT_ACCESS_EXPIRE_MINUTES
JWT_REFRESH_EXPIRE_DAYS
```

## Common commands (from repo root)

```bash
uv sync --all-packages                       # one venv, every member
uv lock                                      # re-resolve
uv run --project apps/account-api pytest     # tests for one app
uv run --project apps/account-api uvicorn app.main:app --reload
uvx ruff check apps packages tests           # lint
```

## Dev & implementation plans

The `OC_`/`OAI_` documents in this directory are the historical dev and
implementation plans. They describe *how we planned to build* things; current
status is tracked in [ROADMAP.md](../ROADMAP.md) and GitHub issues, not in
those files.