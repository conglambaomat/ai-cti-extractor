"""Tests for the top-level :class:`IntermediateCTI` invariants.

These exercise the closure checks (chunk -> evidence -> ioc) that prevent
unsupported claims from ever being instantiated.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
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
from pydantic import ValidationError


@pytest.fixture()
def doc() -> DocumentMeta:
    return DocumentMeta(
        id="00000000-0000-0000-0000-000000000001",
        source_uri="file:///tmp/sample.pdf",
        sha256="a" * 64,
        title="Sample report",
        ingested_at=datetime(2026, 5, 19, tzinfo=UTC),
        mime_type="application/pdf",
        source_format="pdf",
    )


@pytest.fixture()
def chunk() -> ChunkRef:
    return ChunkRef(chunk_id="c-1", section="Initial Access", page=1, char_start=0, char_end=200)


@pytest.fixture()
def evidence() -> Evidence:
    return Evidence(
        evidence_id="e-" + "0" * 16,
        chunk_id="c-1",
        text_span="evil.example.com",
        char_start=10,
        char_end=26,
    )


@pytest.fixture()
def provenance() -> Provenance:
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


def _ioc(eid: str = "e-" + "0" * 16) -> IocCandidate:
    return IocCandidate(
        type=IocType.DOMAIN,
        value="evil[.]example.com",
        normalized="evil.example.com",
        evidence_ids=[eid],
        confidence=1.0,
        extractor="regex_ioc@1.0.0",
    )


def test_happy_path_round_trip(doc: DocumentMeta, chunk: ChunkRef, evidence: Evidence, provenance: Provenance) -> None:
    cti = IntermediateCTI(
        document=doc,
        chunks=[chunk],
        candidates=Candidates(iocs=[_ioc()]),
        evidence=[evidence],
        provenance=provenance,
    )

    payload = cti.model_dump_json()
    restored = IntermediateCTI.model_validate_json(payload)

    assert restored.document.sha256 == doc.sha256
    assert len(restored.candidates.iocs) == 1
    assert restored.evidence[0].evidence_id == evidence.evidence_id


def test_ioc_without_evidence_rejected() -> None:
    with pytest.raises(ValidationError) as excinfo:
        IocCandidate(
            type=IocType.DOMAIN,
            value="evil.com",
            normalized="evil.com",
            evidence_ids=[],
            confidence=1.0,
            extractor="regex_ioc@1.0.0",
        )
    assert "evidence_ids" in str(excinfo.value)


def test_evidence_referencing_unknown_chunk_rejected(
    doc: DocumentMeta, chunk: ChunkRef, provenance: Provenance
) -> None:
    bad_evidence = Evidence(
        evidence_id="e-" + "1" * 16,
        chunk_id="c-DOES-NOT-EXIST",
        text_span="nope",
        char_start=0,
        char_end=4,
    )
    with pytest.raises(ValidationError, match="unknown chunk_id"):
        IntermediateCTI(
            document=doc,
            chunks=[chunk],
            evidence=[bad_evidence],
            provenance=provenance,
        )


def test_ioc_referencing_unknown_evidence_rejected(
    doc: DocumentMeta, chunk: ChunkRef, evidence: Evidence, provenance: Provenance
) -> None:
    with pytest.raises(ValidationError, match="unknown evidence_id"):
        IntermediateCTI(
            document=doc,
            chunks=[chunk],
            candidates=Candidates(iocs=[_ioc(eid="e-" + "9" * 16)]),
            evidence=[evidence],
            provenance=provenance,
        )


def test_evidence_offset_invariant_rejected() -> None:
    with pytest.raises(ValidationError, match="char_end"):
        Evidence(
            evidence_id="e-" + "0" * 16,
            chunk_id="c-1",
            text_span="x",
            char_start=10,
            char_end=10,
        )


def test_chunk_offset_invariant_rejected(doc: DocumentMeta, evidence: Evidence, provenance: Provenance) -> None:
    bad_chunk = ChunkRef(chunk_id="c-1", char_start=100, char_end=50)
    with pytest.raises(ValidationError, match="char_end"):
        IntermediateCTI(
            document=doc,
            chunks=[bad_chunk],
            evidence=[evidence],
            provenance=provenance,
        )


def test_provenance_append_is_immutable(provenance: Provenance) -> None:
    new_run = ExtractorRun(
        name="stix_builder",
        version="1.0.0",
        started_at=datetime(2026, 5, 19, tzinfo=UTC),
        ended_at=datetime(2026, 5, 19, tzinfo=UTC),
        config_hash="c" * 64,
    )
    appended = provenance.append(new_run)
    assert len(provenance.extractors) == 1
    assert len(appended.extractors) == 2
    assert appended is not provenance


def test_extractor_format_validation() -> None:
    with pytest.raises(ValidationError):
        IocCandidate(
            type=IocType.DOMAIN,
            value="x.com",
            normalized="x.com",
            evidence_ids=["e-" + "0" * 16],
            confidence=1.0,
            extractor="missing-version",
        )


def test_serialization_canonical_json_stable(
    doc: DocumentMeta, chunk: ChunkRef, evidence: Evidence, provenance: Provenance
) -> None:
    cti = IntermediateCTI(
        document=doc,
        chunks=[chunk],
        candidates=Candidates(iocs=[_ioc()]),
        evidence=[evidence],
        provenance=provenance,
    )
    once = json.dumps(cti.model_dump(mode="json"), sort_keys=True)
    twice = json.dumps(cti.model_dump(mode="json"), sort_keys=True)
    assert once == twice
