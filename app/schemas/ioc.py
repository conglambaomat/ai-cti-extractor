"""Indicator of Compromise (IOC) candidate types and Pydantic model."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class IocType(str, Enum):
    """Phase 1 IOC type vocabulary.

    Phase 2 may add ``file_path``, ``registry_key``, ``mutex``, ``user_agent``.
    Adding a new variant is a schema change — bump :attr:`IntermediateCTI.version`.
    """

    IPV4 = "ipv4"
    IPV6 = "ipv6"
    DOMAIN = "domain"
    URL = "url"
    EMAIL = "email"
    MD5 = "md5"
    SHA1 = "sha1"
    SHA256 = "sha256"
    SHA512 = "sha512"
    CVE = "cve"
    ASN = "asn"


class IocCandidate(BaseModel):
    """A single IOC candidate produced by an extractor.

    Invariants:
        * ``evidence_ids`` is non-empty (evidence grounding is mandatory).
        * ``confidence`` in [0, 1].
        * ``value`` retains the original (possibly defanged) text from the
          report for audit; ``normalized`` is the refanged + lowercased
          form used for STIX pattern construction and dedup.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: IocType
    value: str = Field(min_length=1, max_length=2048)
    normalized: str = Field(
        min_length=1,
        max_length=2048,
        description="Defanged + lowercased; stable across runs; used as dedup key",
    )
    evidence_ids: list[str] = Field(
        min_length=1,
        description="Must reference at least one Evidence; closure checked at IntermediateCTI level",
    )
    confidence: float = Field(ge=0.0, le=1.0)
    extractor: str = Field(
        description="Name@version, e.g. 'regex_ioc@1.0.0'",
        pattern=r"^[a-z][a-z0-9_]*@\d+\.\d+\.\d+$",
    )
