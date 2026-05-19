"""Tests for the ATT&CK mapper validation logic.

These tests do not call the LLM — they exercise the candidate-validation
path that filters ungrounded / malformed responses.
"""

from __future__ import annotations

from app.llm.attack_mapper import _strip_code_fence, _validate_candidate


def test_validate_drops_non_dict() -> None:
    assert _validate_candidate("T1059", "any text") is None
    assert _validate_candidate(None, "any text") is None
    assert _validate_candidate(42, "any text") is None


def test_validate_drops_bad_technique_id() -> None:
    chunk = "the attacker used PowerShell to download a payload."
    bad = _validate_candidate(
        {"technique_id": "T59", "name": "x", "quote": "PowerShell to download a payload"},
        chunk,
    )
    assert bad is None


def test_validate_drops_paraphrased_quote() -> None:
    chunk = "the attacker used PowerShell to download a payload."
    out = _validate_candidate(
        {
            "technique_id": "T1059",
            "name": "Command and Scripting Interpreter",
            "quote": "the attacker DEPLOYED PowerShell",  # not a substring
            "confidence": 0.8,
        },
        chunk,
    )
    assert out is None


def test_validate_accepts_grounded_candidate() -> None:
    chunk = "the attacker used PowerShell to download a payload."
    out = _validate_candidate(
        {
            "technique_id": "T1059.001",
            "name": "PowerShell",
            "quote": "PowerShell to download",
            "confidence": 0.9,
        },
        chunk,
    )
    assert out is not None
    assert out.technique_id == "T1059.001"
    assert out.confidence == 0.9


def test_validate_clamps_confidence() -> None:
    chunk = "X used Y."
    out = _validate_candidate(
        {"technique_id": "T1059", "name": "x", "quote": "X used Y", "confidence": 5},
        chunk,
    )
    assert out is not None
    assert out.confidence == 1.0

    out2 = _validate_candidate(
        {
            "technique_id": "T1059",
            "name": "x",
            "quote": "X used Y",
            "confidence": -1,
        },
        chunk,
    )
    assert out2 is not None
    assert out2.confidence == 0.0


def test_validate_default_confidence_when_missing() -> None:
    chunk = "X used Y."
    out = _validate_candidate(
        {"technique_id": "T1059", "name": "x", "quote": "X used Y"}, chunk
    )
    assert out is not None
    assert out.confidence == 0.5


def test_strip_code_fence_removes_markdown() -> None:
    body = "```json\n[{\"technique_id\":\"T1059\"}]\n```"
    assert _strip_code_fence(body) == '[{"technique_id":"T1059"}]'


def test_strip_code_fence_passthrough_when_no_fence() -> None:
    body = '[{"technique_id":"T1059"}]'
    assert _strip_code_fence(body) == body
