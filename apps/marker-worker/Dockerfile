# Build from the repo root:
#   docker build -f apps/marker-worker/Dockerfile -t pdf-ai-platform/marker-worker .

FROM ghcr.io/astral-sh/uv:0.8.6-python3.12-bookworm-slim AS uv

# Production image: NVIDIA runtime-based for the CUDA GPU VPS.
FROM nvidia/cuda:12.2.2-runtime-ubuntu22.04
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1

COPY --from=uv /usr/local/bin/uv /usr/local/bin/uv

COPY . .

RUN uv sync --project apps/marker-worker --no-dev --no-install-project

WORKDIR /app/apps/marker-worker
CMD ["uv", "run", "--no-project", "python", "app/main.py"]