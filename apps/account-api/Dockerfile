# Build from the repo root:
#   docker build -f apps/account-api/Dockerfile -t pdf-ai-platform/account-api .
# The build context is the monorepo root so the shared packages are available.

FROM ghcr.io/astral-sh/uv:0.8-python3.12 AS uv

FROM python:3.12-slim
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1

COPY --from=uv /uv /usr/local/bin/uv

COPY apps/account-api/pyproject.toml apps/account-api/pyproject.toml
COPY packages/ packages/
RUN uv sync --project apps/account-api --no-dev --no-install-project

COPY apps/account-api/app apps/account-api/app

WORKDIR /app/apps/account-api
EXPOSE 8000
CMD ["uv", "run", "--no-project", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]