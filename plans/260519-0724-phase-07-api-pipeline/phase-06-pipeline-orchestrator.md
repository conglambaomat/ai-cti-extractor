---
phase: 6
title: "Pipeline orchestrator + persistence layer"
status: pending
priority: P1
effort: "3h"
dependencies: [1, 4]
---

# Phase 06: process_document orchestrator + persistence

## Overview

`process_document(document_id, source_uri)` orchestrates: parse → chunk → IOC extract → STIX build+validate → persist → audit. Per-phase commits, status cursor on `documents.status`, model_runs as phase receipts.

Per researcher recommendation, split into two files to stay under 300 LOC.

## Files

```
app/jobs/
├── __init__.py
├── pipelines.py       # process_document orchestrator (~250 LOC)
└── persistence.py     # bulk insert helpers per phase (~250 LOC)
```

## Architecture

### Status state machine

```
pending → processing → parsed → chunked → ioc_extracted → stix_built → complete
                ↓          ↓         ↓            ↓                ↓
          failed_parse  failed_  failed_      no_iocs         failed_stix
                       parse     ioc          (terminal-OK)
                                                                   ↓
                                                          audit_chain_error
                                                                   ↓
                                                                 failed
```

### Orchestrator skeleton

```python
# app/jobs/pipelines.py
import asyncio
import time
from typing import cast
from uuid import uuid4

import structlog
from sqlalchemy import select

from app.core.exceptions import (
    AppError,
    AuditChainError,
    EvidenceMissingError,
    StixError,
    UnsupportedFormatError,
    UnsupportedLanguageError,
)
from app.db.audit_chain import append as audit_append
from app.db.models.document import Document
from app.db.models.model_run import ModelRun
from app.db.session import SessionFactory
from app.ingestion.chunking import chunk
from app.ingestion.dispatcher import dispatch
from app.ingestion.language import assert_english
from app.extractors.regex_ioc.extractor import extract as extract_iocs
from app.jobs import persistence
from app.stix.builders import build_bundle
from app.stix.validators import validate as validate_bundle
from app.stix.exporters import serialize_canonical, bundle_hash
from app.schemas.intermediate_cti import IntermediateCTI

log = structlog.get_logger(__name__)


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


async def process_document(document_id: str, source_uri: str) -> None:
    """Run the full extraction pipeline for one document.

    Idempotent: re-runs skip completed phases via document.status check.
    Each phase commits independently to avoid SQLite long write locks.
    """
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(document_id=document_id)
    t0 = time.monotonic()

    try:
        async with SessionFactory() as session:
            doc = await session.get(Document, document_id)
            if doc is None:
                log.error("pipeline.document_not_found")
                return
            if doc.status in ("complete", "no_iocs"):
                log.info("pipeline.already_done", status=doc.status)
                return

        # --- Phase 1: parse ---
        try:
            parsed = await dispatch(source_uri)
            assert_english(parsed.text)
        except (UnsupportedFormatError, UnsupportedLanguageError) as e:
            await _set_status_and_audit(
                document_id, "failed_parse",
                "pipeline.parse_failed",
                {"error_type": type(e).__name__, "error_msg": str(e)},
            )
            return

        await persistence.update_doc_after_parse(document_id, parsed)
        log.info("pipeline.parse_complete",
                 char_count=len(parsed.text),
                 section_count=len(parsed.sections),
                 duration_ms=_ms(t0))

        # --- Phase 2: chunk ---
        chunks = chunk(parsed, document_id=document_id)
        if not chunks:
            await _set_status_and_audit(
                document_id, "empty",
                "pipeline.chunk_empty", {},
            )
            return
        await persistence.persist_chunks(document_id, chunks)
        log.info("pipeline.chunk_complete", chunk_count=len(chunks))

        # --- Phase 3: IOC extraction ---
        all_iocs = []
        all_evidence = []
        for c in chunks:
            result = extract_iocs(c)
            all_iocs.extend(result.iocs)
            all_evidence.extend(result.evidence)

        if not all_iocs:
            await persistence.persist_evidence(document_id, all_evidence)
            await _set_status_and_audit(
                document_id, "no_iocs",
                "pipeline.no_iocs", {"chunk_count": len(chunks)},
            )
            log.info("pipeline.no_iocs_terminal")
            return

        await persistence.persist_evidence(document_id, all_evidence)
        await persistence.persist_iocs(document_id, all_iocs)
        log.info("pipeline.ioc_complete",
                 ioc_count=len(all_iocs), evidence_count=len(all_evidence))

        # --- Phase 4: STIX build + validate ---
        try:
            cti = IntermediateCTI(
                document_id=document_id,
                source_uri=source_uri,
                language="en",
                ingested_at=parsed.metadata.get("ingested_at") or _now_utc(),
                evidence=all_evidence,
                iocs=all_iocs,
                chunks=[_to_chunk_ref(c) for c in chunks],
            )
            bundle = build_bundle(cti)
        except StixError as e:
            await _set_status_and_audit(
                document_id, "failed_stix",
                "pipeline.stix_failed",
                {"error_type": type(e).__name__, "error_msg": str(e)},
            )
            return

        result = validate_bundle(bundle)
        if not result.is_valid:
            await _set_status_and_audit(
                document_id, "failed_stix",
                "pipeline.stix_validation_failed",
                {"issues": [i.model_dump() for i in result.issues]},
            )
            return

        b_hash = bundle_hash(bundle)
        await persistence.persist_stix(document_id, bundle, b_hash)
        log.info("pipeline.stix_complete",
                 stix_object_count=len(bundle.objects),
                 bundle_hash=b_hash)

        # --- Terminal: audit + status=complete ---
        await _set_status_and_audit(
            document_id, "complete",
            "pipeline.complete",
            {"bundle_hash": b_hash, "duration_ms": _ms(t0)},
        )
        log.info("pipeline.complete", total_duration_ms=_ms(t0))

    except AuditChainError:
        # CRITICAL — never swallow
        log.critical("pipeline.audit_chain_error", alert=True)
        await _force_status(document_id, "audit_chain_error")
        raise
    except Exception as exc:
        log.exception("pipeline.unhandled_error")
        try:
            await _force_status(document_id, "failed")
        except Exception:
            pass
    finally:
        structlog.contextvars.clear_contextvars()
```

### Persistence module

`app/jobs/persistence.py` exports:
- `update_doc_after_parse(doc_id, parsed)` — set title/language/source_format
- `persist_chunks(doc_id, chunks)` — bulk insert via `add_all` (chunks have natural unique on (doc_id, char_start))
- `persist_evidence(doc_id, evidence)` — bulk insert via `insert_ignore` keyed on `evidence_id`
- `persist_iocs(doc_id, iocs)` — bulk insert via `insert_ignore` keyed on `(document_id, type, normalized)`
- `persist_stix(doc_id, bundle, bundle_hash)` — split bundle into StixObject rows + StixRelationship rows; serialize bundle JSON to storage
- `record_model_run(session, doc_id, model, version, input_hash, output_hash)` — append ModelRun row
- `_set_status_and_audit(doc_id, status, action, payload)` — atomic status + audit chain append in one mini-tx

### Audit chain hook points

Per researcher report — one append per phase terminal event:

| Phase | action | payload |
|---|---|---|
| Document accepted | `document.accepted` | sha256, source_uri |
| Parse complete | `pipeline.parse_complete` | char_count, section_count, language |
| Parse failed | `pipeline.parse_failed` | error_type, error_msg |
| Chunk complete | `pipeline.chunk_complete` | chunk_count |
| IOC complete | `pipeline.ioc_complete` | ioc_count, evidence_count |
| No IOCs | `pipeline.no_iocs` | chunk_count |
| STIX complete | `pipeline.stix_complete` | bundle_hash, object_count |
| STIX failed | `pipeline.stix_failed` | issues |
| Pipeline complete | `pipeline.complete` | bundle_hash, duration_ms |

## Related Code Files

- Create: `app/jobs/__init__.py`
- Create: `app/jobs/pipelines.py` (~250 LOC)
- Create: `app/jobs/persistence.py` (~250 LOC)
- Create: `tests/unit/jobs/test_pipelines.py`
- Create: `tests/unit/jobs/test_persistence.py`

## Implementation Steps

1. `persistence.py` first — easier to unit-test in isolation.
2. `_set_status_and_audit` helper used by all error paths.
3. Orchestrator with try/except per phase.
4. Wire into `app/api/routers/ingest.py`: `background_tasks.add_task(process_document, doc.id, doc.source_uri)`.
5. Tests:
   - happy-path MD with 2-3 known IOCs (uses fixtures from Phase 03/05 tests)
   - empty content → status=empty
   - non-English → status=failed_parse
   - zero-IOC content → status=no_iocs (terminal-OK, NOT failed)
   - duplicate run → no double-insert (idempotent)
   - audit chain verify_chain returns ok=True

## Success Criteria

- [ ] All status transitions tested
- [ ] No StixBuildError leaked when zero IOCs (guarded before build_bundle)
- [ ] `audit_chain.verify_chain` returns `(True, n)` after happy path
- [ ] Idempotent re-run: row counts unchanged
- [ ] Both pipelines.py and persistence.py < 300 LOC
- [ ] mypy --strict + ruff + bandit clean

## Risks

- `audit_chain._lock` is module-level — concurrent tests must use isolated engines (existing pattern in `test_audit_chain.py`)
- `IntermediateCTI` requires `ingested_at` — pull from `parsed.metadata` or generate at orchestrator start (record once for stable bundle hash)
- `Chunk.section` ↔ DB column: chunks ORM model needs `section: str | None` field — verify exists; add if missing
