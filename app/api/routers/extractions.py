"""Read-only access to extracted IOCs + evidence + LLM-driven ATT&CK candidates."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.api.schemas import (
    AttackCandidateResponse,
    AttackMappingResponse,
    ExtractionResponse,
    IocResponse,
)
from app.core.exceptions import AppError
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.evidence_span import EvidenceSpan
from app.db.models.ioc_candidate import IocCandidate
from app.llm.attack_mapper import LlmConfigError, map_chunk_to_attack

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


@router.post("/{doc_id}/attack-candidates", response_model=AttackMappingResponse)
async def attack_candidates(
    doc_id: str, db: DbSession, max_chunks: int = 5
) -> AttackMappingResponse:
    """Run the LLM ATT&CK mapper across the document's chunks.

    Caps chunk count to keep token spend bounded; default top-5 by char_start
    so the head of the report (where context is densest) is always included.
    """
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")

    chunks = (
        await db.execute(
            select(Chunk)
            .where(Chunk.document_id == doc_id)
            .order_by(Chunk.char_start)
            .limit(max_chunks)
        )
    ).scalars().all()
    if not chunks:
        raise HTTPException(status_code=409, detail="document has no chunks")

    iocs = (
        await db.execute(
            select(IocCandidate).where(IocCandidate.document_id == doc_id)
        )
    ).scalars().all()
    ioc_summary = ", ".join(f"{i.type}={i.normalized}" for i in iocs[:20]) or "(none)"

    out: list[AttackCandidateResponse] = []
    cached_total = 0
    in_tok = 0
    out_tok = 0
    try:
        for chunk in chunks:
            result = await asyncio.to_thread(
                map_chunk_to_attack, chunk.text, ioc_summary=ioc_summary
            )
            cached_total += int(result.cached)
            in_tok += result.input_tokens
            out_tok += result.output_tokens
            for cand in result.candidates:
                out.append(
                    AttackCandidateResponse(
                        chunk_id=chunk.id,
                        technique_id=cand.technique_id,
                        name=cand.name,
                        quote=cand.quote,
                        confidence=cand.confidence,
                    )
                )
    except LlmConfigError as e:
        raise HTTPException(
            status_code=503,
            detail=f"LLM not configured: {e}",
        ) from e
    except AppError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    return AttackMappingResponse(
        document_id=doc_id,
        chunks_considered=len(chunks),
        candidates=out,
        cache_hits=cached_total,
        input_tokens=in_tok,
        output_tokens=out_tok,
    )
