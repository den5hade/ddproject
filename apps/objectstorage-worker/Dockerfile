# Build from the repo root:
#   docker build -f apps/objectstorage-worker/Dockerfile -t pdf-ai-platform/objectstorage-worker .
# The build context is the monorepo root so the shared packages are available.

FROM ghcr.io/astral-sh/uv:0.8-python3.12 AS uv

FROM python:3.12-slim
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1

COPY --from=uv /uv /usr/local/bin/uv

COPY apps/objectstorage-worker/pyproject.toml apps/objectstorage-worker/pyproject.toml
COPY packages/ packages/
RUN uv sync --project apps/objectstorage-worker --no-dev --no-install-project

COPY apps/objectstorage-worker/app apps/objectstorage-worker/app

WORKDIR /app/apps/objectstorage-worker
CMD ["uv", "run", "--no-project", "python", "-m", "app.main"]