# Pipeline Orchestrator Research — Phase 07
**Date:** 2026-05-19 | **Author:** researcher agent

---

## 1. Executive Summary

- **Idempotency key = `document.sha256` UNIQUE constraint + `IntegrityError` catch.** No separate phase-marker table needed for Phase 07; `model_runs` rows serve as phase receipts for recovery.
- **Per-phase commits, not one transaction.** SQLite file-level write lock makes long transactions a concurrency killer; per-phase commits with `document.status` as the phase cursor give partial-progress recovery at acceptable complexity.
- **Audit chain appended per phase terminal event** (success or failure), not per row insert. One audit row per phase keeps the chain short and meaningful; bulk inserts do not each need an audit row.
- **BackgroundTasks orchestrator opens its own `AsyncSession`** via `SessionFactory()` — never inherits the request session (request lifecycle is over before the task runs).
- **Zero IOCs is not a failure.** `StixBuildError` from `builders.py` IS a failure (it requires ≥1 indicator). Pipeline must short-circuit before calling `build_bundle` when IOC list is empty, emitting `status=no_iocs` and an audit row, then returning cleanly.

---

## 2. Idempotency Strategy

### Recommended: UNIQUE constraint + `IntegrityError` guard on `document.sha256`

`Document.sha256` already has `unique=True` (confirmed in `app/db/models/document.py` line 16). The orchestrator entry point does:

```python
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

stmt = sqlite_insert(Document).values(...).on_conflict_do_nothing(index_elements=["sha256"])
await session.execute(stmt)
await session.commit()
doc = await session.scalar(select(Document).where(Document.sha256 == sha256))
if doc.status not in ("pending", "failed_parse", "failed_stix"):
    # already processed successfully — skip
    return
```

This is safe for concurrent duplicate submissions: the second request hits `on_conflict_do_nothing`, reads the existing row, sees `status=processing` or `status=complete`, and exits. No double-processing.

**Phase resume logic:** check `document.status` at orchestrator entry:
- `pending` → run full pipeline
- `failed_parse` → retry from parse
- `failed_chunks` → retry from chunk
- `failed_ioc` → retry from IOC extraction
- `failed_stix` → retry from STIX build
- `no_iocs` → do not retry (valid terminal state)
- `complete` → skip (idempotent no-op)
- `processing` → another worker is running; skip (SQLite single-writer means this is safe)

**`model_runs` as phase receipts:** insert one `ModelRun` row per phase with `model="pipeline"`, `version="07"`, `input_hash=sha256_of_phase_input`. On retry, check for existing `ModelRun` with matching `input_hash` — if present and `output_hash` is not null, skip that phase. This gives fine-grained idempotency without a separate phase-marker table.

### Rejected alternatives

| Option | Why rejected |
|---|---|
| Content-addressable `document_id` (sha256 as PK) | Breaks UUID FK convention used across all models; requires migration of all FK columns |
| Explicit `pipeline_phase` enum column on `Document` | Redundant with `status` + `model_runs`; adds schema complexity for no gain |
| Redis distributed lock | Not available in Phase 07 (`JOB_QUEUE_BACKEND=background_tasks`); YAGNI |

---

## 3. Transaction Boundary Plan

**Decision: per-phase commits with `document.status` as cursor.**

SQLite uses a file-level write lock. A single transaction spanning parse → chunk → IOC → STIX would hold the write lock for the entire pipeline duration (potentially seconds for large PDFs). With `BackgroundTasks` running in-process, this blocks all other DB writes including audit log appends from concurrent requests.

### Commit points

| Phase | Commit trigger | `document.status` after commit |
|---|---|---|
| 0. Document upsert | After `on_conflict_do_nothing` + status set | `processing` |
| 1. Parse | After `ParsedDocument` produced, raw text stored | `parsed` |
| 2. Chunk | After all `Chunk` rows inserted | `chunked` |
| 3. IOC extraction | After `EvidenceSpan` + `IocCandidate` rows inserted | `ioc_extracted` |
| 4. STIX build+validate | After `StixObject` + `StixRelationship` rows inserted | `stix_built` |
| 5. Terminal | After final audit row committed | `complete` |

### Rollback semantics

Each phase runs inside its own `async with session.begin()` block (or explicit `begin()`/`commit()`/`rollback()`). On exception:
- Roll back the current phase's writes only.
- Set `document.status = failed_{phase}` in a separate minimal transaction.
- Append audit row for the failure.
- Re-raise to let the orchestrator's top-level handler log and exit.

On retry, the orchestrator reads `document.status` and resumes from the failed phase. Phases that already committed are skipped (idempotent via `model_runs` input_hash check).

### SQLite write-lock mitigation

`aiosqlite` serializes writes through a single thread anyway (WAL mode not enabled by default). Per-phase commits release the lock between phases, allowing audit chain appends from other coroutines to interleave. For Phase 07 this is sufficient; WAL mode (`PRAGMA journal_mode=WAL`) can be added in Phase 08 when concurrent ingestion load increases.

---

## 4. Audit Chain Hook Points

`audit_chain.append()` requires a live `AsyncSession` and acquires `_lock` internally. Call it within the same session that just committed the phase data — open a new mini-transaction for the audit row alone so the chain append is atomic.

| Phase | Audit `action` | `target_type` | Key payload fields |
|---|---|---|---|
| Document accepted | `document.accepted` | `document` | `sha256`, `source_uri`, `mime_type` |
| Parse complete | `pipeline.parse_complete` | `document` | `doc_id`, `char_count`, `section_count`, `language` |
| Parse failed | `pipeline.parse_failed` | `document` | `doc_id`, `error_type`, `error_msg` |
| Chunk complete | `pipeline.chunk_complete` | `document` | `doc_id`, `chunk_count` |
| IOC extraction complete | `pipeline.ioc_complete` | `document` | `doc_id`, `ioc_count`, `evidence_count`, `extractor_id` |
| No IOCs (abstention) | `pipeline.no_iocs` | `document` | `doc_id`, `chunk_count` |
| STIX build+validate complete | `pipeline.stix_complete` | `document` | `doc_id`, `bundle_hash`, `stix_object_count`, `validation_layers_ok` |
| STIX validation failed | `pipeline.stix_failed` | `document` | `doc_id`, `validation_issues` (list of `{layer, code}`) |
| Pipeline complete | `pipeline.complete` | `document` | `doc_id`, `bundle_hash`, `duration_ms` |
| Pipeline failed | `pipeline.failed` | `document` | `doc_id`, `failed_phase`, `error_type` |

**Critical rule:** if `audit_chain.append()` raises `AuditChainError`, halt the pipeline immediately. Do not swallow. Set `document.status=audit_chain_error` and re-raise. This is a data integrity violation — the chain is broken and must be investigated before further writes.

---

## 5. Error Semantics Matrix

| Exception | Source | Action | `document.status` | Retry? |
|---|---|---|---|---|
| `UnsupportedFormatError` | dispatcher | Fail fast; audit `parse_failed` | `failed_parse` | No (format won't change) |
| `UnsupportedLanguageError` | dispatcher / language check | Fail fast; audit `parse_failed` | `failed_parse` | No |
| `OCRFailedError` | pdf_parser | Fail fast; audit `parse_failed` | `failed_parse` | No |
| `ParsedDocument.text == ""` | dispatcher | Fail soft; audit `parse_failed` | `failed_parse` | No |
| `len(chunks) == 0` | chunker | Fail soft; audit `chunk_empty`; status=empty | `empty` | No |
| `ExtractionResult.iocs == []` | regex extractor | Valid abstention; audit `no_iocs`; return cleanly | `no_iocs` | No |
| `StixBuildError` (0 indicators) | builders.py | Fail hard; audit `stix_failed` | `failed_stix` | No (same input → same result) |
| `ValidationResult.is_valid == False` (layer 2) | validators.py | Fail hard; audit `stix_failed` with issues | `failed_stix` | No |
| `ValidationResult.is_valid == False` (layer 1 or 3) | validators.py | Fail hard; same as above | `failed_stix` | No |
| `IntegrityError` on IOC insert (duplicate) | SQLAlchemy | Catch; use `on_conflict_do_nothing`; not a failure | — | N/A (handled inline) |
| `AuditChainError` | audit_chain | CRITICAL halt; do not swallow | `audit_chain_error` | Manual only |
| Any other `AppError` | any | Log + audit `pipeline.failed`; set status | `failed` | Yes (up to 3 per CLAUDE.md) |
| `Exception` (unexpected) | any | Log + audit `pipeline.failed`; re-raise | `failed` | Yes (up to 3) |

**Note on `StixBuildError`:** `builders.py` line 79 raises when `indicator_refs` is empty. This happens when all IOCs are CVEs (skipped in Phase 1) or all fail `ioc_to_stix_pattern`. The orchestrator must guard: if `ioc_count > 0` but `build_bundle` raises `StixBuildError`, that is a data quality failure, not an abstention. Log it as `failed_stix`.

---

## 6. BackgroundTasks Wiring

### Router → orchestrator → session pattern

```python
# app/api/routers/ingest.py
from fastapi import APIRouter, BackgroundTasks, status
from app.jobs.pipelines import process_document

router = APIRouter()

@router.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
async def ingest(
    payload: IngestRequest,
    background_tasks: BackgroundTasks,
) -> IngestResponse:
    # Validate + store raw bytes synchronously (fast path)
    doc_id = await _create_pending_document(payload)
    background_tasks.add_task(process_document, doc_id, payload.source_uri)
    return IngestResponse(document_id=doc_id, status="accepted")
```

```python
# app/jobs/pipelines.py
from app.db.session import SessionFactory   # async_sessionmaker, NOT get_session

async def process_document(document_id: str, source_uri: str) -> None:
    # Opens its OWN session — request session is already closed
    async with SessionFactory() as session:
        try:
            await _run_pipeline(session, document_id, source_uri)
        except Exception:
            # top-level catch: status already set per-phase; just log
            log.exception("pipeline.unhandled_error", document_id=document_id)
```

**Key points:**
- `SessionFactory` (the `async_sessionmaker`) is imported directly, not `get_session`. `get_session` is for request-scoped dependency injection; background tasks have no request scope.
- `SessionFactory()` returns an `AsyncSession` context manager with `expire_on_commit=False` (already configured in `session.py` line 55) — safe for background use since objects aren't expired after commit.
- The background task is fire-and-forget from the router's perspective. The router returns 202 immediately; the task runs in the same event loop after the response is sent.
- Do NOT pass the `AsyncSession` from the router into `add_task`. FastAPI closes the request session before the background task runs, causing `DetachedInstanceError`.

---

## 7. Persistence Ordering

### FK dependency chain

```
documents                          ← insert first (Phase 0)
  └── chunks (FK: document_id)     ← Phase 2
        └── evidence_spans (FK: chunk_id)   ← Phase 3
  └── ioc_candidates (FK: document_id)      ← Phase 3 (after evidence_spans)
  └── stix_objects (FK: document_id)        ← Phase 4
  └── stix_relationships (FK: document_id)  ← Phase 4 (after stix_objects)
  └── model_runs (FK: document_id)          ← end of each phase
audit_logs (no FK)                          ← after each phase commit
```

### Bulk insert pattern

Use `session.add_all(list_of_orm_objects)` + single `await session.commit()` per phase. Do NOT loop `session.add()` + `commit()` per row — that is N round-trips to SQLite.

For IOC candidates specifically, use `insert(...).on_conflict_do_nothing(index_elements=["document_id", "type", "normalized"])` (matches the `ix_ioc_doc_type_norm` unique index in `ioc_candidate.py` line 27) to handle idempotent re-runs without raising.

```python
# Phase 3 bulk insert pattern
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

ioc_rows = [
    {"id": str(uuid4()), "document_id": doc_id, "type": c.type.value,
     "value": c.value, "normalized": c.normalized,
     "evidence_ids": c.evidence_ids, "confidence": float(c.confidence),
     "extractor": c.extractor, "created_at": now, "updated_at": now}
    for c in all_iocs
]
if ioc_rows:
    await session.execute(
        sqlite_insert(IocCandidate).on_conflict_do_nothing(
            index_elements=["document_id", "type", "normalized"]
        ),
        ioc_rows,
    )
```

`EvidenceSpan` has no unique constraint beyond PK — use deterministic UUIDs derived from `evidence_id` (already deterministic in `extractor.py` via `_evidence_id()`) so re-runs produce the same PK and `on_conflict_do_nothing` on PK handles duplicates.

`StixObject.stix_id` has `unique=True` — use `on_conflict_do_nothing(index_elements=["stix_id"])`.

---

## 8. Observability

### structlog bindings

```python
import structlog
from app.core.logging import get_logger

log = get_logger(__name__)

async def process_document(document_id: str, source_uri: str) -> None:
    # Bind document_id for all log calls in this coroutine
    structlog.contextvars.bind_contextvars(document_id=document_id)
    t0 = time.monotonic()
    ...
    # Per-phase
    log.info("pipeline.parse_complete", char_count=len(parsed.text),
             section_count=len(parsed.sections), duration_ms=_ms(t0))
    ...
    log.info("pipeline.complete",
             chunk_count=chunk_count,
             ioc_count=ioc_count,
             stix_object_count=stix_obj_count,
             bundle_hash=b_hash,
             total_duration_ms=_ms(t0))
```

### Key metrics to log per phase

| Event | Fields |
|---|---|
| `pipeline.start` | `document_id`, `source_uri` (redacted if sensitive), `sha256` |
| `pipeline.parse_complete` | `char_count`, `section_count`, `language`, `duration_ms` |
| `pipeline.chunk_complete` | `chunk_count`, `duration_ms` |
| `pipeline.ioc_complete` | `ioc_count`, `evidence_count`, `extractor_id`, `duration_ms` |
| `pipeline.stix_complete` | `stix_object_count`, `bundle_hash`, `validation_ok`, `duration_ms` |
| `pipeline.complete` | all counts + `total_duration_ms` |
| `pipeline.failed` | `failed_phase`, `error_type`, `error_msg` |

Use `structlog.contextvars.bind_contextvars` at entry so every log line in the coroutine automatically carries `document_id` without passing it explicitly. Clear with `structlog.contextvars.clear_contextvars()` in a `finally` block.

---

## 9. Concurrent Run Handling

**Problem:** two POST /ingest with identical content arrive within milliseconds. Both compute the same `sha256`. Both call `process_document` as background tasks.

**Solution (layered):**

1. **`on_conflict_do_nothing` on `documents.sha256`** — only one INSERT wins. The loser gets back the existing row.
2. **Status check at orchestrator entry** — after upsert, read `document.status`. If `processing` or `complete`, return immediately. The `processing` status is set atomically in the same transaction as the document upsert.
3. **`asyncio.Lock` in `audit_chain.py`** — already serializes audit appends; no additional locking needed there.

**Why not `SELECT FOR UPDATE`:** SQLite does not support row-level locking. `SELECT FOR UPDATE` is silently ignored by aiosqlite. The UNIQUE constraint + status check is the correct SQLite idiom.

**Why not application-level lock dict:** a `dict[str, asyncio.Lock]` keyed on `document_id` would work for single-process but leaks memory and doesn't survive process restart. The DB constraint is simpler and durable.

**Race window:** between the status read and the status write, a second coroutine could read `pending` and proceed. This is acceptable for Phase 07 — worst case is two pipeline runs for the same document, both hitting `on_conflict_do_nothing` on all subsequent inserts and producing identical output. The second run is a no-op at the DB level. Add a process-level `asyncio.Lock` keyed on `document_id` only if this becomes a measured problem.

---

## 10. Test Plan

### Unit tests (`tests/unit/jobs/`)

| Test | What it verifies |
|---|---|
| `test_process_document_happy_path` | Full pipeline on a small MD fixture; asserts `document.status=complete`, `chunk_count>0`, `ioc_count>=0`, `audit_log` chain intact |
| `test_idempotent_rerun` | Call `process_document` twice with same `document_id`; assert DB row counts unchanged on second run |
| `test_duplicate_sha256_concurrent` | Two coroutines submit same content concurrently via `asyncio.gather`; assert exactly one `Document` row, status=complete |
| `test_parse_failure_sets_status` | Feed unsupported MIME; assert `document.status=failed_parse`, audit row present |
| `test_empty_chunks_sets_status` | Feed whitespace-only text; assert `document.status=empty` |
| `test_zero_iocs_is_valid` | Feed text with no IOC patterns; assert `document.status=no_iocs`, no `StixBuildError` raised |
| `test_stix_validation_failure_sets_status` | Monkeypatch `validate()` to return `is_valid=False`; assert `document.status=failed_stix` |
| `test_audit_chain_error_halts_pipeline` | Monkeypatch `audit_chain.append` to raise `AuditChainError`; assert pipeline halts, status=`audit_chain_error` |
| `test_model_run_rows_created` | After happy path, assert one `ModelRun` row per phase |

### Integration test (`tests/integration/test_pipeline_e2e.py`)

```python
@pytest.mark.asyncio
async def test_full_pipeline_md_report(tmp_path):
    # 1. Write a small MD fixture with known IOCs
    report = tmp_path / "report.md"
    report.write_text("## C2 Infrastructure\nIP: 192.168.1[.]1\nDomain: evil[.]com\n")

    # 2. Run orchestrator directly (no HTTP layer needed for unit)
    async with SessionFactory() as session:
        doc_id = await _create_document_row(session, report)
    await process_document(doc_id, str(report))

    # 3. Assert DB state
    async with SessionFactory() as session:
        doc = await session.get(Document, doc_id)
        assert doc.status == "complete"
        chunks = (await session.execute(
            select(Chunk).where(Chunk.document_id == doc_id)
        )).scalars().all()
        assert len(chunks) > 0
        iocs = (await session.execute(
            select(IocCandidate).where(IocCandidate.document_id == doc_id)
        )).scalars().all()
        # known IOCs from fixture
        normalized = {i.normalized for i in iocs}
        assert "192.168.1.1" in normalized
        assert "evil.com" in normalized
        # STIX objects persisted
        stix_objs = (await session.execute(
            select(StixObject).where(StixObject.document_id == doc_id)
        )).scalars().all()
        assert len(stix_objs) >= 2  # report + indicators
        # Audit chain intact
        ok, count = await verify_chain(session)
        assert ok is True
        assert count >= 5  # one per phase
```

**Fixture note:** use `tests/fixtures/reports/sample_cti.md` — create a small (< 500 char) English CTI snippet with 2-3 known defanged IOCs. No LLM mocking needed (Phase 07 is regex-only).

**pytest config:** tests need `pytest-asyncio` with `asyncio_mode = "auto"` (check `pyproject.toml`). Use in-memory SQLite (`sqlite+aiosqlite:///:memory:`) with `Base.metadata.create_all` in a session-scoped fixture, matching the pattern in `tests/unit/db/test_audit_chain.py`.

---

## 11. Risks & Open Questions

### Risks

1. **`audit_chain._lock` is module-level.** In tests that run multiple pipeline coroutines concurrently, the lock is shared across all test cases in the session. Tests must use isolated engines/sessions (as `test_audit_chain.py` does) or the lock will serialize across unrelated tests, causing false deadlocks.

2. **`StixBuildError` when all IOCs are CVEs.** Phase 07 corpus may include CVE-heavy reports. The pipeline must check `len([i for i in iocs if i.type != IocType.CVE]) == 0` before calling `build_bundle` and emit `no_iocs` status rather than letting `StixBuildError` propagate as a failure.

3. **`on_conflict_do_nothing` dialect import.** `from sqlalchemy.dialects.sqlite import insert` works for SQLite dev. For Postgres (Phase 08+), swap to `from sqlalchemy.dialects.postgresql import insert`. Abstract behind a helper in `app/db/upsert.py` now to avoid scattered dialect imports.

4. **`document.status` race on retry.** If a background task crashes mid-phase without setting `failed_*` status (e.g., OOM kill), the document stays in `processing` forever. Add a `processing_since` timestamp and a stale-detection sweep (Phase 08 concern, note it now).

5. **`structlog.contextvars` leaks across tasks.** `bind_contextvars` binds to the current `contextvars.Context`. FastAPI background tasks inherit the request context. Always call `clear_contextvars()` at the start of `process_document` to prevent stale bindings from a previous request leaking into the log.

### Open questions

1. Should `pipelines.py` split into `pipelines.py` (orchestration logic, ≤300 LOC) + `persistence.py` (all DB insert helpers)? Given the FK chain and bulk insert patterns, `persistence.py` is likely needed to stay under the 300 LOC hard limit.

2. `ModelRun.model` field — what string to use for the regex extractor phase? Suggest `"regex_ioc"` with `version` from `app/extractors/regex_ioc/version.py`. Confirm `__extractor_id__` format matches `ModelRun.model` expectations.

3. `Document` model has no `processing_since` or `worker_id` column. Is a stale-lock detection mechanism in scope for Phase 07 or deferred?

4. The `IngestRequest` schema (router input) does not exist yet — Phase 07 creates it. Should it accept raw bytes + mime_type, or a file path / URL string? The `dispatcher.dispatch()` signature supports both; the router design choice affects the test fixture approach.

5. `EvidenceSpan` PK is a UUID from `UuidMixin` — but `extractor.py` generates deterministic `evidence_id` strings with `e-` prefix (not UUID format). The DB model uses `UuidMixin` (UUID PK) while the schema uses `evidence_id` (string with `e-` prefix). The persistence layer must map schema `evidence_id` → a separate column or use it as the PK. Clarify before implementing `persistence.py`.
