"""TXT parser — paragraph-segmented plain text with offset preservation."""

from __future__ import annotations

import re

from app.ingestion.types import OffsetEntry, ParsedDocument, Section

_HEADING_RE = re.compile(r"^(?P<text>[A-Z][A-Z0-9 \-/&]{2,80})$", re.MULTILINE)


def parse_txt(text: str, *, language: str = "en", title: str | None = None) -> ParsedDocument:
    """Parse a plain-text report.

    Heuristic section detection: ALL-CAPS lines of 3+ chars are treated as
    headings. Offset map records line starts (sparse, every newline).
    """
    sections: list[Section] = []
    headings = list(_HEADING_RE.finditer(text))
    for i, m in enumerate(headings):
        section_text = m.group("text").strip()
        start = m.start("text")
        end = headings[i + 1].start("text") if i + 1 < len(headings) else len(text)
        sections.append(Section(name=section_text, char_start=start, char_end=end, level=1))

    offset_map: list[OffsetEntry] = []
    line_no = 1
    for i, _ch in enumerate(text):
        if i == 0 or text[i - 1] == "\n":
            offset_map.append(OffsetEntry(char_idx=i, line=line_no))
            line_no += 1

    metadata: dict[str, str] = {}
    if title:
        metadata["title"] = title

    return ParsedDocument(
        text=text,
        sections=sections,
        offset_map=offset_map,
        metadata=metadata,
        source_format="txt",
        language=language,
    )


__all__ = ["parse_txt"]
