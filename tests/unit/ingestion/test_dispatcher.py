"""Tests for the format dispatcher."""

from __future__ import annotations

import pytest
from app.core.exceptions import IngestionError, UnsupportedFormatError
from app.ingestion import dispatch


@pytest.mark.asyncio
async def test_dispatch_markdown_via_mime() -> None:
    md = b"# Title\n\nBody."
    parsed = await dispatch(md, mime_type="text/markdown")
    assert parsed.source_format == "md"


@pytest.mark.asyncio
async def test_dispatch_html_via_mime() -> None:
    html = b"<html><head><title>X</title></head><body><h1>H</h1><p>" + b"a" * 500 + b"</p></body></html>"
    parsed = await dispatch(html, mime_type="text/html")
    assert parsed.source_format == "html"


@pytest.mark.asyncio
async def test_dispatch_pdf_magic_bytes() -> None:
    # Sniff magic bytes; we don't need a valid PDF body for the dispatcher
    # to choose the parser. Parser failure surfaces as IngestionError.
    raw = b"%PDF-1.7\nnot really a PDF"
    with pytest.raises((IngestionError, ValueError)):
        await dispatch(raw)


@pytest.mark.asyncio
async def test_dispatch_unsupported_mime() -> None:
    with pytest.raises(UnsupportedFormatError):
        await dispatch(b"binary blob", mime_type="application/x-msgpack")


@pytest.mark.asyncio
async def test_dispatch_text_fallback_on_unknown_bytes() -> None:
    parsed = await dispatch(b"plain text content with no special markers")
    assert parsed.source_format == "txt"
