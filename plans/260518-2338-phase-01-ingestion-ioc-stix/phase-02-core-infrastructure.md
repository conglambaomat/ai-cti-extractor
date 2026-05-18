---
phase: 2
title: "Core infrastructure: config, logging, security, DB schema"
status: pending
priority: P1
effort: "3d"
dependencies: [01]
file_ownership:
  create:
    - app/core/__init__.py
    - app/core/config.py
    - app/core/logging.py
    - app/core/security.py
    - app/core/exceptions.py
    - app/core/redaction.py
    - app/db/__init__.py
    - app/db/session.py
    - app/db/models/__init__.py
    - app/db/models/base.py
    - app/db/models/document.py
    - app/db/models/chunk.py
    - app/db/models/evidence.py
    - app/db/models/ioc_candidate.py
    - app/db/models/stix_object.py
    - app/db/models/audit_log.py
    - app/db/models/model_run.py
    - app/db/repositories/__init__.py
    - app/db/repositories/document.py
    - app/db/repositories/chunk.py
    - app/db/repositories/audit.py
    - app/db/migrations/env.py
    - app/db/migrations/alembic.ini
    - app/db/migrations/versions/001_initial.py
    - tests/unit/core/test_config.py
    - tests/unit/core/test_redaction.py
    - tests/unit/db/test_models.py
---

# Phase 02 — Core infrastructure

## Overview

Build the foundation every other module sits on: typed configuration via Pydantic Settings, structured logging with correlation IDs, redaction utilities for safe LLM context (Phase 3 dependency), domain exception hierarchy, async SQLAlchemy 2.0 session management, the Phase 1 DB schema with Alembic migration baseline, and audit log hash chain.

## Requirements

### Functional
- `Settings()` loads from `.env` + env vars; missing required values fail fast with clear error
- Logger emits structured JSON in production, pretty in dev (`APP_ENV=development`)
- Correlation ID flows through every request + pipeline step
- `redact_for_external_llm(text)` strips emails, IPv4/v6, common API key formats
- `AuditLog` rows form a hash chain: `row.hash = sha256(prev.hash + payload_canonical_json)`
- Alembic baseline creates all Phase 1 tables; `alembic upgrade head` idempotent

### Non-functional
- Settings is a singleton; instantiated at module import, never re-read mid-request
- All async DB access via context manager (`async with get_session()`)
- No `print` statements
- No bare `except:`
- Type hints + mypy --strict clean
- Test coverage ≥ 90% on `app/core/`

## Architecture

### Config (`app/core/config.py`)
```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    APP_ENV: Literal["development","staging","production"] = "development"
    APP_NAME: str = "cti-extractor"
    LOG_LEVEL: str = "INFO"
    SECRET_KEY: SecretStr

    DATABASE_URL: PostgresDsn
    REDIS_URL: RedisDsn

    S3_ENDPOINT: HttpUrl
    S3_BUCKET: str
    S3_ACCESS_KEY: SecretStr
    S3_SECRET_KEY: SecretStr

    ALLOW_EXTERNAL_LLM: bool = False
    REDACT_BEFORE_LLM: bool = True
    ENABLE_AUDIT_LOG: bool = True

    OPENCTI_URL: HttpUrl | None = None
    OPENCTI_TOKEN: SecretStr | None = None

settings = Settings()  # singleton; importable everywhere
```

### Logging (`app/core/logging.py`)
- `structlog` with JSON renderer in prod, ConsoleRenderer in dev
- Pre-bound: `correlation_id`, `pipeline_step`, `document_id` (when present)
- Helper: `get_logger(__name__)`
- Mask SecretStr automatically; never leak via `repr`

### Exceptions (`app/core/exceptions.py`)
Hierarchy from CLAUDE.md code-standards. Phase 1 stubs:
```python
class AppError(Exception): ...
class IngestionError(AppError): ...
class UnsupportedFormatError(IngestionError): ...
class OCRFailedError(IngestionError): ...
class ExtractionError(AppError): ...
class EvidenceMissingError(ExtractionError): ...
class StixError(AppError): ...
class StixSchemaError(StixError): ...
class StixSemanticError(StixError): ...
class ExportError(AppError): ...
class OpenCTIError(ExportError): ...
```

### Redaction (`app/core/redaction.py`)
Phase 1 patterns to redact before any external LLM call:
- IPv4: `\b(?:\d{1,3}\.){3}\d{1,3}\b` → `[REDACTED_IP]`
- IPv6: full + abbreviated
- Email: RFC5322 simplified
- API keys: `sk-[A-Za-z0-9]{40,}`, `ghp_[A-Za-z0-9]{36,}`, `xoxb-[A-Za-z0-9-]+`
- Internal hostnames: `\b\w+\.internal\b`, `\b\w+\.local\b`

Returns `(redacted_text, redaction_count)`. Caller logs count; never logs raw.

### DB session (`app/db/session.py`)
- Async engine: `create_async_engine(settings.DATABASE_URL, pool_size=5, max_overflow=10)`
- Session factory: `async_sessionmaker(engine, expire_on_commit=False)`
- Context manager `get_session()` for use outside FastAPI
- FastAPI dependency `db_session()` for endpoints (Phase 7)

### Phase 1 schema (Alembic migration `001_initial.py`)

| Table | Phase 1 columns |
|---|---|
| `documents` | id (uuid pk), source_uri (text), sha256 (char64 unique), title (text), language (char8), ingested_at (timestamptz), status (varchar32), mime_type (text) |
| `document_sources` | id, document_id (fk), type (varchar16), raw_uri (text), raw_hash (char64), fetched_at |
| `chunks` | id, document_id (fk), section (text), page (int), text (text), char_start (int), char_end (int), token_count (int) |
| `evidence_spans` | id, chunk_id (fk), char_start (int), char_end (int), text_span (text) |
| `ioc_candidates` | id, document_id (fk), type (varchar32), value (text), normalized (text), evidence_ids (uuid[] gin), confidence (numeric), extractor (varchar64), extracted_at |
| `stix_objects` | id, type (varchar32), stix_id (varchar64 unique), document_id (fk), json (jsonb), hash (char64), version (int), created_at |
| `stix_relationships` | id, source_ref (varchar64), target_ref (varchar64), relationship_type (varchar64), document_id (fk), json (jsonb) |
| `model_runs` | id, document_id (fk), model (varchar64), version (varchar32), prompt_hash (char64), input_hash (char64), output_hash (char64), started_at, ended_at, cost_usd (numeric) |
| `audit_logs` | id (bigserial), prev_hash (char64), hash (char64), actor (varchar128), action (varchar64), target_type (varchar32), target_id (uuid), payload (jsonb), created_at (timestamptz) |
| `exports` | id, target_system (varchar32), bundle_hash (char64), response (jsonb), exported_at, exported_by (varchar128), status (varchar16) |

Indexes: `chunks(document_id)`, `evidence_spans(chunk_id)`, `ioc_candidates(document_id, type)`, `stix_objects(stix_id)`, `audit_logs(target_type, target_id)`, `audit_logs(created_at)`.

### Audit hash chain
On `AuditLog` insert, fetch latest row's `hash` (or zero-hash if first), compute new `hash = sha256(prev_hash + canonical_json(payload))`. Implement as repository method `audit_repo.append(actor, action, target_type, target_id, payload)` with row-level lock to prevent races. Verify chain on startup with `audit_repo.verify_chain()`.

## Implementation steps

1. Create `app/core/{config,logging,security,exceptions,redaction}.py`. Settings with all Phase 1+2 fields.
2. Write `tests/unit/core/test_config.py`: settings load, missing required fields raise, env override works.
3. Write `tests/unit/core/test_redaction.py`: each redaction pattern hit + miss; idempotent (redact twice = same).
4. Create `app/db/session.py`: async engine, sessionmaker, context manager.
5. Create `app/db/models/base.py`: declarative `Base`, common columns (`id` UUID default, timestamps).
6. Create one model file per table per ownership list. Type hints, relationships, indexes.
7. Init Alembic in `app/db/migrations/`. `alembic.ini` points to env var.
8. Generate baseline: `alembic revision --autogenerate -m "initial"` → review, hand-edit if needed (set table names, ordered creation).
9. `alembic upgrade head` against local Postgres. Verify all tables + indexes.
10. Create `app/db/repositories/{document,chunk,audit}.py`. Repository pattern: methods like `get_by_id`, `create`, `list_by_document`. No raw SQL outside repos.
11. Implement `audit_repo.append()` with hash chain logic + row lock (`SELECT ... FOR UPDATE`).
12. Write `tests/unit/db/test_models.py`: insert documents, chunks, evidence; verify FK cascades; verify hash chain integrity over 5 sequential appends.
13. `make migrate && make test && make lint && make types && make security` all green.
14. Commit: `feat(p02): core config, logging, db schema, audit hash chain`. Push.

## Success criteria

- [ ] `from app.core.config import settings` works in REPL with `.env`
- [ ] `Settings()` raises with clear message when `DATABASE_URL` missing
- [ ] `redact_for_external_llm("hit me at admin@evil.com IP 1.2.3.4")` returns `(redacted, 2)` with both replaced
- [ ] `alembic upgrade head` creates 10 tables; `alembic downgrade base` cleanly reverses
- [ ] `audit_repo.append(...)` × 5 forms valid hash chain; `verify_chain()` returns True; tampering detected
- [ ] Coverage ≥ 90% on `app/core/`, ≥ 70% on `app/db/`
- [ ] mypy --strict, ruff, bandit all clean

## Risk assessment

| Risk | Mitigation |
|---|---|
| Audit chain race condition under concurrency | Row lock (`SELECT ... FOR UPDATE`) on latest audit row before insert; integration test spawns 10 concurrent appends, asserts chain intact |
| Pydantic v2 SecretStr leaking via repr | Custom `__repr__` test; structlog renders SecretStr as `***` |
| Alembic autogen misses index changes | Hand-review every migration; never blindly accept autogen output |
| Postgres `uuid[]` array type with SQLAlchemy 2.0 async | Use `from sqlalchemy.dialects.postgresql import ARRAY, UUID`; test in unit |
| Redaction regex catastrophic backtracking on huge text | Cap input at 10 MB; benchmark in test |
