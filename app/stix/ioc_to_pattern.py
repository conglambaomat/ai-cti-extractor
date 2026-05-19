"""Translate :class:`IocCandidate` -> STIX 2.1 Indicator pattern string.

STIX patterns use a small grammar:

    [ <object>:<property> = '<literal>' ]

Single quotes inside literals must be doubled; we handle that for URLs and
emails (which can contain quotes legally per RFC).

CVE -> Vulnerability is intentionally NOT handled here: a CVE is not an
Indicator in STIX 2.1; it is a Vulnerability object. Phase 1 ships only
Report + Indicator + Relationship, so CVEs are skipped at the builder level.
"""

from __future__ import annotations

from app.schemas.ioc import IocCandidate, IocType


class UnsupportedIocTypeError(ValueError):
    """Raised when an IOC type cannot be expressed as a STIX 2.1 Indicator pattern.

    CVE belongs to Vulnerability (Phase 2+); ASN belongs to autonomous-system
    observable but the pattern shape is different from value-typed observables.
    """


def _escape_literal(value: str) -> str:
    """Double single-quotes per STIX 2.1 pattern grammar."""
    return value.replace("'", "''")


def ioc_to_stix_pattern(ioc: IocCandidate) -> str:
    """Build the STIX 2.1 pattern literal for ``ioc``.

    Raises:
        UnsupportedIocTypeError: ``ioc.type`` is CVE or otherwise unsupported.
    """
    n = ioc.normalized

    match ioc.type:
        case IocType.IPV4:
            return f"[ipv4-addr:value = '{n}']"
        case IocType.IPV6:
            return f"[ipv6-addr:value = '{n}']"
        case IocType.DOMAIN:
            return f"[domain-name:value = '{n}']"
        case IocType.URL:
            return f"[url:value = '{_escape_literal(n)}']"
        case IocType.EMAIL:
            return f"[email-addr:value = '{_escape_literal(n)}']"
        case IocType.MD5:
            return f"[file:hashes.MD5 = '{n}']"
        case IocType.SHA1:
            return f"[file:hashes.'SHA-1' = '{n}']"
        case IocType.SHA256:
            return f"[file:hashes.'SHA-256' = '{n}']"
        case IocType.SHA512:
            return f"[file:hashes.'SHA-512' = '{n}']"
        case IocType.ASN:
            number = int(n.removeprefix("AS"))
            return f"[autonomous-system:number = {number}]"
        case IocType.CVE:
            msg = "CVE is a Vulnerability object in STIX 2.1, not an Indicator (Phase 2+)"
            raise UnsupportedIocTypeError(msg)


__all__ = ["UnsupportedIocTypeError", "ioc_to_stix_pattern"]
