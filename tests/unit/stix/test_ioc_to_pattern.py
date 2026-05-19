"""Tests for IocCandidate -> STIX 2.1 pattern translation."""

from __future__ import annotations

import pytest
from app.schemas.ioc import IocCandidate, IocType
from app.stix.ioc_to_pattern import UnsupportedIocTypeError, ioc_to_stix_pattern


def _ioc(ioc_type: IocType, normalized: str) -> IocCandidate:
    return IocCandidate(
        type=ioc_type,
        value=normalized,
        normalized=normalized,
        evidence_ids=["e-" + "0" * 16],
        confidence=1.0,
        extractor="regex_ioc@1.0.0",
    )


@pytest.mark.parametrize(
    ("ioc_type", "value", "expected"),
    [
        (IocType.IPV4, "8.8.8.8", "[ipv4-addr:value = '8.8.8.8']"),
        (IocType.IPV6, "2001:db8::1", "[ipv6-addr:value = '2001:db8::1']"),
        (IocType.DOMAIN, "evil.example.com", "[domain-name:value = 'evil.example.com']"),
        (
            IocType.URL,
            "https://evil.example.com/x",
            "[url:value = 'https://evil.example.com/x']",
        ),
        (IocType.EMAIL, "a@b.com", "[email-addr:value = 'a@b.com']"),
        (IocType.MD5, "d" * 32, f"[file:hashes.MD5 = '{'d' * 32}']"),
        (IocType.SHA1, "a" * 40, f"[file:hashes.'SHA-1' = '{'a' * 40}']"),
        (IocType.SHA256, "a" * 64, f"[file:hashes.'SHA-256' = '{'a' * 64}']"),
        (IocType.SHA512, "a" * 128, f"[file:hashes.'SHA-512' = '{'a' * 128}']"),
        (IocType.ASN, "AS13335", "[autonomous-system:number = 13335]"),
    ],
)
def test_per_type_pattern(ioc_type: IocType, value: str, expected: str) -> None:
    assert ioc_to_stix_pattern(_ioc(ioc_type, value)) == expected


def test_url_with_single_quote_escapes() -> None:
    pattern = ioc_to_stix_pattern(_ioc(IocType.URL, "https://e.com/x'y"))
    assert "''" in pattern  # doubled


def test_cve_raises_unsupported() -> None:
    with pytest.raises(UnsupportedIocTypeError):
        ioc_to_stix_pattern(_ioc(IocType.CVE, "CVE-2024-1234"))
