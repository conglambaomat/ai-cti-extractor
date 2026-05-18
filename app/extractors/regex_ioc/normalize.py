"""Per-type IOC normalization + semantic validation.

After the regex matches, every candidate string is run through a normalizer
that returns either the canonical form (lowercased, trimmed, IPv6-compressed,
TLD-validated) or ``None`` to reject obvious false positives.

Normalization rules per type (Phase 1):

==========  =================================================================
Type        Normalize
==========  =================================================================
ipv4        ``ipaddress.IPv4Address`` parse; reject reserved ranges
ipv6        ``ipaddress.IPv6Address`` parse + .compressed; reject reserved
domain      lowercase + strip trailing dot; reject if TLD not in the IANA list
url         lowercase scheme + host; preserve path; reject if domain rejected
email       lowercase domain; preserve local-part; reject domain failures
md5/sha*    lowercase hex
cve         uppercase ``CVE-YYYY-NNNN+``
asn         uppercase ``AS<int>``; reject AS0
==========  =================================================================

The TLD whitelist comes from a shipped snapshot of IANA's
``tlds-alpha-by-domain.txt``. Refresh quarterly; load from
``tests/fixtures/iana/`` so test environments are reproducible.
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from app.schemas.ioc import IocType

_DEFAULT_TLD_FALLBACK = frozenset(
    {
        # Common gTLDs / ccTLDs to bootstrap before the IANA snapshot ships.
        # The fixture file overrides this when present.
        "com",
        "net",
        "org",
        "io",
        "co",
        "gov",
        "edu",
        "mil",
        "info",
        "biz",
        "us",
        "uk",
        "de",
        "fr",
        "ru",
        "cn",
        "jp",
        "br",
        "ca",
        "au",
        "in",
        "vn",
        "kr",
        "tw",
        "hk",
        "sg",
        "tk",
        "xyz",
        "online",
        "site",
        "store",
        "cloud",
        "tech",
        "app",
        "dev",
    }
)


@lru_cache(maxsize=1)
def _load_tld_whitelist() -> frozenset[str]:
    """Load IANA TLD list from fixture if available, else minimal fallback.

    Searched in order:
        1. ``tests/fixtures/iana/tlds-alpha-by-domain.txt``
        2. ``data/iana/tlds-alpha-by-domain.txt``
    """
    repo_root = Path(__file__).resolve().parents[3]
    candidates = [
        repo_root / "tests" / "fixtures" / "iana" / "tlds-alpha-by-domain.txt",
        repo_root / "data" / "iana" / "tlds-alpha-by-domain.txt",
    ]
    for path in candidates:
        if path.exists():
            tlds: set[str] = set()
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    tlds.add(line.lower())
            if tlds:
                return frozenset(tlds)
    return _DEFAULT_TLD_FALLBACK


def _norm_ipv4(value: str) -> str | None:
    try:
        addr = ipaddress.IPv4Address(value)
    except (ipaddress.AddressValueError, ValueError):
        return None
    if (
        addr.is_loopback
        or addr.is_unspecified
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_private  # 10/8, 172.16/12, 192.168/16 — usually internal
    ):
        return None
    return str(addr)


def _norm_ipv6(value: str) -> str | None:
    try:
        addr = ipaddress.IPv6Address(value)
    except (ipaddress.AddressValueError, ValueError):
        return None
    if addr.is_loopback or addr.is_unspecified or addr.is_link_local or addr.is_multicast or addr.is_reserved:
        return None
    return addr.compressed


def _norm_domain(value: str) -> str | None:
    candidate = value.lower().rstrip(".")
    if "." not in candidate:
        return None
    tld = candidate.rsplit(".", 1)[-1]
    if tld not in _load_tld_whitelist():
        return None
    if any(part == "" for part in candidate.split(".")):
        return None
    return candidate


def _norm_url(value: str) -> str | None:
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"}:
        return None
    if not parsed.netloc:
        return None
    host = parsed.hostname or ""
    # Validate host as either domain or IP literal
    if _norm_domain(host) is None and _norm_ipv4(host) is None and _norm_ipv6(host) is None:
        return None
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    rest = parsed._replace(scheme=scheme, netloc=netloc).geturl()
    return rest


def _norm_email(value: str) -> str | None:
    if "@" not in value:
        return None
    local, _, domain = value.rpartition("@")
    if not local:
        return None
    norm_domain = _norm_domain(domain)
    if norm_domain is None:
        return None
    return f"{local}@{norm_domain}"


def _norm_hex(value: str, length: int) -> str | None:
    candidate = value.lower()
    if len(candidate) != length:
        return None
    try:
        int(candidate, 16)
    except ValueError:
        return None
    return candidate


def _norm_cve(value: str) -> str | None:
    candidate = value.upper()
    if not candidate.startswith("CVE-"):
        return None
    return candidate


def _norm_asn(value: str) -> str | None:
    candidate = value.upper()
    if not candidate.startswith("AS"):
        return None
    try:
        number = int(candidate[2:])
    except ValueError:
        return None
    if number == 0:
        return None
    return f"AS{number}"


_NORMALIZERS = {
    IocType.IPV4: _norm_ipv4,
    IocType.IPV6: _norm_ipv6,
    IocType.DOMAIN: _norm_domain,
    IocType.URL: _norm_url,
    IocType.EMAIL: _norm_email,
    IocType.MD5: lambda v: _norm_hex(v, 32),
    IocType.SHA1: lambda v: _norm_hex(v, 40),
    IocType.SHA256: lambda v: _norm_hex(v, 64),
    IocType.SHA512: lambda v: _norm_hex(v, 128),
    IocType.CVE: _norm_cve,
    IocType.ASN: _norm_asn,
}


def normalize(ioc_type: IocType, raw: str) -> str | None:
    """Return canonical form or ``None`` if the value is rejected."""
    fn = _NORMALIZERS.get(ioc_type)
    if fn is None:
        msg = f"no normalizer for {ioc_type}"
        raise ValueError(msg)
    return fn(raw.strip())


__all__ = ["normalize"]
