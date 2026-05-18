---
phase: 7
title: "FastAPI service + RQ worker + pipeline orchestrator"
status: pending
priority: P1
effort: "4d"
dependencies: [03, 05, 06]
file_ownership:
  create:
    - app/api/__init__.py
    - app/api/main.py
    - app/api/routers/__init__.py
    - app/api/routers/health.py
    - app/api/routers/ingest.py
    - app/api/routers/extract.py
    - app/api/routers/documents.py
    - app/api/routers/stix.py
    - app/api/dependencies.py
    - app/api/middleware.py
    - app/jobs/__init__.py
    - app/jobs/queue.py
    - app/jobs/worker.py
    - app/jobs/pipelines.py
    - app/storage/__init__.py
    - app/storage/s3.py
    - tests/integration/test_ingest_endpoint.py
    - tests/integration/test_extract_pipeline.py
    - tests/integration/test_health.py
---

# Phase 07 — FastAPI service + RQ worker + pipeline orchestrator

## Overview

Wire ingestion → extraction → STIX into an async API + background worker. POST `/ingest` accepts a file or URL, persists raw to S3 (MinIO local), creates a `Document` row, enqueues an extract job. Worker picks up the job, runs the pipeline (parse → chunk → IOC extract → STIX build → validate → persist), writes STIX bundle to DB. GET `/extractions/{id}` returns the intermediate CTI JSON. POST `/stix/validate` is a side endpoint for analysts to validate ad-hoc bundles.

This phase glues all prior phases into something operable.

## Requirements

### Functional
- `POST /ingest` — multipart upload OR `{ "url": "..." }`. Validates Content-Type, stores raw to S3, hashes, creates Document, enqueues extract job, returns 202 with document_id + job_id.
- `POST /documents/{id}/extract` — explicit re-extract (idempotent, new model_run row).
- `GET /documents/{id}` — document metadata + extraction status.
- `GET /documents/{id}/chunks` — paginated chunks.
- `GET /extractions/{id}` — intermediate CTI JSON.
- `POST /stix/validate` — accepts STIX bundle JSON in body, returns ValidationResult.
- `GET /health` — liveness + readiness (DB + Redis + S3 reachable).
- Pipeline runs in worker, persists everything (chunks, evidence, IOCs, STIX objects, audit log entries).
- Job idempotency: same `(document_id, pipeline_version, extractor_versions)` → same output, no duplicate audit entries.

### Non-functional
- API p95 ≤ 200 ms for non-pipeline endpoints
- Worker processes 10-page PDF end-to-end ≤ 30 s (Phase 1, no LLM)
- Health endpoint < 50 ms when all deps healthy
- Errors return RFC 7807 problem+json
- Coverage ≥ 70% on `app/api/` + `app/jobs/`

## Architecture

### API entry (`app/api/main.py`)
```python
from fastapi import FastAPI
from app.core.config import settings
from app.api.middleware import correlation_id_middleware, problem_detail_handler
from app.api.routers import health, ingest, extract, documents, stix

def create_app() -> FastAPI:
    app = FastAPI(
        title="AI-Assisted CTI Extractor",
        version=__version__,
        docs_url="/docs" if settings.APP_ENV != "production" else None,
    )
    app.middleware("http")(correlation_id_middleware)
    app.add_exception_handler(AppError, problem_detail_handler)
    app.include_router(health.router)
    app.include_router(ingest.router, prefix="/ingest", tags=["ingestion"])
    app.include_router(documents.router, prefix="/documents", tags=["documents"])
    app.include_router(extract.router, prefix="/extractions", tags=["extraction"])
    app.include_router(stix.router, prefix="/stix", tags=["stix"])
    return app

app = create_app()
```

### Middleware (`app/api/middleware.py`)
- `correlation_id_middleware`: read header `X-Correlation-Id` or generate UUIDv4; bind to structlog context; echo back in response header
- `problem_detail_handler(request, exc)`: convert `AppError` subclasses → RFC 7807 JSON

### Routers
Concise, one resource each. Example:

```python
# app/api/routers/ingest.py
@router.post("", status_code=202, response_model=IngestResponse)
async def ingest(
    payload: IngestRequest,
    s3: S3Client = Depends(get_s3),
    db: AsyncSession = Depends(get_db),
    queue: Queue = Depends(get_queue),
) -> IngestResponse:
    if payload.url:
        raw, mime = await fetch_url(payload.url)
    elif payload.file:
        raw, mime = await read_upload(payload.file)
    else:
        raise UnsupportedFormatError("must provide url or file")

    sha = sha256(raw)
    s3_key = f"raw/{sha[:2]}/{sha}"
    await s3.put_object(Bucket=settings.S3_BUCKET, Key=s3_key, Body=raw)

    doc = Document(
        sha256=sha, source_uri=payload.url or payload.file.filename,
        mime_type=mime, status="pending",
    )
    db.add(doc); await db.commit(); await db.refresh(doc)

    job = queue.enqueue("app.jobs.pipelines.process_document", doc.id, job_timeout=600)
    await audit_repo.append(actor="api", action="ingest", target_type="document",
                            target_id=doc.id, payload={"sha256": sha, "mime_type": mime})

    return IngestResponse(document_id=doc.id, job_id=job.id, status="queued")
```

### Pipeline orchestrator (`app/jobs/pipelines.py`)

```python
def process_document(document_id: str) -> None:
    """Idempotent. Pulls raw from S3, runs full Phase 1 pipeline."""
    log = get_logger("pipeline").bind(document_id=document_id)
    started = utcnow()

    with get_session_sync() as db:
        doc = doc_repo.get_by_id(db, document_id)
        if doc.status == "completed" and not _re_extract_requested(doc):
            log.info("already_extracted", skipping=True)
            return

        raw = s3.get_object(Bucket=settings.S3_BUCKET, Key=f"raw/{doc.sha256[:2]}/{doc.sha256}")["Body"].read()
        parsed = ingestion.dispatch(raw, mime_type=doc.mime_type)
        chunks = ingestion.chunk(parsed, document_id=doc.id)
        chunk_repo.bulk_insert(db, chunks)

        cti_iocs = []
        cti_evidence = []
        for ch in chunks:
            iocs, evidences = regex_ioc.extract(ch)
            cti_iocs.extend(iocs)
            cti_evidence.extend(evidences)

        intermediate = IntermediateCTI(
            document=doc.as_meta(),
            chunks=[c.as_ref() for c in chunks],
            candidates=Candidates(iocs=cti_iocs),
            evidence=cti_evidence,
            provenance=Provenance(...),
        )

        bundle = stix.build_bundle(intermediate)
        validation = stix.validate(intermediate, bundle)
        if not (validation.parse_ok and validation.semantic_ok):
            log.error("stix_validation_failed", errors=validation.errors)
            doc.status = "failed"
            db.commit()
            audit_repo.append(...)  # failure
            return

        stix_repo.persist_bundle(db, bundle, document_id=doc.id)
        doc.status = "completed"
        doc.title = parsed.metadata.get("title")
        doc.language = parsed.language
        db.commit()

        audit_repo.append(
            actor="worker", action="extract", target_type="document", target_id=doc.id,
            payload={"chunk_count": len(chunks), "ioc_count": len(cti_iocs),
                     "bundle_hash": stix.bundle_hash(bundle), "duration_s": (utcnow() - started).total_seconds()},
        )
```

(Sync `get_session_sync` because RQ workers don't run an event loop natively. Phase 3+ may switch to Arq if async workers needed.)

### Storage (`app/storage/s3.py`)

Thin wrapper over `boto3.client('s3')` configured for MinIO; methods: `put_object`, `get_object`, `head_object`, `delete_object`. Bucket auto-created on startup if missing.

### Queue (`app/jobs/queue.py`)

```python
from rq import Queue
from redis import Redis
from app.core.config import settings

_redis = Redis.from_url(str(settings.REDIS_URL))
extract_queue = Queue("extract", connection=_redis, default_timeout=600)

def get_queue() -> Queue:
    return extract_queue
```

### Worker (`app/jobs/worker.py`)

```python
from rq import Worker
from app.jobs.queue import _redis, extract_queue

if __name__ == "__main__":
    Worker([extract_queue], connection=_redis).work(with_scheduler=False)
```

`make worker` runs this; Docker `Dockerfile.worker` CMD points here.

## Implementation steps

1. Create `app/api/main.py`, `dependencies.py`, `middleware.py`.
2. Create routers per ownership list; each is < 100 LOC; one resource per file.
3. Create `app/storage/s3.py`; configure MinIO endpoint from settings; auto-create bucket.
4. Create `app/jobs/queue.py`, `worker.py`.
5. Create `app/jobs/pipelines.py::process_document` per spec.
6. Wire DI: `get_db`, `get_s3`, `get_queue` in `app/api/dependencies.py`.
7. Update `Makefile`:
   - `dev` → `uvicorn app.api.main:app --reload --port 8000`
   - `worker` → `python -m app.jobs.worker`
   - `dev-stack` → starts API + worker + docker compose deps
8. Integration test `tests/integration/test_ingest_endpoint.py`:
   - POST sample PDF → 202 with document_id
   - GET /documents/{id} → status pending → completed (poll)
   - GET /extractions/{id} → contains ≥ 1 IOC
9. Integration test `tests/integration/test_extract_pipeline.py`:
   - Call `process_document` directly (no queue) on test fixture document
   - Assert chunks persisted, IOCs persisted, STIX bundle persisted, audit entries created
   - Re-run with same input → no duplicate audit entries (idempotency)
10. Integration test `tests/integration/test_health.py`:
    - `/health` returns 200 when deps up
    - returns 503 when DB or Redis or S3 unreachable
11. `make test && make types && make lint && make security` green.
12. Commit: `feat(p07): FastAPI + RQ worker + pipeline orchestrator`. Push.

## Success criteria

- [ ] `/health` returns 200 with all deps reachable
- [ ] `POST /ingest` with sample PDF → 202 → worker processes → status `completed`
- [ ] Sample PDF → ≥ 5 IOCs extracted, valid STIX bundle persisted, audit log entries present
- [ ] Re-run pipeline on same document → idempotent, bundle hash stable
- [ ] Health 503 when Redis stopped (regression test for failure handling)
- [ ] Coverage ≥ 70% on `app/api/`, `app/jobs/`

## Risk assessment

| Risk | Mitigation |
|---|---|
| RQ worker process leaking DB connections | Use `Session.close()` in `finally`; per-job session scope; integration test with 100 sequential jobs asserting connection pool stable |
| MinIO bucket auto-create race in CI | Single-shot init script in `docker/init-minio.sh`; called by docker compose `entrypoint` of MinIO sidecar |
| Large PDF upload OOM | FastAPI `request.stream()` for files > 10 MB; cap at 100 MB |
| Worker hangs on bad input | RQ `job_timeout=600`; failed jobs land in `failed_job_registry` with stack trace; worker auto-restart in Docker |
| Audit append non-transactional with main work | Wrap pipeline + audit in same DB transaction; if commit fails, both rolled back |
| Bundle persist large JSON in Postgres jsonb | Test with 5MB bundle; if perf issue, store bundle in S3 + reference; deferred unless real |
