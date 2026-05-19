---
phase: 5
title: "API routers — health / ingest / documents / extractions / stix"
status: pending
priority: P1
effort: "2h"
dependencies: [4]
---

# Phase 05: Routers

## Overview

5 routers wiring Phase 02–06 modules to HTTP. All response models Pydantic v2. All endpoints async. Read-only routers query DB; ingest router accepts content + dispatches background task.

## Files

```
app/api/routers/
├── __init__.py
├── health.py
├── ingest.py
├── documents.py
├── extractions.py
└── stix.py
```

## Endpoints

### `GET /health`
- Response: `{"status": "ok", "env": "development", "version": "0.1.0"}`
- No DB hit

### `POST /ingest`
- Request: multipart `file: UploadFile` OR JSON `{"url": str}` OR JSON `{"content": str, "mime_type": str}`
- Response 202: `{"document_id": "...", "status": "queued"}`
- Side effect: persists raw bytes via `Storage`, creates `Document` row (status=`pending`), schedules `process_document` background task
- Idempotency: dedupe by `sha256(content)`; existing document → return same `document_id` with current `status`

### `GET /documents/{doc_id}`
- Response 200: `DocumentResponse` (id, source_uri, sha256, title, language, mime_type, source_format, status, created_at, updated_at, counts: chunks/iocs/stix_objects)
- 404 if not found

### `GET /documents/{doc_id}/chunks`
- Response 200: `list[ChunkResponse]` (id, char_start, char_end, section, length)
- Paginated (`?limit=50&offset=0`)

### `POST /documents/{doc_id}/extract` (re-trigger)
- Response 202: `{"status": "queued"}`
- Schedules `process_document` again (idempotent — orchestrator skips completed phases)

### `GET /extractions/{doc_id}`
- Response 200: `ExtractionResponse` (iocs: list, evidence_count, status, errors)
- 404 if document not found

### `POST /stix/validate`
- Request: `{"bundle": dict}` (raw STIX JSON)
- Response 200: `ValidationResult` (is_valid, layer, issues)
- Calls `app.stix.validators.validate(bundle)` directly — no DB

### `GET /stix/{doc_id}`
- Response 200: STIX bundle JSON (`application/stix+json;version=2.1`)
- 404 if not found

## Pydantic response models

```python
# app/api/schemas.py
class IngestResponse(BaseModel):
    document_id: str
    status: Literal["queued", "duplicate"]


class DocumentResponse(BaseModel):
    id: str
    source_uri: str
    sha256: str
    title: str | None
    language: str
    mime_type: str | None
    source_format: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    chunk_count: int
    ioc_count: int
    stix_object_count: int


class ChunkResponse(BaseModel):
    id: str
    char_start: int
    char_end: int
    section: str | None
    length: int


class IocResponse(BaseModel):
    id: str
    type: str
    value: str
    normalized: str
    confidence: float
    evidence_ids: list[str]


class ExtractionResponse(BaseModel):
    document_id: str
    status: str
    ioc_count: int
    evidence_count: int
    iocs: list[IocResponse]


class StixValidateRequest(BaseModel):
    bundle: dict[str, Any]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    env: str
    version: str
```

## Related Code Files

- Create: `app/api/routers/__init__.py`
- Create: `app/api/routers/health.py` (~30 LOC)
- Create: `app/api/routers/ingest.py` (~120 LOC)
- Create: `app/api/routers/documents.py` (~120 LOC)
- Create: `app/api/routers/extractions.py` (~100 LOC)
- Create: `app/api/routers/stix.py` (~80 LOC)
- Create: `app/api/schemas.py` (~120 LOC)
- Create: `tests/unit/api/routers/test_health.py`
- Create: `tests/unit/api/routers/test_ingest.py`
- Create: `tests/unit/api/routers/test_documents.py`

## Implementation Steps

1. `app/api/schemas.py` — all response/request models.
2. `health.py` — trivial, no DB.
3. `ingest.py` —
   - `_compute_sha256(data)` helper
   - `_persist_document(db, storage, source_uri, content, mime)` returns Document instance
   - `_dedupe_by_sha256(db, sha256)` returns existing Document or None
   - Storage key format: `{document_id}/raw` + content_type from mime
   - On dedupe hit: return 200 with `status="duplicate"` (NOT 202)
4. `documents.py` —
   - `get_document` joins `chunks`/`iocs`/`stix_objects` counts via subquery
   - `list_chunks` with limit/offset
   - `trigger_extract` schedules background task
5. `extractions.py` — pulls IocCandidate rows + counts
6. `stix.py` — `/validate` calls `validators.validate(...)`; `/{doc_id}` reads StixObject rows + serializes via `exporters.serialize_canonical`
7. Tests use `httpx.AsyncClient(transport=ASGITransport(app=app))` with overridden `get_db`.

## Success Criteria

- [ ] `GET /health` returns 200 with version
- [ ] `POST /ingest` round-trips MD content → returns 202 with doc_id
- [ ] Duplicate ingest returns existing doc_id with status="duplicate"
- [ ] `GET /documents/{id}` returns 404 for unknown id
- [ ] `POST /stix/validate` rejects malformed bundle
- [ ] All routers wired in `create_app`
- [ ] OpenAPI schema generates without errors
