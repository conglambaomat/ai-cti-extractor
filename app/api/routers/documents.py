"""Document inspection endpoints."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import DbSession, Storage
from app.api.schemas import (
    ChunkResponse,
    DocumentResponse,
    ExtractTriggerResponse,
)
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.ioc_candidate import IocCandidate
from app.db.models.stix_object import StixObject
from app.jobs.pipelines import process_document

router = APIRouter()


async def _doc_or_404(db: DbSession, doc_id: str) -> Document:
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    return doc


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(doc_id: str, db: DbSession) -> DocumentResponse:
    doc = await _doc_or_404(db, doc_id)
    chunk_count = (
        await db.execute(
            select(func.count()).select_from(Chunk).where(Chunk.document_id == doc_id)
        )
    ).scalar_one()
    ioc_count = (
        await db.execute(
            select(func.count())
            .select_from(IocCandidate)
            .where(IocCandidate.document_id == doc_id)
        )
    ).scalar_one()
    stix_count = (
        await db.execute(
            select(func.count())
            .select_from(StixObject)
            .where(StixObject.document_id == doc_id)
        )
    ).scalar_one()
    return DocumentResponse(
        id=doc.id,
        source_uri=doc.source_uri,
        sha256=doc.sha256,
        title=doc.title,
        language=doc.language,
        mime_type=doc.mime_type,
        source_format=doc.source_format,
        status=doc.status,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        chunk_count=int(chunk_count),
        ioc_count=int(ioc_count),
        stix_object_count=int(stix_count),
    )


@router.get("/{doc_id}/chunks", response_model=list[ChunkResponse])
async def list_chunks(
    doc_id: str,
    db: DbSession,
    limit: int = 50,
    offset: int = 0,
) -> list[ChunkResponse]:
    await _doc_or_404(db, doc_id)
    rows = (
        await db.execute(
            select(Chunk)
            .where(Chunk.document_id == doc_id)
            .order_by(Chunk.char_start)
            .limit(min(limit, 500))
            .offset(max(offset, 0))
        )
    ).scalars().all()
    return [
        ChunkResponse(
            id=r.id,
            section=r.section,
            char_start=r.char_start,
            char_end=r.char_end,
            length=r.char_end - r.char_start,
        )
        for r in rows
    ]


@router.post(
    "/{doc_id}/extract",
    response_model=ExtractTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_extract(
    doc_id: str,
    db: DbSession,
    storage: Storage,
    background_tasks: BackgroundTasks,
) -> ExtractTriggerResponse:
    """Re-trigger the pipeline for an existing document.

    Idempotent at the orchestrator level — completed phases are skipped.
    """
    doc = await _doc_or_404(db, doc_id)
    background_tasks.add_task(process_document, doc.id, doc.source_uri)
    return ExtractTriggerResponse(document_id=doc.id, status=doc.status)
