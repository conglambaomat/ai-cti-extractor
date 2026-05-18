"""Ingestion package.

Phase 03 ships in two stages:

1. **Types-only** (this commit): runtime-free Pydantic models that downstream
   extractors and orchestrators can import without pulling pdfplumber,
   Tesseract, trafilatura, etc.
2. **Parsers** (subsequent commit on this phase branch): real implementations
   of PDF/HTML/MD/TXT/URL parsers + chunker + OCR + language gate.

Importing ``app.ingestion`` is intentionally cheap; the heavy parser modules
are loaded lazily inside their own submodules.
"""

from __future__ import annotations

from app.ingestion.types import Chunk, OffsetEntry, ParsedDocument, Section, SourceFormat

__all__ = [
    "Chunk",
    "OffsetEntry",
    "ParsedDocument",
    "Section",
    "SourceFormat",
]
