# Build from the repo root:
#   docker build -f apps/ai-worker/Dockerfile -t pdf-ai-platform/ai-worker .

FROM ghcr.io/astral-sh/uv:0.8.6-python3.12-bookworm-slim AS uv

FROM python:3.12-slim
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1

COPY --from=uv /usr/local/bin/uv /usr/local/bin/uv

COPY . .

RUN uv sync --project apps/ai-worker --no-dev --no-install-project

WORKDIR /app/apps/ai-worker
CMD ["uv", "run", "--no-project", "python", "app/main.py"]