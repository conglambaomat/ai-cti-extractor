"""Read-only access to extracted IOCs + evidence."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.api.schemas import ExtractionResponse, IocResponse
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.evidence_span import EvidenceSpan
from app.db.models.ioc_candidate import IocCandidate

router = APIRouter()


@router.get("/{doc_id}", response_model=ExtractionResponse)
async def get_extraction(doc_id: str, db: DbSession) -> ExtractionResponse:
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")

    iocs = (
        await db.execute(
            select(IocCandidate)
            .where(IocCandidate.document_id == doc_id)
            .order_by(IocCandidate.type, IocCandidate.normalized)
        )
    ).scalars().all()
    # Count distinct evidence rows for this document via the chunk join.
    evidence_count = (
        await db.execute(
            select(func.count(EvidenceSpan.id))
            .select_from(EvidenceSpan)
            .join(Chunk, EvidenceSpan.chunk_id == Chunk.id)
            .where(Chunk.document_id == doc_id)
        )
    ).scalar_one()

    return ExtractionResponse(
        document_id=doc.id,
        status=doc.status,
        ioc_count=len(iocs),
        evidence_count=int(evidence_count),
        iocs=[
            IocResponse(
                id=row.id,
                type=row.type,
                value=row.value,
                normalized=row.normalized,
                confidence=float(row.confidence),
                evidence_ids=list(row.evidence_ids or []),
            )
            for row in iocs
        ],
    )
