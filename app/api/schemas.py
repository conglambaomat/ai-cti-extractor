"""HTTP request/response models for the API surface.

Pydantic v2; all frozen + ``extra="forbid"`` to keep the contract honest.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    status: Literal["ok"] = "ok"
    env: str
    version: str = "0.1.0"


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


class IngestUrlRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    url: str = Field(min_length=8, max_length=4096)
    mime_type: str | None = None
    title: str | None = Field(default=None, max_length=1024)


class IngestInlineRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    content: str = Field(min_length=1, max_length=2_000_000)
    mime_type: str = Field(default="text/markdown")
    title: str | None = Field(default=None, max_length=1024)


class IngestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str
    sha256: str
    status: str
    duplicate: bool = False


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


class DocumentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    source_uri: str
    sha256: str
    title: str | None
    language: str
    mime_type: str | None
    source_format: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    chunk_count: int = 0
    ioc_count: int = 0
    stix_object_count: int = 0


class ChunkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    section: str | None
    char_start: int
    char_end: int
    length: int


class IocResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: str
    value: str
    normalized: str
    confidence: float
    evidence_ids: list[str]


class ExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str
    status: str
    ioc_count: int
    evidence_count: int
    iocs: list[IocResponse]


class ExtractTriggerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str
    status: str


# ---------------------------------------------------------------------------
# STIX
# ---------------------------------------------------------------------------


class StixValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bundle: dict[str, Any]


class StixValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    layer: str
    code: str
    message: str
    target_id: str | None = None


class StixValidateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_valid: bool
    parse_ok: bool
    semantic_ok: bool
    issues: list[StixValidationIssue]


# ---------------------------------------------------------------------------
# ATT&CK candidates (Phase 09 — LLM judge)
# ---------------------------------------------------------------------------


class AttackCandidateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chunk_id: str
    technique_id: str
    name: str
    quote: str
    confidence: float


class AttackMappingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str
    chunks_considered: int
    candidates: list[AttackCandidateResponse]
    cache_hits: int
    input_tokens: int
    output_tokens: int


__all__ = [
    "AttackCandidateResponse",
    "AttackMappingResponse",
    "ChunkResponse",
    "DocumentResponse",
    "ExtractTriggerResponse",
    "ExtractionResponse",
    "HealthResponse",
    "IngestInlineRequest",
    "IngestResponse",
    "IngestUrlRequest",
    "IocResponse",
    "StixValidateRequest",
    "StixValidateResponse",
    "StixValidationIssue",
]
