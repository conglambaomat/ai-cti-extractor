"""End-to-end tests for ``app.stix.build_bundle`` and the validation layers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import stix2
from app.schemas import (
    Candidates,
    ChunkRef,
    DocumentMeta,
    Evidence,
    ExtractorRun,
    IntermediateCTI,
    IocCandidate,
    IocType,
    Provenance,
)
from app.stix import build_bundle, bundle_hash, serialize_canonical, validate
from app.stix.builders import StixBuildError


def _meta() -> DocumentMeta:
    return DocumentMeta(
        id="00000000-0000-0000-0000-000000000001",
        source_uri="file:///tmp/sample.pdf",
        sha256="a" * 64,
        title="Sample",
        ingested_at=datetime(2026, 5, 19, tzinfo=UTC),
        source_format="pdf",
    )


def _provenance() -> Provenance:
    return Provenance(
        pipeline_version="0.1.0",
        extractors=[
            ExtractorRun(
                name="regex_ioc",
                version="1.0.0",
                started_at=datetime(2026, 5, 19, tzinfo=UTC),
                ended_at=datetime(2026, 5, 19, tzinfo=UTC),
                config_hash="b" * 64,
            )
        ],
    )


def _evidence(eid: str = "e-" + "0" * 16) -> Evidence:
    return Evidence(
        evidence_id=eid,
        chunk_id="c-1",
        text_span="evil.example.com",
        char_start=10,
        char_end=26,
    )


def _ioc(ioc_type: IocType, normalized: str, eid: str = "e-" + "0" * 16) -> IocCandidate:
    return IocCandidate(
        type=ioc_type,
        value=normalized,
        normalized=normalized,
        evidence_ids=[eid],
        confidence=0.9,
        extractor="regex_ioc@1.0.0",
    )


def _cti(iocs: list[IocCandidate]) -> IntermediateCTI:
    return IntermediateCTI(
        document=_meta(),
        chunks=[ChunkRef(chunk_id="c-1", char_start=0, char_end=200)],
        candidates=Candidates(iocs=iocs),
        evidence=[_evidence()],
        provenance=_provenance(),
    )


def test_build_bundle_minimal_report_plus_indicator() -> None:
    bundle = build_bundle(_cti([_ioc(IocType.DOMAIN, "evil.example.com")]))
    types = sorted(obj["type"] for obj in bundle.objects)
    assert types == ["indicator", "report"]


def test_bundle_round_trips_through_strict_parse() -> None:
    bundle = build_bundle(_cti([_ioc(IocType.DOMAIN, "evil.example.com")]))
    reparsed = stix2.parse(bundle.serialize(), allow_custom=False)
    # round-trip yields a parseable Bundle (or list of objects)
    assert reparsed is not None


def test_bundle_hash_stable_across_runs() -> None:
    cti = _cti([_ioc(IocType.DOMAIN, "evil.example.com")])
    h1 = bundle_hash(build_bundle(cti))
    h2 = bundle_hash(build_bundle(cti))
    assert h1 == h2


def test_bundle_hash_changes_when_ioc_changes() -> None:
    h1 = bundle_hash(build_bundle(_cti([_ioc(IocType.DOMAIN, "evil.example.com")])))
    h2 = bundle_hash(build_bundle(_cti([_ioc(IocType.DOMAIN, "other.example.com")])))
    assert h1 != h2


def test_serialize_canonical_is_deterministic() -> None:
    bundle = build_bundle(_cti([_ioc(IocType.DOMAIN, "evil.example.com")]))
    assert serialize_canonical(bundle) == serialize_canonical(bundle)


def test_build_bundle_skips_cve() -> None:
    cti = _cti(
        [
            _ioc(IocType.DOMAIN, "evil.example.com"),
            _ioc(IocType.CVE, "CVE-2024-1234"),
        ]
    )
    bundle = build_bundle(cti)
    types = [obj["type"] for obj in bundle.objects]
    assert types.count("indicator") == 1  # CVE skipped


def test_build_bundle_raises_when_no_buildable_indicators() -> None:
    cti = _cti([_ioc(IocType.CVE, "CVE-2024-1234")])
    with pytest.raises(StixBuildError):
        build_bundle(cti)


def test_validate_passes_for_valid_bundle() -> None:
    cti = _cti([_ioc(IocType.DOMAIN, "evil.example.com")])
    bundle = build_bundle(cti)
    result = validate(cti, bundle)
    assert result.is_valid, result.issues


def test_indicator_id_deterministic_same_input() -> None:
    cti = _cti([_ioc(IocType.IPV4, "8.8.8.8")])
    b1 = build_bundle(cti)
    b2 = build_bundle(cti)
    ids1 = sorted(obj["id"] for obj in b1.objects)
    ids2 = sorted(obj["id"] for obj in b2.objects)
    assert ids1 == ids2
