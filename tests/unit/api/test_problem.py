"""Tests for the Problem (RFC 7807) envelope."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.problem import Problem, make_problem


def test_problem_required_fields() -> None:
    p = make_problem(
        title="Bad",
        status=400,
        detail="reason",
        instance="/x#cid",
        correlation_id="cid",
        error_code="BadError",
    )
    dumped = p.model_dump()
    assert set(dumped) == {
        "type", "title", "status", "detail",
        "instance", "correlation_id", "error_code",
    }
    assert dumped["type"] == "about:blank"


def test_problem_with_type_slug() -> None:
    p = make_problem(
        title="Bad",
        status=415,
        detail="x",
        instance="/x#cid",
        correlation_id="cid",
        error_code="UnsupportedFormatError",
        type_slug="unsupported-format",
    )
    assert p.type.endswith("/errors/unsupported-format")


def test_problem_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Problem(  # type: ignore[call-arg]
            title="x", status=400, detail="x",
            instance="/x", correlation_id="c", error_code="E",
            sneaky="leak",  # extra=forbid
        )


def test_problem_rejects_status_below_400() -> None:
    with pytest.raises(ValidationError):
        Problem(
            title="x", status=200, detail="x",
            instance="/x", correlation_id="c", error_code="E",
        )


def test_problem_rejects_status_above_599() -> None:
    with pytest.raises(ValidationError):
        Problem(
            title="x", status=600, detail="x",
            instance="/x", correlation_id="c", error_code="E",
        )


def test_problem_is_frozen() -> None:
    p = make_problem(
        title="x", status=500, detail="x",
        instance="/x", correlation_id="c", error_code="E",
    )
    with pytest.raises(ValidationError):
        p.title = "tampered"  # type: ignore[misc]
