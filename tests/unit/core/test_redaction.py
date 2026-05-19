"""Tests for ``app.core.redaction.redact_for_external_llm``."""

from __future__ import annotations

import pytest
from app.core.redaction import redact_for_external_llm


def test_redacts_ipv4() -> None:
    out, n = redact_for_external_llm("connect to 8.8.8.8 now")
    assert "[REDACTED_IPV4]" in out
    assert "8.8.8.8" not in out
    assert n == 1


def test_redacts_email() -> None:
    out, n = redact_for_external_llm("contact admin@example.com")
    assert "[REDACTED_EMAIL]" in out
    assert n == 1


def test_redacts_openai_key() -> None:
    out, n = redact_for_external_llm("token: sk-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    assert "[REDACTED_OPENAI_KEY]" in out
    assert n == 1


def test_redacts_github_pat() -> None:
    out, n = redact_for_external_llm("token=ghp_abcdefghijklmnopqrstuvwxyz0123456789")
    assert "[REDACTED_GH_PAT]" in out
    assert n == 1


def test_redacts_aws_key() -> None:
    out, n = redact_for_external_llm("AWS_KEY=AKIAIOSFODNN7EXAMPLE")
    assert "[REDACTED_AWS_KEY]" in out


def test_redacts_internal_host() -> None:
    out, n = redact_for_external_llm("ssh proxy.internal")
    assert "[REDACTED_INTERNAL_HOST]" in out
    assert n == 1


def test_idempotent_on_second_pass() -> None:
    text = "ip 1.2.3.4 mail a@b.com"
    once, n1 = redact_for_external_llm(text)
    twice, n2 = redact_for_external_llm(once)
    assert once == twice
    assert n1 == 2
    assert n2 == 0


def test_clean_text_unchanged() -> None:
    out, n = redact_for_external_llm("nothing sensitive here")
    assert out == "nothing sensitive here"
    assert n == 0


@pytest.mark.parametrize(
    ("inp", "expected_count"),
    [
        ("ip 8.8.8.8 ip 1.1.1.1", 2),
        ("a@b.com c@d.com e@f.com", 3),
    ],
)
def test_counts_multiple_matches(inp: str, expected_count: int) -> None:
    _, n = redact_for_external_llm(inp)
    assert n == expected_count
