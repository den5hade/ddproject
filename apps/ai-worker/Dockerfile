# Build from the repo root:
#   docker build -f apps/ai-worker/Dockerfile -t pdf-ai-platform/ai-worker .

FROM ghcr.io/astral-sh/uv:0.8-python3.12 AS uv

FROM python:3.12-slim
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1

COPY --from=uv /uv /usr/local/bin/uv

COPY apps/ai-worker/pyproject.toml apps/ai-worker/pyproject.toml
COPY packages/ packages/
RUN uv sync --project apps/ai-worker --no-dev --no-install-project

COPY apps/ai-worker/app apps/ai-worker/app

WORKDIR /app/apps/ai-worker
CMD ["uv", "run", "--no-project", "python", "app/main.py"]