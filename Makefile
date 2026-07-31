.PHONY: up down logs seed test test-unit test-integration lint build clean

up: ## Start the full stack (Postgres, Redis, MinIO, API, worker, frontend)
	docker compose up --build -d
	@echo "Dashboard:  http://localhost:8080"
	@echo "API docs:   http://localhost:8000/docs"

down: ## Stop and remove all containers
	docker compose down

logs: ## Tail logs from all services
	docker compose logs -f

seed: ## Create a demo organization/project/API key for local exploration
	docker compose exec api python -m agenteval_api.seed

test-unit: ## Run core unit tests (no external services required)
	cd backend && PYTHONPATH=. python -m pytest tests/unit -v

test-integration: ## Run integration tests (requires Postgres + Redis + a running Celery worker)
	cd backend && PYTHONPATH=. python -m pytest tests/integration -v

test: test-unit test-integration ## Run the full test suite

lint: ## Run ruff + mypy on the backend, eslint + tsc on the frontend
	cd backend && ruff check . && mypy agenteval_core
	cd frontend && npm run lint && npx tsc -b

build: ## Build all Docker images without starting them
	docker compose build

clean: ## Remove containers, volumes, and local dev artifacts
	docker compose down -v
	rm -rf backend/.agenteval frontend/dist frontend/node_modules
