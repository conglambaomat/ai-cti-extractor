"""ORM models for Phase 1+ schema.

Phase 1 ships:
  * ``Document`` + ``Chunk`` + ``EvidenceSpan``
  * ``IocCandidate``
  * ``StixObject`` + ``StixRelationship``
  * ``ModelRun`` + ``Export``
  * ``AuditLog`` (with hash chain — see :mod:`app.db.audit_chain`)

Phase 2+ adds entities, relations, events, attack_mappings, canonical_entities.
"""

from __future__ import annotations

from app.db.models.audit_log import AuditLog
from app.db.models.base import Base, TimestampMixin, UuidMixin
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.evidence_span import EvidenceSpan
from app.db.models.export import Export
from app.db.models.ioc_candidate import IocCandidate
from app.db.models.model_run import ModelRun
from app.db.models.stix_object import StixObject, StixRelationship

__all__ = [
    "AuditLog",
    "Base",
    "Chunk",
    "Document",
    "EvidenceSpan",
    "Export",
    "IocCandidate",
    "ModelRun",
    "StixObject",
    "StixRelationship",
    "TimestampMixin",
    "UuidMixin",
]
