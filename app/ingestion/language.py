"""Language gate at the ingestion boundary.

Public CTI corpus is English-only (per CLAUDE.md scope). Non-English
inputs are rejected here, before any extractor sees them. ``langdetect`` is
deterministic when seeded.

Exposes :func:`assert_english` which raises :class:`UnsupportedLanguageError`
on non-English (with override flag for technical English misclassified due
to heavy non-Latin code blocks).
"""

from __future__ import annotations

from langdetect import DetectorFactory, detect_langs
from langdetect.lang_detect_exception import LangDetectException

from app.core.exceptions import UnsupportedLanguageError

# Deterministic seed: langdetect uses random Markov chains otherwise,
# which makes tests flaky.
DetectorFactory.seed = 0


# Sample at most this many chars to avoid long detection on huge documents.
_SAMPLE_LIMIT = 5000


def detect_language(text: str) -> str:
    """Best-effort ISO-639-1 code. Returns ``"und"`` on detection failure."""
    sample = text.strip()[:_SAMPLE_LIMIT]
    if not sample:
        return "und"
    try:
        ranked = detect_langs(sample)
    except LangDetectException:
        return "und"
    return str(ranked[0].lang)


def assert_english(text: str, *, force_override: bool = False) -> str:
    """Raise :class:`UnsupportedLanguageError` if the text is not English.

    Returns the detected ISO-639-1 code on success.
    """
    code = detect_language(text)
    if code == "en" or force_override:
        return code if force_override else "en"
    msg = f"detected language '{code}', only English ('en') is supported"
    raise UnsupportedLanguageError(msg)


__all__ = ["assert_english", "detect_language"]
