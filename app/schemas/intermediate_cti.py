"""Top-level intermediate CTI representation.

This is the canonical in-memory + JSON exchange shape. STIX 2.1 bundles are
built FROM this; raw report text never reaches the STIX builders directly.

The model enforces three closures at validation time:
    1. Every ``Evidence.chunk_id`` resolves to a chunk in ``chunks``.
    2. Every ``IocCandidate.evidence_ids`` resolves to evidence in ``evidence``.
    3. Every chunk's ``(char_start, char_end)`` is internally consistent.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.document import ChunkRef, DocumentMeta
from app.schemas.evidence import Evidence
from app.schemas.ioc import IocCandidate
from app.schemas.provenance import Provenance


class Candidates(BaseModel):
    """Container for extracted candidates.

    Phase 1 ships only ``iocs``. Phase 2 will add ``entities``, ``relations``,
    ``events``, ``attack_mappings``. Adding a field is a schema-version bump.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    iocs: list[IocCandidate] = Field(default_factory=list)


class IntermediateCTI(BaseModel):
    """Full intermediate CTI for a single document."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document: DocumentMeta
    chunks: list[ChunkRef] = Field(min_length=0)
    candidates: Candidates = Field(default_factory=Candidates)
    evidence: list[Evidence] = Field(default_factory=list)
    provenance: Provenance
    version: str = Field(default="2026.05.18", description="Schema version")

    @model_validator(mode="after")
    def _check_closures(self) -> IntermediateCTI:
        chunk_ids = {c.chunk_id for c in self.chunks}
        evidence_ids = {e.evidence_id for e in self.evidence}

        for ev in self.evidence:
            if ev.chunk_id not in chunk_ids:
                msg = f"evidence {ev.evidence_id} references unknown chunk_id {ev.chunk_id!r}"
                raise ValueError(msg)

        for ioc in self.candidates.iocs:
            for eid in ioc.evidence_ids:
                if eid not in evidence_ids:
                    msg = f"ioc {ioc.value!r} references unknown evidence_id {eid!r}"
                    raise ValueError(msg)

        for chunk in self.chunks:
            if chunk.char_end < chunk.char_start:
                msg = f"chunk {chunk.chunk_id} has char_end ({chunk.char_end})" f" < char_start ({chunk.char_start})"
                raise ValueError(msg)

        return self
