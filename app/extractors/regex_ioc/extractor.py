"""Regex IOC extractor — entry point for the rule-based extraction layer.

Phase 1 of the hybrid pipeline: high-precision deterministic extraction of
IPv4/v6, domains, URLs, emails, hashes, CVEs, and ASNs. Every match emits an
:class:`Evidence` row and aggregates into a deduplicated :class:`IocCandidate`.

Public surface:

    extract(chunk) -> ExtractionResult

The extractor is pure — given the same chunk, it produces byte-identical
output. Determinism enables caching and idempotent re-runs.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.extractors.regex_ioc.defang import build_refanged_view
from app.extractors.regex_ioc.normalize import normalize
from app.extractors.regex_ioc.patterns import PATTERNS
from app.extractors.regex_ioc.version import __extractor_id__
from app.ingestion.types import Chunk
from app.schemas.evidence import Evidence
from app.schemas.ioc import IocCandidate, IocType


@dataclass(frozen=True)
class ExtractionResult:
    """Per-chunk extraction output.

    Both lists are pre-deduplicated:
      * ``iocs``: one entry per ``(type, normalized)`` with merged evidence.
      * ``evidence``: one entry per ``(type, original_span)``.
    """

    iocs: list[IocCandidate]
    evidence: list[Evidence]


def _evidence_id(chunk_id: str, abs_start: int, abs_end: int, ioc_type: IocType) -> str:
    """Deterministic Evidence id keyed on the absolute span + type.

    Matches the schema regex ``^e-[0-9a-f]{16,}$`` (we use 32 hex chars).
    Same chunk + span + type across runs ⇒ same evidence_id.
    """
    seed = f"{chunk_id}|{abs_start}|{abs_end}|{ioc_type.value}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]
    return f"e-{digest}"


def extract(chunk: Chunk) -> ExtractionResult:
    """Run all Phase 1 IOC patterns against a single chunk.

    Offsets in returned :class:`Evidence` are absolute (relative to the
    parent ``ParsedDocument.text``), computed as
    ``chunk.char_start + local_offset``.
    """
    view = build_refanged_view(chunk.text)

    candidates: dict[tuple[IocType, str], IocCandidate] = {}
    evidences: dict[tuple[IocType, int, int], Evidence] = {}

    for ioc_type, pattern in PATTERNS.items():
        for match in pattern.finditer(view.refanged):
            local_start, local_end = view.resolve(match.start(), match.end())
            if local_end <= local_start:
                continue

            original_value = chunk.text[local_start:local_end]
            normalized = normalize(ioc_type, match.group(0))
            if normalized is None:
                continue

            abs_start = chunk.char_start + local_start
            abs_end = chunk.char_start + local_end

            evid_key = (ioc_type, abs_start, abs_end)
            if evid_key not in evidences:
                evidences[evid_key] = Evidence(
                    evidence_id=_evidence_id(chunk.chunk_id, abs_start, abs_end, ioc_type),
                    chunk_id=chunk.chunk_id,
                    text_span=original_value,
                    char_start=abs_start,
                    char_end=abs_end,
                )
            evid = evidences[evid_key]

            cand_key = (ioc_type, normalized)
            existing = candidates.get(cand_key)
            if existing is None:
                candidates[cand_key] = IocCandidate(
                    type=ioc_type,
                    value=original_value,
                    normalized=normalized,
                    evidence_ids=[evid.evidence_id],
                    confidence=1.0,
                    extractor=__extractor_id__,
                )
            elif evid.evidence_id not in existing.evidence_ids:
                # Pydantic models are frozen — replace with merged copy
                merged_eids = [*existing.evidence_ids, evid.evidence_id]
                candidates[cand_key] = existing.model_copy(update={"evidence_ids": merged_eids})

    return ExtractionResult(
        iocs=list(candidates.values()),
        evidence=list(evidences.values()),
    )


__all__ = ["ExtractionResult", "extract"]
