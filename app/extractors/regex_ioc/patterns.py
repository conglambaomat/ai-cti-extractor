"""Compiled regex patterns for Phase 1 IOC types.

Each pattern is conservative — better to miss a fuzzy match than to report a
false positive. Per-type validation in :mod:`.normalize` rejects matches
that pass the regex but fail semantic checks (reserved IP ranges, non-IANA
TLDs, malformed CIDs).

The patterns are compiled once at import time and shared across all chunks.
"""

from __future__ import annotations

import re

from app.schemas.ioc import IocType

# IPv4 dotted-quad with strict octet validation (0-255 each)
_IPV4_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
IPV4_PATTERN = re.compile(rf"\b(?:{_IPV4_OCTET}\.){{3}}{_IPV4_OCTET}\b")

# IPv6 — captures full and abbreviated forms; `ipaddress` validates in normalize
IPV6_PATTERN = re.compile(
    r"(?<![:.\w])"
    r"(?:"
    r"(?:[A-Fa-f0-9]{1,4}:){7}[A-Fa-f0-9]{1,4}"
    r"|(?:[A-Fa-f0-9]{1,4}:){1,7}:"
    r"|(?:[A-Fa-f0-9]{1,4}:){1,6}:[A-Fa-f0-9]{1,4}"
    r"|(?:[A-Fa-f0-9]{1,4}:){1,5}(?::[A-Fa-f0-9]{1,4}){1,2}"
    r"|(?:[A-Fa-f0-9]{1,4}:){1,4}(?::[A-Fa-f0-9]{1,4}){1,3}"
    r"|(?:[A-Fa-f0-9]{1,4}:){1,3}(?::[A-Fa-f0-9]{1,4}){1,4}"
    r"|(?:[A-Fa-f0-9]{1,4}:){1,2}(?::[A-Fa-f0-9]{1,4}){1,5}"
    r"|[A-Fa-f0-9]{1,4}:(?::[A-Fa-f0-9]{1,4}){1,6}"
    r"|::(?:[A-Fa-f0-9]{1,4}:){0,6}[A-Fa-f0-9]{1,4}"
    r"|::"
    r")"
    r"(?![:.\w])"
)

# Domain — left to TLD whitelist for final validation in normalize
DOMAIN_PATTERN = re.compile(r"\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.){1,8}[a-zA-Z]{2,24}\b")

# URL — only http/https in Phase 1 (ftp/file/etc deferred); stops at common terminators
URL_PATTERN = re.compile(
    r"https?://[^\s<>\"'`)\]}|]+",
    re.IGNORECASE,
)

# Email — RFC5322 simplified; case-insensitive local part
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}\b")

# Hashes — strict-length hex; word-bounded
MD5_PATTERN = re.compile(r"(?<![A-Fa-f0-9])[a-fA-F0-9]{32}(?![A-Fa-f0-9])")
SHA1_PATTERN = re.compile(r"(?<![A-Fa-f0-9])[a-fA-F0-9]{40}(?![A-Fa-f0-9])")
SHA256_PATTERN = re.compile(r"(?<![A-Fa-f0-9])[a-fA-F0-9]{64}(?![A-Fa-f0-9])")
SHA512_PATTERN = re.compile(r"(?<![A-Fa-f0-9])[a-fA-F0-9]{128}(?![A-Fa-f0-9])")

# CVE — required uppercase by spec; we extract case-insensitively, normalize uppercases
CVE_PATTERN = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)

# Autonomous System Number — `AS` prefix + 1-10 digits
ASN_PATTERN = re.compile(r"\bAS\d{1,10}\b")


# Order matters for the extractor: longer, more specific hashes first so a
# SHA-512 substring is not mis-classified as MD5.
PATTERNS: dict[IocType, re.Pattern[str]] = {
    IocType.SHA512: SHA512_PATTERN,
    IocType.SHA256: SHA256_PATTERN,
    IocType.SHA1: SHA1_PATTERN,
    IocType.MD5: MD5_PATTERN,
    IocType.IPV6: IPV6_PATTERN,
    IocType.IPV4: IPV4_PATTERN,
    IocType.URL: URL_PATTERN,
    IocType.EMAIL: EMAIL_PATTERN,
    IocType.DOMAIN: DOMAIN_PATTERN,
    IocType.CVE: CVE_PATTERN,
    IocType.ASN: ASN_PATTERN,
}


__all__ = [
    "ASN_PATTERN",
    "CVE_PATTERN",
    "DOMAIN_PATTERN",
    "EMAIL_PATTERN",
    "IPV4_PATTERN",
    "IPV6_PATTERN",
    "MD5_PATTERN",
    "PATTERNS",
    "SHA1_PATTERN",
    "SHA256_PATTERN",
    "SHA512_PATTERN",
    "URL_PATTERN",
]
