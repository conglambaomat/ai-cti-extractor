"""Tests for the offset-preserving refang utility."""

from __future__ import annotations

from app.extractors.regex_ioc.defang import build_refanged_view


def test_bracket_dot_refangs() -> None:
    view = build_refanged_view("evil[.]example.com")
    assert view.refanged == "evil.example.com"


def test_hxxp_refangs() -> None:
    view = build_refanged_view("hxxps://bad.com/x")
    assert view.refanged == "https://bad.com/x"


def test_at_refangs() -> None:
    view = build_refanged_view("user[at]domain.com")
    assert view.refanged == "user@domain.com"


def test_zero_width_chars_stripped() -> None:
    view = build_refanged_view("evil​.com")
    assert view.refanged == "evil.com"


def test_clean_text_unchanged() -> None:
    view = build_refanged_view("plain text without defang")
    assert view.refanged == "plain text without defang"
    assert view.orig_idx_per_char == tuple(range(len("plain text without defang")))


def test_resolve_round_trip_for_clean_text() -> None:
    text = "evil.example.com is bad"
    view = build_refanged_view(text)
    start = view.refanged.index("evil.example.com")
    end = start + len("evil.example.com")
    orig_start, orig_end = view.resolve(start, end)
    assert text[orig_start:orig_end] == "evil.example.com"


def test_resolve_round_trip_after_bracket_dot() -> None:
    text = "see evil[.]example.com please"
    view = build_refanged_view(text)
    assert "evil.example.com" in view.refanged

    start = view.refanged.index("evil.example.com")
    end = start + len("evil.example.com")
    orig_start, orig_end = view.resolve(start, end)

    # Original span must cover the original brackets:
    assert text[orig_start:orig_end] == "evil[.]example.com"


def test_resolve_round_trip_after_hxxp() -> None:
    text = "click hxxps://bad.example.com/path now"
    view = build_refanged_view(text)
    refanged_url = "https://bad.example.com/path"
    start = view.refanged.index(refanged_url)
    end = start + len(refanged_url)
    orig_start, orig_end = view.resolve(start, end)
    assert text[orig_start:orig_end] == "hxxps://bad.example.com/path"


def test_multiple_defangs_in_one_string() -> None:
    text = "hxxps://evil[.]com and user[at]bad[.]com"
    view = build_refanged_view(text)
    assert view.refanged == "https://evil.com and user@bad.com"
