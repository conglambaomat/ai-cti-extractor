"""HTML parser via trafilatura primary + BeautifulSoup fallback.

Trafilatura strips nav/footer/ad content reliably on vendor blogs (Mandiant,
Talos, etc.). The cleaned text loses the original byte offsets, so the
parser records offsets in the *cleaned* text — analysts can audit via
``metadata['source_html_len']`` to confirm extraction ratio.

Fallback to BeautifulSoup runs when trafilatura returns empty (rare on CTI
vendor sites; happens on JS-rendered SPA pages).
"""

from __future__ import annotations

import re

import trafilatura
from bs4 import BeautifulSoup, Tag

from app.ingestion.types import OffsetEntry, ParsedDocument, Section

_HEADING_TAG_RE = re.compile(r"^h([1-6])$")


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def _fallback_with_bs4(html: str) -> tuple[str, list[Section], dict[str, str]]:
    """Last-resort extractor: take <main>, <article>, or <body>.

    Strips <script>, <style>, <nav>, <header>, <footer>, <aside>.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()

    root_candidate = soup.find("main") or soup.find("article") or soup.body or soup
    # Treat root as a Tag so .descendants typechecks; fall back to the soup.
    root: Tag = root_candidate if isinstance(root_candidate, Tag) else soup

    sections: list[Section] = []
    parts: list[str] = []
    cursor = 0
    for el in root.descendants:
        if not isinstance(el, Tag):
            continue
        m = _HEADING_TAG_RE.match(el.name)
        text = el.get_text(" ", strip=True)
        if not text:
            continue
        if m is not None:
            level = int(m.group(1))
            section_start = cursor
            sections.append(Section(name=text[:256], char_start=section_start, char_end=section_start, level=level))
        parts.append(text)
        parts.append("\n\n")
        cursor += len(text) + 2

    body_text = "".join(parts).strip()

    # Patch section.char_end to next sibling at <= level start.
    for idx, sect in enumerate(sections):
        next_start = len(body_text)
        for follow in sections[idx + 1 :]:
            if follow.level <= sect.level:
                next_start = follow.char_start
                break
        sections[idx] = sect.model_copy(update={"char_end": next_start})

    metadata: dict[str, str] = {}
    if soup.title and soup.title.string:
        metadata["title"] = soup.title.string.strip()
    return body_text, sections, metadata


def parse_html(html: str, *, language: str = "en") -> ParsedDocument:
    """Parse HTML to clean text + sections."""
    metadata: dict[str, str] = {"source_html_len": str(len(html))}
    sections: list[Section] = []
    text: str

    try:
        extracted = trafilatura.extract(
            html,
            output_format="markdown",
            include_tables=True,
            include_links=False,
            with_metadata=False,
            favor_recall=True,
        )
    except Exception:
        extracted = None

    if extracted and len(extracted.strip()) >= 200:
        text = extracted
        # Re-detect headings from markdown-style ``# Heading``.
        for m in re.finditer(r"^(#+)\s+(?P<name>.+?)$", text, flags=re.MULTILINE):
            level = len(m.group(1))
            sections.append(
                Section(name=m.group("name").strip()[:256], char_start=m.start(), char_end=len(text), level=level)
            )
        # Patch section ends.
        for idx, sect in enumerate(sections):
            next_start = len(text)
            for follow in sections[idx + 1 :]:
                if follow.level <= sect.level:
                    next_start = follow.char_start
                    break
            sections[idx] = sect.model_copy(update={"char_end": next_start})
    else:
        text, sections, fallback_meta = _fallback_with_bs4(html)
        metadata.update(fallback_meta)
        metadata["extractor"] = "beautifulsoup_fallback"

    starts = _line_starts(text)
    offset_map = [OffsetEntry(char_idx=s, line=ln + 1) for ln, s in enumerate(starts)]

    return ParsedDocument(
        text=text,
        sections=sections,
        offset_map=offset_map,
        metadata=metadata,
        source_format="html",
        language=language,
    )


__all__ = ["parse_html"]
