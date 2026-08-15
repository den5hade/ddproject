# Build from the repo root:
#   docker build -f apps/notification-worker/Dockerfile -t pdf-ai-platform/notification-worker .
# The build context is the monorepo root so the shared packages are available.

FROM ghcr.io/astral-sh/uv:0.8-python3.12 AS uv

FROM python:3.12-slim
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1

COPY --from=uv /uv /usr/local/bin/uv

COPY apps/notification-worker/pyproject.toml apps/notification-worker/pyproject.toml
COPY packages/ packages/
RUN uv sync --project apps/notification-worker --no-dev --no-install-project

COPY apps/notification-worker/app apps/notification-worker/app

WORKDIR /app/apps/notification-worker
CMD ["uv", "run", "--no-project", "python", "-m", "app.main"]