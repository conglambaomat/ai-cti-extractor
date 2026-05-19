"""Tests for deterministic STIX object IDs (UUIDv5 keyed on stable content)."""

from __future__ import annotations

from app.stix.ids import indicator_id, relationship_id, report_id


def test_indicator_id_deterministic_same_input() -> None:
    a = indicator_id("doc-1", "[ipv4-addr:value = '8.8.8.8']")
    b = indicator_id("doc-1", "[ipv4-addr:value = '8.8.8.8']")
    assert a == b


def test_indicator_id_differs_for_different_pattern() -> None:
    a = indicator_id("doc-1", "[ipv4-addr:value = '8.8.8.8']")
    b = indicator_id("doc-1", "[ipv4-addr:value = '1.1.1.1']")
    assert a != b


def test_indicator_id_differs_for_different_doc() -> None:
    a = indicator_id("doc-1", "[ipv4-addr:value = '8.8.8.8']")
    b = indicator_id("doc-2", "[ipv4-addr:value = '8.8.8.8']")
    assert a != b


def test_report_id_deterministic() -> None:
    assert report_id("doc-x") == report_id("doc-x")


def test_relationship_id_deterministic() -> None:
    a = relationship_id("indicator--1", "indicates", "malware--1")
    b = relationship_id("indicator--1", "indicates", "malware--1")
    assert a == b


def test_relationship_id_differs_when_endpoints_swap() -> None:
    a = relationship_id("indicator--1", "indicates", "malware--1")
    b = relationship_id("malware--1", "indicates", "indicator--1")
    assert a != b


def test_indicator_id_format_canonical() -> None:
    iid = indicator_id("doc-1", "[ipv4-addr:value = '8.8.8.8']")
    assert iid.startswith("indicator--")
    # Body is a uuid (8-4-4-4-12 hex)
    body = iid.split("--", 1)[1]
    assert len(body) == 36
    parts = body.split("-")
    assert [len(p) for p in parts] == [8, 4, 4, 4, 12]
