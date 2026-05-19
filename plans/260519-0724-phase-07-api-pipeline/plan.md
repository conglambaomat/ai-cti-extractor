---
title: "Phase 07 — FastAPI service + BackgroundTasks pipeline orchestrator"
phase: 07
status: in-progress
priority: P1
effort: "1-2d"
branch: feat/phase-07-api-pipeline
base_branch: feat/phase-03-ingestion-parsers
mode: --hard
---

# Phase 07: FastAPI Service + BackgroundTasks Pipeline

## Goal

Wire all Phase 02–06 modules behind a FastAPI HTTP surface. End-to-end: client POSTs document → orchestrator parses → chunks → extracts IOCs → builds+validates STIX → persists → audits → returns 202. Then GET endpoints expose state.

## Stack constraint (Option B, locked)

- FastAPI BackgroundTasks (no Redis/RQ — `settings.JOB_QUEUE_BACKEND="background_tasks"`)
- Local filesystem storage (no MinIO — `settings.STORAGE_BACKEND="local"`)
- SQLite via aiosqlite (no Postgres yet — `sqlite+aiosqlite:///data/cti.db`)

## Reference reports

- [reports/researcher-260519-0732-GH-07-fastapi-patterns.md](reports/researcher-260519-0732-GH-07-fastapi-patterns.md)
- [reports/researcher-error-handling-middleware.md](reports/researcher-error-handling-middleware.md)
- [reports/researcher-pipeline-orchestrator.md](reports/researcher-pipeline-orchestrator.md)

## Phases

| ID | File | Title | Status |
|---|---|---|---|
| 01 | [phase-01-config-and-db-additions.md](phase-01-config-and-db-additions.md) | Config flags, DB schema additions, upsert helper | pending |
| 02 | [phase-02-storage-abstraction.md](phase-02-storage-abstraction.md) | Storage Protocol + LocalStorageBackend | pending |
| 03 | [phase-03-error-handling.md](phase-03-error-handling.md) | Problem+JSON, correlation_id middleware, exception handlers | pending |
| 04 | [phase-04-app-factory-and-di.md](phase-04-app-factory-and-di.md) | `create_app`, lifespan, dependencies | pending |
| 05 | [phase-05-routers.md](phase-05-routers.md) | health / ingest / documents / extractions / stix | pending |
| 06 | [phase-06-pipeline-orchestrator.md](phase-06-pipeline-orchestrator.md) | `process_document` orchestrator + persistence | pending |
| 07 | [phase-07-integration-tests.md](phase-07-integration-tests.md) | E2E httpx + sample MD report | pending |

Phases 01–02 are independent; 03 needs 01; 04 needs 02+03; 05 needs 04; 06 needs 01+04; 07 needs 06.

## Autonomous decisions (logged per CLAUDE.md)

- **Auth**: deferred to Phase 08. Phase 07 is internal API; no JWT/X-API-Key gate yet.
- **JSON renderer**: stdlib `JSONResponse` (no `orjson` dep — YAGNI; can swap later).
- **`aiofiles`**: add as dep (cleanest async file I/O).
- **`TRUST_PROXY_HEADERS`**: default `False` → always generate fresh correlation_id UUID. Production flips to True behind reverse proxy.
- **`AuditChainError` alert**: structlog `critical` only. No webhook in Phase 07.
- **`AbstentionRequired`**: not raised in Phase 07 (regex-only). Handler exists for safety; logs ERROR if reached.
- **Concurrency**: `MAX_CONCURRENT_PIPELINES=3` semaphore default.
- **Document status states**: `pending → processing → parsed → chunked → ioc_extracted → stix_built → complete`. Failure terminals: `failed_parse, empty, no_iocs (terminal-OK), failed_stix, audit_chain_error, failed`.

## Critical risk: EvidenceSpan PK mismatch

DB model `EvidenceSpan(UuidMixin)` uses UUID PK. Schema `Evidence.evidence_id` is deterministic `e-[0-9a-f]{16,}`. Resolution in Phase 01: add `evidence_id` column (unique, indexed) on `EvidenceSpan`. Keep UUID PK for FK consistency. Persistence keys upserts on `evidence_id`. `IocCandidate.evidence_ids` stores the `e-{hash}` strings (matches schema).

## Definition of Done

- [ ] All 7 phases checked in
- [ ] `pytest -x tests/` green (≥ 18 new tests across unit + integration)
- [ ] `mypy --strict app/api/ app/jobs/ app/storage/` clean
- [ ] `ruff check app/` clean
- [ ] `bandit -r app/api/ app/jobs/ app/storage/` no new HIGH findings
- [ ] `uvicorn app.main:app` starts; `GET /health` returns 200
- [ ] E2E test: POST sample MD → poll until `status=complete` → bundle hash deterministic
- [ ] PR opened against `main` from `feat/phase-07-api-pipeline`
- [ ] `docs/codebase-summary.md` updated
