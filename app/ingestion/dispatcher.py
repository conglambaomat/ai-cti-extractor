"""Format dispatcher: route raw bytes / paths / URLs to the right parser.

Decision matrix:
    - explicit ``mime_type``      -> direct route
    - file extension              -> known parser
    - URL                         -> fetch then re-dispatch
    - magic-byte sniffing fallback (PDF starts with ``%PDF-``)
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.exceptions import UnsupportedFormatError
from app.ingestion.html_parser import parse_html
from app.ingestion.markdown_parser import parse_markdown
from app.ingestion.pdf_parser import parse_pdf
from app.ingestion.txt_parser import parse_txt
from app.ingestion.types import ParsedDocument
from app.ingestion.url_fetcher import fetch_url

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def _decode_text(raw: bytes) -> str:
    """Decode bytes as UTF-8 with replacement on bad bytes."""
    return raw.decode("utf-8", errors="replace")


def _dispatch_bytes(raw: bytes, mime: str | None) -> ParsedDocument:
    if mime:
        if mime.startswith("application/pdf"):
            return parse_pdf(raw)
        if mime.startswith(("text/html", "application/xhtml")):
            return parse_html(_decode_text(raw))
        if mime.startswith(("text/markdown", "text/x-markdown")):
            return parse_markdown(_decode_text(raw))
        if mime.startswith("text/plain"):
            return parse_txt(_decode_text(raw))
        if mime.startswith("text/"):
            return parse_txt(_decode_text(raw))
        msg = f"unsupported mime_type {mime!r}"
        raise UnsupportedFormatError(msg)

    if raw.startswith(b"%PDF-"):
        return parse_pdf(raw)
    text = _decode_text(raw)
    if text.lstrip().startswith("<"):
        return parse_html(text)
    return parse_txt(text)


async def dispatch(
    source: bytes | str | Path,
    *,
    mime_type: str | None = None,
) -> ParsedDocument:
    """Route ``source`` to the correct parser.

    ``source`` may be:
        * raw bytes — paired with ``mime_type`` or sniffed
        * URL string — fetched then re-dispatched
        * file path (Path or str) — extension drives the parser

    Async because URL fetching is async; non-URL paths run synchronously.
    """
    if isinstance(source, str) and _URL_RE.match(source):
        content, mime = await fetch_url(source)
        return _dispatch_bytes(content, mime)

    if isinstance(source, str | Path):
        path = Path(source)
        if not path.exists():
            msg = f"file not found: {path}"
            raise UnsupportedFormatError(msg)
        ext = path.suffix.lower()
        if ext == ".pdf":
            return parse_pdf(path)
        if ext in {".html", ".htm"}:
            return parse_html(path.read_text(encoding="utf-8", errors="replace"))
        if ext in {".md", ".markdown"}:
            return parse_markdown(path.read_text(encoding="utf-8", errors="replace"))
        if ext in {".txt", ""}:
            return parse_txt(path.read_text(encoding="utf-8", errors="replace"))
        msg = f"unsupported extension {ext!r}"
        raise UnsupportedFormatError(msg)

    return _dispatch_bytes(source, mime_type)


__all__ = ["dispatch"]
