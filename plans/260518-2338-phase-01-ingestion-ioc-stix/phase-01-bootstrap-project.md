---
phase: 1
title: "Bootstrap project, pyproject, docker stack"
status: pending
priority: P1
effort: "4d"
dependencies: []
file_ownership:
  create:
    - pyproject.toml
    - uv.lock
    - .python-version
    - Makefile
    - docker/docker-compose.yml
    - docker/Dockerfile.app
    - docker/Dockerfile.worker
    - docker/.dockerignore
    - app/__init__.py
    - app/__main__.py
    - tests/__init__.py
    - tests/conftest.py
    - .github/workflows/ci.yml
    - .pre-commit-config.yaml
---

# Phase 01 — Bootstrap project, pyproject, docker stack

## Overview

Stand up the Python 3.11+ project skeleton with locked dependencies, dev tooling (ruff, mypy, bandit, pytest), Docker Compose stack for local development (Postgres + Redis + MinIO), and CI on GitHub Actions. Zero application logic yet — only the foundation that every later phase builds on.

## Requirements

### Functional
- `uv sync` produces a working `.venv` reproducibly from `uv.lock`
- `docker compose up -d` brings up Postgres 16, Redis 7, MinIO; all healthy
- `make test` runs pytest (zero tests is OK; framework wired)
- `make lint` runs ruff check
- `make types` runs mypy --strict
- `make security` runs bandit + pip-audit
- GitHub Actions runs lint + types + security on every PR + main push

### Non-functional
- All deps pinned by minor version in `pyproject.toml`; lock file in repo
- `mypy --strict` clean (zero `Any` escapes in baseline)
- Docker images < 500 MB (slim base; no torch/transformers in Phase 1)
- CI run < 5 min for empty test suite

## Architecture

```
project root
├── pyproject.toml          # PEP 621 metadata + ruff/mypy/pytest config
├── uv.lock                 # locked dep tree
├── .python-version         # 3.11.x pin
├── Makefile                # dev / test / lint / types / security / migrate
├── docker/
│   ├── docker-compose.yml  # postgres, redis, minio (no opencti yet)
│   ├── Dockerfile.app      # FastAPI service image
│   ├── Dockerfile.worker   # RQ worker image (same base, different CMD)
│   └── .dockerignore
├── app/
│   ├── __init__.py         # version, package marker
│   └── __main__.py         # `python -m app` entrypoint (placeholder)
├── tests/
│   ├── __init__.py
│   └── conftest.py         # async loop, dotenv, fixture roots
└── .github/workflows/
    └── ci.yml              # lint + types + security + tests
```

### pyproject.toml (Phase 1 deps only)

```toml
[project]
name = "ai-cti-extractor"
version = "0.1.0"
requires-python = ">=3.11,<3.13"
dependencies = [
  "fastapi >=0.115,<0.117",
  "uvicorn[standard] >=0.32,<0.34",
  "pydantic >=2.9,<3",
  "pydantic-settings >=2.5,<3",
  "sqlalchemy[asyncio] >=2.0.35,<2.1",
  "asyncpg >=0.30,<0.31",
  "alembic >=1.14,<2",
  "redis >=5.1,<6",
  "rq >=2.0,<3",
  "boto3 >=1.35,<2",
  "stix2 >=3.0.1,<4",
  "pycti >=6.4,<7",
  "pdfplumber >=0.11,<0.12",
  "pdfminer.six >=20240706",
  "trafilatura >=1.12,<2",
  "beautifulsoup4 >=4.12,<5",
  "markdown-it-py >=3.0,<4",
  "pytesseract >=0.3.13,<0.4",
  "pillow >=10.4,<12",
  "httpx >=0.27,<0.29",
  "python-multipart >=0.0.12,<0.1",
  "structlog >=24.4,<25",
  "tenacity >=9.0,<10",
]

[dependency-groups]
dev = [
  "pytest >=8.3,<9",
  "pytest-asyncio >=0.24,<0.25",
  "pytest-cov >=5.0,<7",
  "factory-boy >=3.3,<4",
  "hypothesis >=6.115,<7",
  "ruff >=0.7,<0.9",
  "mypy >=1.13,<2",
  "bandit[toml] >=1.7,<2",
  "pip-audit >=2.7,<3",
  "pre-commit >=4.0,<5",
  "types-beautifulsoup4",
  "types-pillow",
  "types-pyyaml",
]

[tool.ruff]
line-length = 120
target-version = "py311"
[tool.ruff.lint]
select = ["E","F","W","I","B","UP","S","SIM","C4","PIE","RUF"]
ignore = ["S101"]  # allow assert in tests

[tool.mypy]
python_version = "3.11"
strict = true
plugins = ["pydantic.mypy"]
mypy_path = "app"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "-x --strict-markers --cov=app --cov-report=term-missing --cov-report=xml"

[tool.bandit]
exclude_dirs = ["tests", ".venv"]
```

### Docker compose (Phase 1)

Services: `postgres:16-alpine`, `redis:7-alpine`, `minio/minio:latest`. Volumes for data persistence. Healthchecks. Network `cti-net`. No app/worker images in this compose — those are Phase 7. OpenCTI compose is **separate file** (Phase 8) to keep dev cycle fast.

### Makefile targets

| Target | Action |
|---|---|
| `install` | `uv sync` |
| `dev` | `uvicorn app.api.main:app --reload --port 8000` (placeholder until Phase 7) |
| `test` | `pytest` |
| `lint` | `ruff check app tests` |
| `lint-fix` | `ruff check --fix app tests` |
| `format` | `ruff format app tests` |
| `types` | `mypy app` |
| `security` | `bandit -r app && pip-audit` |
| `up` | `docker compose -f docker/docker-compose.yml up -d` |
| `down` | `docker compose -f docker/docker-compose.yml down` |
| `migrate` | `alembic upgrade head` (Phase 2 wires it) |
| `clean` | rm caches, `__pycache__`, .pytest_cache, .mypy_cache |

### CI workflow (`.github/workflows/ci.yml`)

```yaml
name: CI
on: [push, pull_request]
jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --frozen
      - run: uv run ruff check app tests
      - run: uv run ruff format --check app tests
      - run: uv run mypy app
      - run: uv run bandit -r app
      - run: uv run pip-audit
      - run: uv run pytest
```

## Implementation steps

1. Create `pyproject.toml` per spec above. Run `uv sync` to materialize lockfile.
2. Create `.python-version` with `3.11`.
3. Create `Makefile` with targets above; smoke `make lint` (no errors expected on empty `app/`).
4. Create `docker/docker-compose.yml` with postgres / redis / minio + healthchecks + named volumes.
5. Create `docker/Dockerfile.app` (multi-stage: builder uv-installs, runtime slim).
6. Create `docker/Dockerfile.worker` (same base, CMD `rq worker`).
7. Create `app/__init__.py` exporting `__version__`.
8. Create `app/__main__.py` placeholder that prints version.
9. Create `tests/__init__.py` + `tests/conftest.py` with: `pytest_asyncio` config, env loading from `.env.test`, fixture roots.
10. Create `.pre-commit-config.yaml`: ruff, mypy (--check), bandit. (Hooks stay project-local; do NOT enable global.)
11. Create `.github/workflows/ci.yml` per spec.
12. Run `make up` → confirm all services healthy via `docker compose ps`.
13. Run `make test` → 0 tests, exit 0.
14. Run `make lint && make types && make security` → all clean.
15. Commit: `feat(p01): bootstrap project + pyproject + docker stack`. Push.

## Success criteria

- [ ] `uv sync` reproducible, lockfile committed
- [ ] `make up` brings up postgres + redis + minio, all `(healthy)`
- [ ] `make lint`, `make types`, `make security`, `make test` all exit 0
- [ ] CI green on first push of this phase
- [ ] No app code yet — phase intentionally minimal
- [ ] Conventional commit pushed to `feat/phase-01-bootstrap`

## Risk assessment

| Risk | Mitigation |
|---|---|
| `uv` not available on runner | CI uses `astral-sh/setup-uv@v3` — published action |
| Pin conflicts (e.g., pdfplumber pulls old pdfminer) | `uv lock --upgrade` to resolve; commit lockfile |
| Docker image bloat | use `python:3.11-slim`; only install `tesseract-ocr eng` in worker image (Phase 3+ adds OCR libs anyway) |
| Mypy --strict pain on third-party untyped libs | Add per-module overrides in pyproject under `[[tool.mypy.overrides]]` for known offenders (`pdfminer.six`, `trafilatura`) |
