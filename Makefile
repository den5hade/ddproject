PYTHON  := uv
WEB_DIR := apps/web

.PHONY: help setup lock lint test test-integration build-web dev-web compose-dev compose-down compose-logs

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: ## Install all workspace members into one venv
	uv sync --all-packages

lock: ## Regenerate the root uv.lock
	uv lock

lint: ## Ruff across the whole monorepo
	uvx ruff check apps packages tests

test: ## Run pytest for every Python app
	uv run --all-packages pytest apps tests

test-integration: ## Integration tests against local dev infra (docker compose)
	uv run --all-packages pytest tests/integration -m integration

build-web: ## Build the React SPA
	cd $(WEB_DIR) && npm run build

dev-web: ## Run the Vite dev server (proxies /api to account-api:8000)
	cd $(WEB_DIR) && npm run dev

compose-dev: ## Build & start dev stack: postgres, rabbitmq, redis, account-api, workers
	docker compose -f infrastructure/development/docker-compose.yml up -d --build

compose-logs: ## Tail dev stack logs; SVC=<service> to filter one
	docker compose -f infrastructure/development/docker-compose.yml logs -f $(SVC)

compose-down: ## Stop local dev infra
	docker compose -f infrastructure/development/docker-compose.yml down
