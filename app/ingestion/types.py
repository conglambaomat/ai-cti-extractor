"""Ingestion types — runtime-free, importable from extractors.

Phase 03 partial: ships only the type contract that Phase 05 (IOC extractor)
and Phase 07 (pipeline orchestrator) depend on. Real parser implementations
(pdfplumber, trafilatura, markdown-it-py, Tesseract) ship later as Phase 03
parsers — they will produce instances of these types.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OffsetEntry(BaseModel):
    """One mapping from char index in extracted text to source position.

    The ingestion layer keeps a *sparse* list of these (one every N chars)
    so that any extracted span can be back-resolved to the original page +
    coordinates. Stored alongside :class:`ParsedDocument`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    char_idx: int = Field(ge=0)
    page: int | None = Field(default=None, ge=1)
    line: int | None = Field(default=None, ge=1)
    x: float | None = None
    y: float | None = None


class Section(BaseModel):
    """A heading-bounded region of the parsed document."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, description="Heading text, e.g. 'Initial Access'")
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    level: int = Field(default=1, ge=1, le=6)

    @model_validator(mode="after")
    def _bounds(self) -> Section:
        if self.char_end < self.char_start:
            msg = f"section {self.name!r}: char_end < char_start"
            raise ValueError(msg)
        return self


SourceFormat = Literal["pdf", "html", "md", "txt", "url"]


class ParsedDocument(BaseModel):
    """Output of any ingestion parser.

    Holds the canonical reading-order text plus a sparse offset map and
    detected sections. Downstream consumers (chunker, IOC extractor, NER
    in Phase 2) operate on ``text`` and resolve provenance via the maps.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    sections: list[Section] = Field(default_factory=list)
    offset_map: list[OffsetEntry] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)
    source_format: SourceFormat
    language: str = Field(default="en", min_length=2, max_length=5)


class Chunk(BaseModel):
    """A single chunk produced by ``app.ingestion.chunking``.

    Phase 05 IOC extractor consumes a stream of these. ``char_start``/``char_end``
    are absolute offsets inside :attr:`ParsedDocument.text` (not chunk-local),
    so any IOC span resolved inside the chunk maps back to a unique document
    position without disambiguation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str = Field(min_length=1, description="Stable id; convention: c-<doc_short>-<index>")
    document_id: str
    section: str | None = None
    page: int | None = Field(default=None, ge=1)
    text: str = Field(min_length=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    token_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _bounds(self) -> Chunk:
        if self.char_end <= self.char_start:
            msg = f"chunk {self.chunk_id}: char_end ({self.char_end}) must be > char_start ({self.char_start})"
            raise ValueError(msg)
        if (self.char_end - self.char_start) != len(self.text):
            msg = (
                f"chunk {self.chunk_id}: text length {len(self.text)} does not match"
                f" offset window {self.char_end - self.char_start}"
            )
            raise ValueError(msg)
        return self
