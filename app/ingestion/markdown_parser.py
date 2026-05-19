"""Markdown parser via markdown-it-py.

Uses markdown-it's token stream which carries ``map=[start_line, end_line]``
per block, letting us preserve offsets by line index without rendering HTML.
"""

from __future__ import annotations

from markdown_it import MarkdownIt

from app.ingestion.types import OffsetEntry, ParsedDocument, Section


def _line_starts(text: str) -> list[int]:
    """Char index where each line begins (1-indexed line numbers)."""
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def parse_markdown(source: str, *, language: str = "en") -> ParsedDocument:
    """Parse a Markdown document, preserving heading sections + char offsets.

    Heading detection uses native markdown-it tokens (``heading_open`` / inline
    text). Section boundary is from the heading char_start to the start of
    the next sibling heading at the same level (or end of text).
    """
    md = MarkdownIt("commonmark")
    tokens = md.parse(source)
    starts = _line_starts(source)

    sections: list[Section] = []
    headings: list[Section] = []
    title: str | None = None

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.type == "heading_open" and tok.map is not None:
            level = int(tok.tag[1:])  # e.g., "h2" -> 2
            text_tok = tokens[i + 1] if i + 1 < len(tokens) else None
            text_value = (text_tok.content if text_tok is not None else "").strip()

            char_start = starts[tok.map[0]]
            # End is provisional; we patch when we see the next sibling heading.
            char_end = len(source)
            sect = Section(name=text_value or "Untitled", char_start=char_start, char_end=char_end, level=level)
            headings.append(sect)

            if title is None and level == 1:
                title = text_value
        i += 1

    # Patch char_end of each heading to the next heading at <= level start.
    for idx, sect in enumerate(headings):
        next_start = len(source)
        for follow in headings[idx + 1 :]:
            if follow.level <= sect.level:
                next_start = follow.char_start
                break
        sections.append(
            Section(
                name=sect.name,
                char_start=sect.char_start,
                char_end=next_start,
                level=sect.level,
            )
        )

    offset_map = [OffsetEntry(char_idx=start, line=line_no + 1) for line_no, start in enumerate(starts)]

    metadata: dict[str, str] = {}
    if title is not None:
        metadata["title"] = title

    return ParsedDocument(
        text=source,
        sections=sections,
        offset_map=offset_map,
        metadata=metadata,
        source_format="md",
        language=language,
    )


__all__ = ["parse_markdown"]
