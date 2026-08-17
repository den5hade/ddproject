# Local Setup

Run the whole platform on one machine for development.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) ≥ 0.8
- Docker
- Node ≥ 20 (web)

## 1. Local dev infra

```bash
make compose-dev
```

Brings up `infrastructure/development/docker-compose.yml`:
PostgreSQL, RabbitMQ, MinIO (S3), Qdrant.

## 2. Python workspace

```bash
make setup          # uv sync --all-packages (one venv, single uv.lock)
```

Useful commands:

```bash
uv lock                                      # re-resolve dependencies
uv run --project apps/account-api pytest     # run one app's tests
uvx ruff check apps packages tests           # lint everything
```

## 3. Web frontend

```bash
cd apps/web && npm install && npm run dev
```

## 4. Run services

```bash
uv run --project apps/account-api uvicorn app.main:app --reload
```

Notification worker (OTP delivery) comes up via the Makefile helpers.

## Environment

Copy `.env.example` → `.env` (repo root) and set at minimum:

```env
JWT_SECRET_KEY
AUTH_HMAC_KEY
RABBITMQ_URL
REDIS_URL
```

Full reference in `.env.example`. Dev defaults must be overridden in
production (see [PRODUCTION.md](PRODUCTION.md)).
