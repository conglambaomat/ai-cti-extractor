"""Document ingestion endpoint.

Accepts an uploaded file or a JSON URL/inline payload. Persists raw bytes,
creates a ``Document`` row, and schedules ``process_document`` as a
FastAPI BackgroundTask. Idempotent: duplicates dedupe by ``sha256``.
"""

from __future__ import annotations

import hashlib
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, Storage
from app.api.schemas import IngestInlineRequest, IngestResponse, IngestUrlRequest
from app.core.exceptions import UnsupportedFormatError
from app.db.models.document import Document
from app.jobs.pipelines import process_document

router = APIRouter()

_ALLOWED_MIME = {
    "application/pdf",
    "text/html",
    "application/xhtml+xml",
    "text/markdown",
    "text/x-markdown",
    "text/plain",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def _create_or_get(
    db: DbSession,
    *,
    sha256: str,
    source_uri: str,
    title: str | None,
    mime_type: str | None,
) -> tuple[Document, bool]:
    """Return (document, was_duplicate)."""
    existing = (
        await db.execute(select(Document).where(Document.sha256 == sha256))
    ).scalar_one_or_none()
    if existing is not None:
        return existing, True

    doc = Document(
        source_uri=source_uri,
        sha256=sha256,
        title=title,
        language="en",
        mime_type=mime_type,
        status="pending",
    )
    db.add(doc)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        existing = (
            await db.execute(select(Document).where(Document.sha256 == sha256))
        ).scalar_one()
        return existing, True
    return doc, False


@router.post(
    "",
    response_model=IngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_file(
    db: DbSession,
    storage: Storage,
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(...)],
    title: Annotated[str | None, Form()] = None,
) -> IngestResponse:
    """Multipart upload path."""
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty upload")
    mime = (file.content_type or "application/octet-stream").split(";")[0].strip()
    if mime not in _ALLOWED_MIME and not mime.startswith("text/"):
        raise UnsupportedFormatError(f"mime type {mime!r} not accepted")

    sha = _sha256(raw)
    doc, dup = await _create_or_get(
        db,
        sha256=sha,
        source_uri=f"upload://{file.filename or 'document'}",
        title=title,
        mime_type=mime,
    )
    storage_uri: str
    if not dup:
        await storage.put_object(f"{doc.id}/raw", raw, content_type=mime)
        storage_uri = f"local://{doc.id}/raw"
        doc.source_uri = storage_uri
        await db.flush()
        background_tasks.add_task(process_document, doc.id, doc.source_uri)
    return IngestResponse(
        document_id=doc.id,
        sha256=doc.sha256,
        status=doc.status,
        duplicate=dup,
    )


@router.post(
    "/url",
    response_model=IngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_url(
    payload: IngestUrlRequest,
    db: DbSession,
    storage: Storage,
    background_tasks: BackgroundTasks,
) -> IngestResponse:
    """URL fetch path — defers fetch+content-hash to the orchestrator.

    A placeholder Document is created keyed on sha256(url) so analysts can
    resolve the row immediately; the orchestrator overwrites sha256 after
    fetching the real bytes (Phase 8 concern: handle URL→content drift).
    """
    surrogate = _sha256(payload.url.encode("utf-8"))
    doc, dup = await _create_or_get(
        db,
        sha256=surrogate,
        source_uri=payload.url,
        title=payload.title,
        mime_type=payload.mime_type,
    )
    if not dup:
        background_tasks.add_task(process_document, doc.id, payload.url)
    return IngestResponse(
        document_id=doc.id,
        sha256=doc.sha256,
        status=doc.status,
        duplicate=dup,
    )


@router.post(
    "/inline",
    response_model=IngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_inline(
    payload: IngestInlineRequest,
    db: DbSession,
    storage: Storage,
    background_tasks: BackgroundTasks,
) -> IngestResponse:
    """JSON-body path — content provided directly in the request."""
    raw = payload.content.encode("utf-8")
    sha = _sha256(raw)
    doc, dup = await _create_or_get(
        db,
        sha256=sha,
        source_uri=f"inline://{sha[:12]}",
        title=payload.title,
        mime_type=payload.mime_type,
    )
    if not dup:
        await storage.put_object(f"{doc.id}/raw", raw, content_type=payload.mime_type)
        doc.source_uri = f"local://{doc.id}/raw"
        await db.flush()
        background_tasks.add_task(process_document, doc.id, doc.source_uri)
    return IngestResponse(
        document_id=doc.id,
        sha256=doc.sha256,
        status=doc.status,
        duplicate=dup,
    )
