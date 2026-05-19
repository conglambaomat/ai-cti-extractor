"""Per-type IOC normalization tests."""

from __future__ import annotations

import pytest
from app.extractors.regex_ioc.normalize import normalize
from app.schemas.ioc import IocType

# ----- IPv4 -----------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["8.8.8.8", "1.1.1.1", "23.45.67.89"],
)
def test_ipv4_public_accepted(value: str) -> None:
    assert normalize(IocType.IPV4, value) == value


@pytest.mark.parametrize(
    "value",
    ["127.0.0.1", "192.168.1.1", "10.0.0.5", "172.16.0.1", "0.0.0.0", "169.254.1.1", "224.0.0.1"],
)
def test_ipv4_reserved_rejected(value: str) -> None:
    assert normalize(IocType.IPV4, value) is None


# ----- IPv6 -----------------------------------------------------------------


def test_ipv6_compressed() -> None:
    assert normalize(IocType.IPV6, "2001:0db8:0000:0000:0000:0000:0000:0001") == "2001:db8::1"


def test_ipv6_loopback_rejected() -> None:
    assert normalize(IocType.IPV6, "::1") is None


# ----- Domain ---------------------------------------------------------------


def test_domain_lowercased() -> None:
    assert normalize(IocType.DOMAIN, "EVIL.Example.Com") == "evil.example.com"


def test_domain_invalid_tld_rejected() -> None:
    # `.invalidtld` not in IANA fallback whitelist
    assert normalize(IocType.DOMAIN, "host.invalidtld") is None


def test_domain_no_dot_rejected() -> None:
    assert normalize(IocType.DOMAIN, "localhost") is None


# ----- URL ------------------------------------------------------------------


def test_url_lowercases_scheme_host() -> None:
    assert normalize(IocType.URL, "HTTPS://Evil.Example.com/Path") == "https://evil.example.com/Path"


def test_url_non_http_scheme_rejected() -> None:
    assert normalize(IocType.URL, "ftp://evil.example.com/x") is None


# ----- Email ----------------------------------------------------------------


def test_email_local_part_preserved_domain_lowercased() -> None:
    assert normalize(IocType.EMAIL, "Attacker@Evil.Example.Com") == "Attacker@evil.example.com"


def test_email_invalid_tld_rejected() -> None:
    assert normalize(IocType.EMAIL, "x@host.invalidtld") is None


# ----- Hashes ---------------------------------------------------------------


def test_md5_lowercased() -> None:
    assert normalize(IocType.MD5, "D41D8CD98F00B204E9800998ECF8427E") == "d41d8cd98f00b204e9800998ecf8427e"


def test_sha256_wrong_length_rejected() -> None:
    assert normalize(IocType.SHA256, "abc") is None


def test_sha512_accepted() -> None:
    digest = "f" * 128
    assert normalize(IocType.SHA512, digest) == digest


# ----- CVE ------------------------------------------------------------------


def test_cve_uppercased() -> None:
    assert normalize(IocType.CVE, "cve-2024-1234") == "CVE-2024-1234"


# ----- ASN ------------------------------------------------------------------


def test_asn_normalizes_padding() -> None:
    assert normalize(IocType.ASN, "AS013335") == "AS13335"


def test_asn_zero_rejected() -> None:
    assert normalize(IocType.ASN, "AS0") is None
