"""Tests for the markdown parser (section detection + offsets)."""

from __future__ import annotations

from app.ingestion import parse_markdown


def test_detects_h1_and_h2() -> None:
    md = "# Title\n\nIntro.\n\n## Section A\n\nBody A.\n\n## Section B\n\nBody B.\n"
    doc = parse_markdown(md)
    names = [s.name for s in doc.sections]
    assert "Title" in names
    assert "Section A" in names
    assert "Section B" in names


def test_section_char_ranges_disjoint_at_same_level() -> None:
    md = "## A\n\nbody-a\n\n## B\n\nbody-b\n"
    doc = parse_markdown(md)
    a = next(s for s in doc.sections if s.name == "A")
    b = next(s for s in doc.sections if s.name == "B")
    assert a.char_end <= b.char_start


def test_title_extracted_from_h1() -> None:
    doc = parse_markdown("# CTI Report 2026\n\ncontent\n")
    assert doc.metadata.get("title") == "CTI Report 2026"


def test_offset_round_trip_for_section_text() -> None:
    md = "# Title\n\nFirst paragraph.\n"
    doc = parse_markdown(md)
    title_section = next(s for s in doc.sections if s.name == "Title")
    assert doc.text[title_section.char_start : title_section.char_end].startswith("# Title")
