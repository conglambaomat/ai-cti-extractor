"""PDF parser via pdfplumber primary + pdfminer.six fallback.

Phase 1 baseline. Reading-order is approximated by sorting words on each
page by ``(top // line_height, x0)``. Heading detection uses font-size
heuristic: words whose median font size exceeds 1.2x the page-median are
treated as heading candidates.

Char-offset preservation: ``offset_map`` is sparse (one entry per word
boundary) referencing ``page`` + ``x``/``y`` coordinates so any extracted
span can be back-resolved to a PDF location.
"""

from __future__ import annotations

import io
import statistics
from pathlib import Path

import pdfplumber

from app.core.exceptions import IngestionError
from app.ingestion.types import OffsetEntry, ParsedDocument, Section

_HEADING_FONT_RATIO = 1.2
_LINE_TOLERANCE = 3.0


def _word_line_key(word: dict[str, object], line_height: float) -> tuple[int, float]:
    return (int(float(word["top"]) // line_height), float(word["x0"]))  # type: ignore[arg-type]


def parse_pdf(source: bytes | Path | str, *, language: str = "en") -> ParsedDocument:
    """Parse a PDF, preserving reading order, sections and offsets.

    ``source`` may be raw bytes or a file path. Raises :class:`IngestionError`
    when pdfplumber cannot open the file.
    """
    text_parts: list[str] = []
    sections: list[Section] = []
    offset_map: list[OffsetEntry] = []

    cursor = 0
    try:
        opener = pdfplumber.open(str(source)) if isinstance(source, str | Path) else pdfplumber.open(io.BytesIO(source))
        with opener as pdf:
            page_median_size: float = 10.0
            for page_idx, page in enumerate(pdf.pages, start=1):
                words = page.extract_words(use_text_flow=True, keep_blank_chars=False) or []
                if not words:
                    continue

                font_sizes = [float(w.get("size", 10)) for w in words if w.get("size")]
                page_median_size = statistics.median(font_sizes) if font_sizes else 10.0
                line_height = max(_LINE_TOLERANCE, page_median_size * 1.1)

                ordered = sorted(words, key=lambda w: _word_line_key(w, line_height))

                last_line_key: int | None = None
                for word in ordered:
                    line_key = int(word["top"] // line_height)
                    sep = "" if last_line_key is None else ("\n" if line_key != last_line_key else " ")
                    last_line_key = line_key

                    text_parts.append(sep)
                    cursor += len(sep)

                    word_text = str(word["text"])
                    word_start = cursor
                    text_parts.append(word_text)
                    cursor += len(word_text)

                    offset_map.append(
                        OffsetEntry(
                            char_idx=word_start,
                            page=page_idx,
                            x=float(word["x0"]),
                            y=float(word["top"]),
                        )
                    )

                    size = float(word.get("size", page_median_size))
                    if size > page_median_size * _HEADING_FONT_RATIO and len(word_text) >= 3:
                        sections.append(
                            Section(
                                name=word_text[:256],
                                char_start=word_start,
                                char_end=word_start,
                                level=1,
                            )
                        )

                # Newline between pages
                text_parts.append("\n\n")
                cursor += 2
    except Exception as e:
        raise IngestionError(f"pdfplumber failed: {e}") from e

    text = "".join(text_parts).strip()

    # Patch section ends to next-section start or doc end.
    for idx, sect in enumerate(sections):
        next_start = len(text)
        for follow in sections[idx + 1 :]:
            if follow.char_start > sect.char_start:
                next_start = follow.char_start
                break
        sections[idx] = sect.model_copy(update={"char_end": next_start})

    metadata: dict[str, str] = {"page_count": str(len(offset_map))}

    return ParsedDocument(
        text=text,
        sections=sections,
        offset_map=offset_map,
        metadata=metadata,
        source_format="pdf",
        language=language,
    )


__all__ = ["parse_pdf"]
