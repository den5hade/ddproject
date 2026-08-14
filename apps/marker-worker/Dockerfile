# Build from the repo root:
#   docker build -f apps/marker-worker/Dockerfile -t pdf-ai-platform/marker-worker .

FROM ghcr.io/astral-sh/uv:0.8-python3.12 AS uv

# Production image: NVIDIA runtime-based for the CUDA GPU VPS.
FROM nvidia/cuda:12.2.2-runtime-ubuntu22.04
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1

COPY --from=uv /uv /usr/local/bin/uv

COPY apps/marker-worker/pyproject.toml apps/marker-worker/pyproject.toml
COPY packages/ packages/
RUN uv sync --project apps/marker-worker --no-dev --no-install-project

COPY apps/marker-worker/app apps/marker-worker/app

WORKDIR /app/apps/marker-worker
CMD ["uv", "run", "--no-project", "python", "app/main.py"]