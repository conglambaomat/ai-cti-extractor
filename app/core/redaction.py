"""Redaction of secrets / PII before any external LLM call.

Per CLAUDE.md non-negotiable principles, report content is *untrusted* —
treat it as hostile prompt input. Before any external LLM (or even a
local LLM that logs prompts), strip:

  * IPv4 / IPv6 addresses (could leak victim org infra)
  * Email addresses (PII)
  * Common API key patterns (sk-, ghp_, xoxb-, AKIA...)
  * Internal hostnames (.local, .internal, .corp)

The function is *not* a substitute for proper authorization checks. It is
a defence-in-depth layer to limit accidental leakage when an extractor
forwards report text into a tool-calling scope.
"""

from __future__ import annotations

import re

# Order: most specific first to avoid partial matches.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "[REDACTED_OPENAI_KEY]"),
    (re.compile(r"\bghp_[A-Za-z0-9]{30,}\b"), "[REDACTED_GH_PAT]"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]+\b"), "[REDACTED_SLACK_TOKEN]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    (
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "[REDACTED_EMAIL]",
    ),
    (
        re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b"),
        "[REDACTED_IPV4]",
    ),
    (
        re.compile(r"(?<![:.\w])" r"(?:[A-Fa-f0-9]{1,4}:){7}[A-Fa-f0-9]{1,4}" r"(?![:.\w])"),
        "[REDACTED_IPV6]",
    ),
    (re.compile(r"\b[\w-]+\.(?:internal|local|corp|lan|intranet)\b"), "[REDACTED_INTERNAL_HOST]"),
]


def redact_for_external_llm(text: str) -> tuple[str, int]:
    """Return ``(redacted_text, replacement_count)``.

    Idempotent: redacting twice yields the same string and count zero on
    the second pass (unless the input contained the placeholder literal).
    """
    count = 0
    out = text
    for pattern, placeholder in _PATTERNS:
        out, n = pattern.subn(placeholder, out)
        count += n
    return out, count


__all__ = ["redact_for_external_llm"]
