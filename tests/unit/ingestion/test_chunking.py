"""Tests for section-aware chunking with offset preservation."""

from __future__ import annotations

from app.ingestion import Chunk, chunk, parse_markdown


def _doc_id() -> str:
    return "00000000-0000-0000-0000-000000000001"


def test_chunk_text_round_trips_to_parent_text() -> None:
    md = "# Title\n\n" + ("body sentence. " * 100)
    parsed = parse_markdown(md)
    chunks = chunk(parsed, document_id=_doc_id(), target_chars=400, overlap_chars=80)
    assert chunks
    for c in chunks:
        assert parsed.text[c.char_start : c.char_end] == c.text


def test_chunks_inherit_section_name() -> None:
    md = "# Title\n\n" "## Initial Access\n\n" + ("alpha beta gamma. " * 60) + "\n\n## Persistence\n\n" + (
        "zeta eta theta. " * 60
    )
    parsed = parse_markdown(md)
    chunks = chunk(parsed, document_id=_doc_id(), target_chars=300, overlap_chars=60)
    sections_seen = {c.section for c in chunks if c.section}
    assert "Initial Access" in sections_seen
    assert "Persistence" in sections_seen


def test_short_text_yields_one_chunk() -> None:
    parsed = parse_markdown(
        "# Title\n\nA small body of text under target but long enough to clear the minimum chunk threshold."
    )
    chunks = chunk(parsed, document_id=_doc_id(), target_chars=400)
    assert len(chunks) == 1


def test_empty_text_yields_no_chunks() -> None:
    parsed = parse_markdown("")
    chunks = chunk(parsed, document_id=_doc_id())
    assert chunks == []


def test_chunk_overlap_creates_continuation() -> None:
    md = "alpha. " * 200
    parsed = parse_markdown(md)
    chunks = chunk(parsed, document_id=_doc_id(), target_chars=400, overlap_chars=100)
    assert len(chunks) > 1
    # Adjacent chunks should overlap by ~100 chars
    overlap_seen = chunks[0].char_end - chunks[1].char_start
    assert overlap_seen > 0


def test_chunk_window_invariant() -> None:
    md = "alpha. " * 200
    parsed = parse_markdown(md)
    chunks = chunk(parsed, document_id=_doc_id(), target_chars=400, overlap_chars=100)
    for c in chunks:
        assert isinstance(c, Chunk)
        assert c.char_end - c.char_start == len(c.text)
