"""Tests for the runtime-free ingestion type contracts."""

from __future__ import annotations

import pytest
from app.ingestion import Chunk, OffsetEntry, ParsedDocument, Section
from pydantic import ValidationError


def test_chunk_text_length_matches_offset_window() -> None:
    chunk = Chunk(
        chunk_id="c-1",
        document_id="00000000-0000-0000-0000-000000000001",
        text="hello world",
        char_start=100,
        char_end=111,
    )
    assert len(chunk.text) == chunk.char_end - chunk.char_start


def test_chunk_rejects_mismatched_offset_window() -> None:
    with pytest.raises(ValidationError, match="does not match"):
        Chunk(
            chunk_id="c-1",
            document_id="d",
            text="hello",
            char_start=0,
            char_end=10,  # window 10 != len("hello")=5
        )


def test_chunk_rejects_inverted_offsets() -> None:
    with pytest.raises(ValidationError, match="char_end"):
        Chunk(
            chunk_id="c-1",
            document_id="d",
            text="x",
            char_start=10,
            char_end=10,
        )


def test_section_rejects_negative_window() -> None:
    with pytest.raises(ValidationError, match="char_end"):
        Section(name="Initial Access", char_start=100, char_end=50)


def test_offset_entry_minimum_fields() -> None:
    entry = OffsetEntry(char_idx=0)
    assert entry.page is None
    assert entry.line is None


def test_parsed_document_round_trip() -> None:
    doc = ParsedDocument(
        text="hello world",
        sections=[Section(name="Intro", char_start=0, char_end=11)],
        offset_map=[OffsetEntry(char_idx=0, page=1)],
        metadata={"title": "Sample"},
        source_format="md",
        language="en",
    )
    payload = doc.model_dump_json()
    restored = ParsedDocument.model_validate_json(payload)
    assert restored.text == "hello world"
    assert restored.source_format == "md"
    assert restored.sections[0].name == "Intro"
