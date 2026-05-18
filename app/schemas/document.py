"""Document and chunk metadata used inside ``IntermediateCTI``.

These are *references* — they do not duplicate the full document/chunk row
from the database. Persistence lives in ``app.db.models``; this layer is the
in-memory + JSON exchange representation used by extractors and STIX builders.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DocumentMeta(BaseModel):
    """Identifying metadata about the document currently being processed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(description="UUID of the document row")
    source_uri: str = Field(description="Original URL or file path; redacted when sensitive")
    sha256: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    title: str | None = None
    language: str = Field(default="en", min_length=2, max_length=5)
    ingested_at: datetime
    mime_type: str | None = None
    source_format: Literal["pdf", "html", "md", "txt", "url"] | None = None


class ChunkRef(BaseModel):
    """Lightweight reference to a chunk inside ``app.ingestion.types.Chunk``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str = Field(description="Stable chunk id; convention: c-<doc_short>-<index>")
    section: str | None = Field(default=None, description="Section heading if known")
    page: int | None = Field(default=None, ge=1)
    char_start: int = Field(ge=0, description="Offset inside the source document text")
    char_end: int = Field(ge=0)
    token_count: int = Field(default=0, ge=0)
