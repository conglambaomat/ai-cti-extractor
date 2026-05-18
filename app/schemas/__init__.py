"""Pydantic v2 schemas for the intermediate CTI representation.

This package is the canonical internal data model: every extracted fact
lives here first; STIX 2.1 bundles are *built from* this — never from raw
text directly. Strict invariants enforce evidence grounding at the type
level (an ``IocCandidate`` without ``evidence_ids`` cannot be instantiated).
"""

from __future__ import annotations

from app.schemas.document import ChunkRef, DocumentMeta
from app.schemas.evidence import Evidence
from app.schemas.intermediate_cti import Candidates, IntermediateCTI
from app.schemas.ioc import IocCandidate, IocType
from app.schemas.provenance import ExtractorRun, Provenance

__all__ = [
    "Candidates",
    "ChunkRef",
    "DocumentMeta",
    "Evidence",
    "ExtractorRun",
    "IntermediateCTI",
    "IocCandidate",
    "IocType",
    "Provenance",
]
