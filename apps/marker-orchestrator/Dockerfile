# Build from the repo root:
#   docker build -f apps/marker-orchestrator/Dockerfile -t pdf-ai-platform/marker-orchestrator .

FROM ghcr.io/astral-sh/uv:0.8.6-python3.12-bookworm-slim AS uv

FROM python:3.12-slim
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1

COPY --from=uv /usr/local/bin/uv /usr/local/bin/uv

COPY . .

RUN uv sync --project apps/marker-orchestrator --no-dev --no-install-project

WORKDIR /app/apps/marker-orchestrator
CMD ["uv", "run", "--no-project", "python", "app/main.py"]