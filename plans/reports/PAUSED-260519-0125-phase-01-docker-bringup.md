# Phase 01 — PAUSED: docker stack bring-up

**Date:** 2026-05-19
**Phase:** 01 — Bootstrap project, pyproject, docker stack
**Branch:** `feat/phase-01-bootstrap-project`

## Status

**Code path: COMPLETE.** All Python tooling green.

| Gate | Status |
|---|---|
| `pyproject.toml` + `uv.lock` | ✓ committed |
| `make lint` (ruff check) | ✓ pass |
| `make format` (ruff format check) | ✓ pass |
| `make types` (mypy --strict) | ✓ pass |
| `make security` (bandit) | ✓ pass |
| `make test` (pytest) | ✓ pass (2/2 sanity tests) |
| `python -m app` smoke | ✓ pass |
| `app/`, `tests/conftest.py`, CI workflow | ✓ committed |
| `Makefile`, `.pre-commit-config.yaml` | ✓ committed |
| `Dockerfile.app`, `Dockerfile.worker` | ✓ committed (build untested) |
| `docker/docker-compose.yml` | ✓ committed (run untested) |

**Pause path: docker stack bring-up.** `docker` CLI is not installed on the host; cannot run `make up` to verify Postgres + Redis + MinIO compose stack.

## What's blocked

Phase 01 acceptance criterion *"`docker compose up -d` brings up all 3 services healthy"* cannot be verified without Docker Desktop or `docker` CLI on the host.

Phase 02 (`Phase 02: Core infrastructure`) needs Postgres reachable for Alembic migrations + integration tests.

## What I tried

1. `command -v docker` — not found.
2. Default install path `/c/Program Files/Docker/Docker/` — not present.
3. WSL Ubuntu present — could in theory run docker through WSL, but autonomous policy forbids `sudo` in deny-list (necessary for first-time docker install in WSL).

## Resolution path (human-only — chosen by you)

| Option | Effort | Trade-off |
|---|---|---|
| **Install Docker Desktop for Windows** | 5-10 min | Standard; Phase 1 stack works directly. Recommended. |
| **Install docker CLI in WSL Ubuntu + enable WSL2 integration** | 15-20 min | Avoids Docker Desktop license; needs `sudo apt install docker.io`. |
| **Skip docker, run Postgres/Redis/MinIO natively on Windows** | 30-60 min per service | High friction; not recommended. |

After installing Docker, run:
```bash
docker --version    # confirm
make up             # bring up stack
make ps             # all 3 services healthy
```

Then resume Phase 02 implementation.

## What can proceed in parallel (no Docker required)

- **Phase 04** (Intermediate CTI Pydantic schema) — pure Python, no DB needed.
- **Phase 05** (Regex IOC extractor) — pure Python.
- **Phase 06** (STIX builders + validators) — pure Python.

Phase 02 (DB), Phase 03 (ingestion partial — OCR needs container), Phase 07 (worker stack), Phase 08 (OpenCTI compose) are blocked.

## Recommendation

Proceed with **Phase 04 → 05 → 06** while Docker is being installed. Docker work resumes Phase 02 + Phase 07 + Phase 08 once available.

## Unresolved questions

1. Confirm Docker install path / approach you prefer.
2. Whether to defer Phase 01 acceptance gate sign-off until Docker present, or split Phase 01 into "code path" (done) and "infra path" (pending).
