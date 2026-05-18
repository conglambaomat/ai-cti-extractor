"""Build STIX 2.1 bundles from :class:`IntermediateCTI`.

Phase 1 ships only three object types: ``Report``, ``Indicator``, and
``Relationship`` (skeleton — no real Malware/ThreatActor yet to point at,
so Relationship is reserved for Phase 2 entity work). The Report.object_refs
list links the report to its indicators directly.

Output objects are deterministic across runs (stable UUIDv5 ids), strict
(``allow_custom=False``), and ready to round-trip through OpenCTI.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import stix2

from app.schemas.intermediate_cti import IntermediateCTI
from app.schemas.ioc import IocCandidate, IocType
from app.stix.ids import bundle_id, indicator_id, report_id
from app.stix.ioc_to_pattern import UnsupportedIocTypeError, ioc_to_stix_pattern


class StixBuildError(ValueError):
    """Raised when an IntermediateCTI cannot be turned into a STIX bundle."""


def _to_utc_z(value: datetime) -> datetime:
    """Coerce timestamps to UTC. STIX 2.1 requires `Z` zone serialization."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _build_indicator(doc_id: str, ioc: IocCandidate, valid_from: datetime) -> stix2.v21.Indicator:
    pattern = ioc_to_stix_pattern(ioc)
    iid = indicator_id(doc_id, pattern)

    return stix2.v21.Indicator(
        id=iid,
        pattern=pattern,
        pattern_type="stix",
        created=valid_from,
        modified=valid_from,
        valid_from=_to_utc_z(valid_from),
        indicator_types=["malicious-activity"],
        name=f"{ioc.type.value}: {ioc.normalized}",
        description=(f"Extracted by {ioc.extractor}; backed by {len(ioc.evidence_ids)} evidence span(s)."),
        confidence=int(round(ioc.confidence * 100)),
        allow_custom=False,
    )


def build_bundle(cti: IntermediateCTI) -> stix2.v21.Bundle:
    """Build a STIX 2.1 ``Bundle`` for the given intermediate representation.

    Skips IOC types not yet expressible as Indicators (CVE — Phase 2+).
    Always emits a Report linking every successfully built Indicator.
    """
    objects: list[stix2.v21._STIXBase21] = []
    indicator_refs: list[str] = []

    valid_from = _to_utc_z(cti.document.ingested_at)

    for ioc in cti.candidates.iocs:
        if ioc.type is IocType.CVE:
            # Phase 2: emit Vulnerability instead.
            continue
        try:
            indicator = _build_indicator(cti.document.id, ioc, valid_from)
        except UnsupportedIocTypeError:
            continue
        objects.append(indicator)
        indicator_refs.append(cast("str", indicator["id"]))

    if not indicator_refs:
        msg = "no buildable indicators in IntermediateCTI (Phase 1 requires >=1)"
        raise StixBuildError(msg)

    rid = report_id(cti.document.id)
    report = stix2.v21.Report(
        id=rid,
        name=cti.document.title or f"Report {cti.document.id}",
        created=valid_from,
        modified=valid_from,
        published=valid_from,
        report_types=["threat-report"],
        object_refs=indicator_refs,
        description=cti.document.source_uri,
        allow_custom=False,
    )

    all_objects = [report, *objects]
    bid = bundle_id([cast("str", obj["id"]) for obj in all_objects])
    return stix2.v21.Bundle(id=bid, objects=all_objects, allow_custom=False)


__all__ = ["StixBuildError", "build_bundle"]
