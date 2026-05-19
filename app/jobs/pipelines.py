"""End-to-end pipeline orchestrator: parse -> chunk -> IOC -> STIX -> persist.

Designed for FastAPI ``BackgroundTasks`` so the HTTP layer can return 202 fast
while extraction runs after the response. Per-phase commits keep the SQLite
write-lock window short. ``document.status`` is the resume cursor.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from typing import Any

import structlog

from app.core.exceptions import (
    AuditChainError,
    IngestionError,
    UnsupportedFormatError,
    UnsupportedLanguageError,
)
from app.db.audit_chain import append as audit_append
from app.db.models.document import Document
from app.db.session import SessionFactory
from app.extractors.regex_ioc.extractor import extract as extract_iocs
from app.extractors.regex_ioc.version import (
    __extractor_id__,
    __extractor_name__,
)
from app.extractors.regex_ioc.version import (
    __version__ as _regex_version,
)
from app.ingestion.chunking import chunk as chunk_text
from app.ingestion.dispatcher import dispatch
from app.ingestion.language import assert_english
from app.ingestion.types import Chunk as ChunkSchema
from app.jobs import persistence
from app.schemas.document import ChunkRef, DocumentMeta
from app.schemas.evidence import Evidence
from app.schemas.intermediate_cti import Candidates, IntermediateCTI
from app.schemas.ioc import IocCandidate
from app.schemas.provenance import ExtractorRun, Provenance
from app.stix.builders import StixBuildError, build_bundle
from app.stix.exporters import bundle_hash
from app.stix.validators import validate as validate_bundle

log = structlog.get_logger(__name__)

_PIPELINE_VERSION = "0.1.0"


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _config_hash(payload: dict[str, Any]) -> str:
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


async def _audit(
    session: Any,
    *,
    action: str,
    document_id: str,
    payload: dict[str, Any] | None = None,
) -> None:
    await audit_append(
        session,
        actor="pipeline",
        action=action,
        target_type="document",
        target_id=document_id,
        payload=payload or {},
    )


async def _set_status(document_id: str, status: str) -> None:
    """Open a fresh session, set status, commit. For terminal/error paths."""
    async with SessionFactory() as session:
        await persistence.set_document_status(session, document_id, status)
        await session.commit()


async def _fetch_for_parse(source_uri: str, mime_type: str | None) -> Any:
    """Resolve a ``source_uri`` into something ``dispatch`` can parse.

    ``local://{doc_id}/raw`` is the API-layer convention for objects in the
    configured storage backend; we resolve it via the storage backend before
    handing bytes to ``dispatch``. Other schemes pass through.
    """
    if source_uri.startswith("local://"):
        from app.core.config import Settings
        from app.storage.local import LocalStorageBackend

        # Re-read settings so test monkeypatches of STORAGE_LOCAL_DIR are honored.
        cfg = Settings()
        key = source_uri[len("local://") :]
        backend = LocalStorageBackend(cfg.STORAGE_LOCAL_DIR)
        data = await backend.get_object(key)
        return await dispatch(data, mime_type=mime_type)
    return await dispatch(source_uri, mime_type=mime_type)


async def process_document(document_id: str, source_uri: str) -> None:
    """Run the full extraction pipeline. Idempotent across re-runs."""
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(document_id=document_id)
    t0 = time.monotonic()

    try:
        # ----------------------------------------------------------- bootstrap
        async with SessionFactory() as session:
            doc = await session.get(Document, document_id)
            if doc is None:
                log.error("pipeline.document_not_found")
                return
            if doc.status in ("complete", "no_iocs"):
                log.info("pipeline.already_done", status=doc.status)
                return
            sha256 = doc.sha256
            title = doc.title
            mime_type = doc.mime_type
            ingested_at = doc.created_at or _utcnow()
            doc.status = "processing"
            await _audit(
                session,
                action="document.accepted",
                document_id=document_id,
                payload={"sha256": sha256, "source_uri": source_uri},
            )
            await session.commit()

        # --------------------------------------------------------------- parse
        try:
            parsed = await _fetch_for_parse(source_uri, mime_type)
            assert_english(parsed.text)
        except (UnsupportedFormatError, UnsupportedLanguageError, IngestionError) as exc:
            await _fail_phase(
                document_id,
                status="failed_parse",
                action="pipeline.parse_failed",
                payload={"error_type": type(exc).__name__, "error_msg": str(exc)},
            )
            return

        async with SessionFactory() as session:
            await persistence.update_doc_after_parse(session, document_id, parsed)
            await _audit(
                session,
                action="pipeline.parse_complete",
                document_id=document_id,
                payload={
                    "char_count": len(parsed.text),
                    "section_count": len(parsed.sections),
                    "language": parsed.language,
                },
            )
            await session.commit()
        log.info("pipeline.parse_complete", duration_ms=_ms(t0))

        # --------------------------------------------------------------- chunk
        chunks: list[ChunkSchema] = chunk_text(parsed, document_id=document_id)
        if not chunks:
            await _fail_phase(
                document_id,
                status="empty",
                action="pipeline.chunk_empty",
                payload={"char_count": len(parsed.text)},
            )
            return

        async with SessionFactory() as session:
            chunk_id_map = await persistence.persist_chunks(
                session, document_id, chunks
            )
            await _audit(
                session,
                action="pipeline.chunk_complete",
                document_id=document_id,
                payload={"chunk_count": len(chunks)},
            )
            await session.commit()
        log.info("pipeline.chunk_complete", chunk_count=len(chunks))

        # --------------------------------------------------------------- iocs
        all_iocs: list[IocCandidate] = []
        all_evidence: list[Evidence] = []
        for c in chunks:
            res = extract_iocs(c)
            all_iocs.extend(res.iocs)
            all_evidence.extend(res.evidence)

        # Persist evidence first (FK dependency for any downstream work)
        async with SessionFactory() as session:
            await persistence.persist_evidence(session, all_evidence, chunk_id_map)
            await session.commit()

        if not all_iocs:
            async with SessionFactory() as session:
                await persistence.set_document_status(
                    session, document_id, "no_iocs"
                )
                await _audit(
                    session,
                    action="pipeline.no_iocs",
                    document_id=document_id,
                    payload={"chunk_count": len(chunks)},
                )
                await session.commit()
            log.info("pipeline.no_iocs_terminal")
            return

        async with SessionFactory() as session:
            await persistence.persist_iocs(session, document_id, all_iocs)
            await persistence.set_document_status(
                session, document_id, "ioc_extracted"
            )
            await _audit(
                session,
                action="pipeline.ioc_complete",
                document_id=document_id,
                payload={
                    "ioc_count": len(all_iocs),
                    "evidence_count": len(all_evidence),
                    "extractor_id": __extractor_id__,
                },
            )
            await session.commit()
        log.info(
            "pipeline.ioc_complete",
            ioc_count=len(all_iocs),
            evidence_count=len(all_evidence),
        )

        # ---------------------------------------------------------- stix build
        ts_started = _utcnow()
        run = ExtractorRun(
            name=__extractor_name__,
            version=_regex_version,
            started_at=ts_started,
            ended_at=_utcnow(),
            config_hash=_config_hash({"patterns": "default", "v": _regex_version}),
        )
        provenance = Provenance(
            extractors=[run], pipeline_version=_PIPELINE_VERSION
        )
        document_meta = DocumentMeta(
            id=document_id,
            source_uri=source_uri,
            sha256=sha256,
            title=title,
            language="en",
            ingested_at=ingested_at,
            mime_type=mime_type,
            source_format=parsed.source_format,
        )
        chunk_refs = [
            ChunkRef(
                chunk_id=c.chunk_id,
                section=c.section,
                page=c.page,
                char_start=c.char_start,
                char_end=c.char_end,
                token_count=c.token_count,
            )
            for c in chunks
        ]
        try:
            cti = IntermediateCTI(
                document=document_meta,
                chunks=chunk_refs,
                candidates=Candidates(iocs=all_iocs),
                evidence=all_evidence,
                provenance=provenance,
            )
            stix_bundle = build_bundle(cti)
        except StixBuildError as exc:
            # Phase 06 raises this when no buildable indicators exist (e.g.,
            # CVE-only). Map to ``no_iocs`` because no STIX value was produced.
            log.info("pipeline.stix_no_indicators", reason=str(exc))
            async with SessionFactory() as session:
                await persistence.set_document_status(
                    session, document_id, "no_iocs"
                )
                await _audit(
                    session,
                    action="pipeline.no_iocs",
                    document_id=document_id,
                    payload={"reason": "no_buildable_indicators"},
                )
                await session.commit()
            return

        result = validate_bundle(cti, stix_bundle)
        if not result.is_valid:
            await _fail_phase(
                document_id,
                status="failed_stix",
                action="pipeline.stix_validation_failed",
                payload={
                    "issues": [issue.model_dump() for issue in result.issues][:50]
                },
            )
            return

        bhash = bundle_hash(stix_bundle)
        bundle_dict = json.loads(stix_bundle.serialize())
        async with SessionFactory() as session:
            await persistence.persist_stix(session, document_id, bundle_dict)
            await persistence.set_document_status(
                session, document_id, "stix_built"
            )
            await persistence.record_model_run(
                session,
                document_id=document_id,
                model="pipeline",
                version=_PIPELINE_VERSION,
                input_hash=sha256,
                output_hash=bhash,
                started_at=ts_started,
                ended_at=_utcnow(),
            )
            await _audit(
                session,
                action="pipeline.stix_complete",
                document_id=document_id,
                payload={
                    "bundle_hash": bhash,
                    "stix_object_count": len(bundle_dict.get("objects", [])),
                },
            )
            await session.commit()

        # ---------------------------------------------------- terminal success
        async with SessionFactory() as session:
            await persistence.set_document_status(session, document_id, "complete")
            await _audit(
                session,
                action="pipeline.complete",
                document_id=document_id,
                payload={"bundle_hash": bhash, "duration_ms": _ms(t0)},
            )
            await session.commit()
        log.info("pipeline.complete", total_duration_ms=_ms(t0))

    except AuditChainError:
        log.critical("pipeline.audit_chain_error", alert=True)
        await _set_status(document_id, "audit_chain_error")
        raise
    except Exception:
        log.exception("pipeline.unhandled_error")
        try:
            await _set_status(document_id, "failed")
        except Exception:
            log.exception("pipeline.status_update_failed_after_error")
    finally:
        structlog.contextvars.clear_contextvars()


async def _fail_phase(
    document_id: str,
    *,
    status: str,
    action: str,
    payload: dict[str, Any],
) -> None:
    """Set status + write audit row in one mini-transaction."""
    async with SessionFactory() as session:
        await persistence.set_document_status(session, document_id, status)
        await _audit(
            session, action=action, document_id=document_id, payload=payload
        )
        await session.commit()


__all__ = ["process_document"]
