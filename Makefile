PYTHON  := uv
WEB_DIR := apps/web

.PHONY: help setup setup-web lock lint lint-web format-web test test-web test-e2e test-integration generate-api-types build-web dev-web compose-dev compose-start compose-stop compose-down compose-logs compose-ai-worker compose-ai-worker-logs migrate

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: ## Install all workspace members into one venv
	uv sync --all-packages

setup-web: ## Install frontend dependencies (apps/web)
	cd $(WEB_DIR) && npm install

lock: ## Regenerate the root uv.lock
	uv lock

lint: ## Ruff across the whole monorepo
	uvx ruff check apps packages tests

lint-web: ## ESLint for apps/web
	cd $(WEB_DIR) && npm run lint

format-web: ## Prettier for apps/web
	cd $(WEB_DIR) && npm run format

test: ## Run pytest for every Python app
	uv run --all-packages pytest apps tests

test-web: ## Run vitest for apps/web
	cd $(WEB_DIR) && npm test

test-e2e: ## Playwright E2E against the running dev stack (compose-dev + backend on :8000)
	cd $(WEB_DIR) && npx playwright install chromium && npx playwright test

migrate: ## Apply DB migrations (local dev)
	uv run --all-packages alembic -c alembic.ini upgrade head

generate-api-types: ## Regenerate TS API types from live OpenAPI (needs backend on :8000)
	cd $(WEB_DIR) && npm run generate:api

test-integration: ## Integration tests against local dev infra (docker compose)
	uv run --all-packages pytest tests/integration -m integration

build-web: ## Build the React SPA
	cd $(WEB_DIR) && npm run build

dev-web: ## Run the Vite dev server (proxies /api to account-api:8000)
	cd $(WEB_DIR) && npm run dev

compose-dev: ## Build & start dev stack: postgres, rabbitmq, redis, account-api, workers
	docker compose -f infrastructure/development/docker-compose.yml up -d --build

compose-start: ## Start dev stack from existing images (no build)
	docker compose -f infrastructure/development/docker-compose.yml up -d

compose-stop: ## Stop dev stack (+ ai-worker), keeping containers (restart with compose-start)
	docker compose -f infrastructure/development/docker-compose.yml --profile ai-worker stop

compose-logs: ## Tail dev stack logs; SVC=<service> to filter one
	docker compose -f infrastructure/development/docker-compose.yml logs -f $(SVC)

compose-ai-worker: ## Build & start the ai-worker (opt-in containerized dev mode)
	docker compose -f infrastructure/development/docker-compose.yml --profile ai-worker up -d --build

compose-ai-worker-logs: ## Tail ai-worker logs
	$(MAKE) compose-logs SVC=ai-worker --no-print-directory

compose-down: ## Stop and remove dev infra (+ ai-worker)
	docker compose -f infrastructure/development/docker-compose.yml --profile ai-worker down
