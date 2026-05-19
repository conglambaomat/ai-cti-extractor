"""Ingestion layer.

Public surface:

    from app.ingestion import (
        Chunk, OffsetEntry, ParsedDocument, Section, SourceFormat,
        dispatch, chunk,
        parse_pdf, parse_html, parse_markdown, parse_txt,
        fetch_url, assert_english, detect_language,
    )

The heavy parser modules import their backends (pdfplumber, trafilatura,
etc.) lazily — importing ``app.ingestion`` is cheap.
"""

from __future__ import annotations

from app.ingestion.chunking import chunk
from app.ingestion.dispatcher import dispatch
from app.ingestion.html_parser import parse_html
from app.ingestion.language import assert_english, detect_language
from app.ingestion.markdown_parser import parse_markdown
from app.ingestion.pdf_parser import parse_pdf
from app.ingestion.txt_parser import parse_txt
from app.ingestion.types import Chunk, OffsetEntry, ParsedDocument, Section, SourceFormat
from app.ingestion.url_fetcher import fetch_url

__all__ = [
    "Chunk",
    "OffsetEntry",
    "ParsedDocument",
    "Section",
    "SourceFormat",
    "assert_english",
    "chunk",
    "detect_language",
    "dispatch",
    "fetch_url",
    "parse_html",
    "parse_markdown",
    "parse_pdf",
    "parse_txt",
]
