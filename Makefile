# AI-Assisted CTI Extractor — Makefile
#
# Common dev tasks. All commands run inside the uv-managed venv via `uv run`.
# On Windows native, run from Git Bash or WSL.

.PHONY: help install dev test test-cov lint lint-fix format types security audit \
        up down logs ps migrate clean worker eval-ioc eval-phase1

PY = python -m uv run

help: ## show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "\033[1;36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## sync deps from uv.lock
	python -m uv sync

dev: ## run FastAPI dev server (Phase 7 wires the app)
	$(PY) uvicorn app.api.main:app --reload --port 8000

worker: ## run RQ worker (Phase 7+)
	$(PY) python -m app.jobs.worker

test: ## run pytest (excludes integration_opencti)
	$(PY) pytest -m "not integration_opencti"

test-cov: ## pytest with coverage
	$(PY) pytest --cov=app --cov-report=term-missing --cov-report=xml -m "not integration_opencti"

lint: ## ruff check
	$(PY) ruff check app tests

lint-fix: ## ruff check --fix
	$(PY) ruff check --fix app tests

format: ## ruff format
	$(PY) ruff format app tests

types: ## mypy --strict
	$(PY) mypy app

security: ## bandit + pip-audit
	$(PY) bandit -r app
	$(PY) pip-audit

audit: security ## alias

up: ## docker compose up -d (Postgres + Redis + MinIO)
	docker compose -f docker/docker-compose.yml up -d

down: ## docker compose down
	docker compose -f docker/docker-compose.yml down

logs: ## tail compose logs
	docker compose -f docker/docker-compose.yml logs -f --tail=100

ps: ## compose ps
	docker compose -f docker/docker-compose.yml ps

migrate: ## alembic upgrade head (Phase 2 wires Alembic)
	$(PY) alembic upgrade head

eval-ioc: ## run IOC extractor eval (Phase 5)
	$(PY) python scripts/eval_ioc.py

eval-phase1: ## end-to-end Phase 1 acceptance demo
	bash scripts/eval-phase1.sh

clean: ## remove caches
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage coverage.xml htmlcov
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name '*.egg-info' -prune -exec rm -rf {} +
