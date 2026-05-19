"""Section-aware chunking with offset preservation.

Splits a :class:`ParsedDocument` into Pydantic :class:`Chunk` records that
respect section boundaries (chunks don't span heading transitions) and
target a configurable size (default 800 chars, 200 overlap).
"""

from __future__ import annotations

from collections.abc import Iterable

from app.ingestion.types import Chunk, ParsedDocument, Section

_DEFAULT_TARGET_CHARS = 800
_DEFAULT_OVERLAP = 200
_MIN_CHUNK_CHARS = 50


def _section_for_offset(sections: list[Section], offset: int) -> str | None:
    """Return the deepest section name covering ``offset``."""
    deepest: tuple[int, str] | None = None
    for s in sections:
        if s.char_start <= offset < s.char_end and (deepest is None or s.level > deepest[0]):
            deepest = (s.level, s.name)
    return deepest[1] if deepest else None


def _section_windows(text: str, sections: list[Section]) -> list[tuple[int, int]]:
    """Return list of (start, end) windows, one per section + leading prelude."""
    if not sections:
        return [(0, len(text))]
    windows: list[tuple[int, int]] = []
    cursor = 0
    for s in sorted(sections, key=lambda x: x.char_start):
        if s.char_start > cursor:
            windows.append((cursor, s.char_start))
        windows.append((s.char_start, s.char_end))
        cursor = s.char_end
    if cursor < len(text):
        windows.append((cursor, len(text)))
    return windows


def _slide_chunks(
    text: str,
    *,
    window_start: int,
    window_end: int,
    target: int,
    overlap: int,
) -> Iterable[tuple[int, int]]:
    """Yield (chunk_start, chunk_end) tuples within a window."""
    if window_end - window_start <= 0:
        return
    if window_end - window_start <= target:
        yield (window_start, window_end)
        return

    pos = window_start
    while pos < window_end:
        end = min(pos + target, window_end)
        yield (pos, end)
        if end >= window_end:
            return
        pos = max(pos + 1, end - overlap)


def chunk(
    parsed: ParsedDocument,
    *,
    document_id: str,
    target_chars: int = _DEFAULT_TARGET_CHARS,
    overlap_chars: int = _DEFAULT_OVERLAP,
) -> list[Chunk]:
    """Slice ``parsed.text`` into :class:`Chunk` records.

    Boundary rules:
        * No chunk spans a section transition (we walk section windows).
        * Chunks below ``_MIN_CHUNK_CHARS`` are dropped (not worth IOC scan).
        * Chunk char_start/end are absolute offsets in ``parsed.text``.
    """
    out: list[Chunk] = []
    idx = 0
    text = parsed.text
    if not text:
        return out

    windows = _section_windows(text, parsed.sections)

    for win_start, win_end in windows:
        for c_start, c_end in _slide_chunks(
            text,
            window_start=win_start,
            window_end=win_end,
            target=target_chars,
            overlap=overlap_chars,
        ):
            slice_text = text[c_start:c_end]
            if len(slice_text) < _MIN_CHUNK_CHARS:
                continue
            section = _section_for_offset(parsed.sections, c_start)
            out.append(
                Chunk(
                    chunk_id=f"c-{document_id[:8]}-{idx:04d}",
                    document_id=document_id,
                    section=section,
                    page=None,
                    text=slice_text,
                    char_start=c_start,
                    char_end=c_end,
                    token_count=0,
                )
            )
            idx += 1
    return out


__all__ = ["chunk"]
