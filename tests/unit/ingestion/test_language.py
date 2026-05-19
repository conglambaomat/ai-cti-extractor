"""Tests for the language gate."""

from __future__ import annotations

import pytest
from app.core.exceptions import UnsupportedLanguageError
from app.ingestion import assert_english, detect_language


def test_detects_english() -> None:
    assert detect_language("This is a typical English threat report sentence.") == "en"


def test_assert_english_passes() -> None:
    assert_english("Cyber threat intelligence report on APT actors and tools.")


def test_rejects_vietnamese() -> None:
    with pytest.raises(UnsupportedLanguageError):
        assert_english(
            "Đây là một báo cáo thông tin tình báo mối đe dọa mạng bằng tiếng Việt"
            " mô tả các tác nhân APT và hành vi tấn công của họ trên mạng."
        )


def test_force_override_bypasses_check() -> None:
    code = assert_english("Đây là báo cáo bằng tiếng Việt", force_override=True)
    # When override is set, the function returns the *detected* code, not "en".
    assert code != "en"


def test_empty_text_returns_und() -> None:
    assert detect_language("") == "und"
