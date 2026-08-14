# Build from the repo root:
#   docker build -f apps/marker-orchestrator/Dockerfile -t pdf-ai-platform/marker-orchestrator .

FROM ghcr.io/astral-sh/uv:0.8-python3.12 AS uv

FROM python:3.12-slim
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1

COPY --from=uv /uv /usr/local/bin/uv

COPY apps/marker-orchestrator/pyproject.toml apps/marker-orchestrator/pyproject.toml
COPY packages/ packages/
RUN uv sync --project apps/marker-orchestrator --no-dev --no-install-project

COPY apps/marker-orchestrator/app apps/marker-orchestrator/app

WORKDIR /app/apps/marker-orchestrator
CMD ["uv", "run", "--no-project", "python", "app/main.py"]