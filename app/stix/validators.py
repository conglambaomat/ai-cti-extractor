"""Layered STIX bundle validation.

Four independent layers, each catches different defects:

  Layer 1 - Pydantic intermediate invariants (already enforced by
            :class:`IntermediateCTI`; we re-check here for defensive depth)
  Layer 2 - ``stix2.parse(allow_custom=False)`` strict library parse
  Layer 3 - Semantic ref-closure + vocab checks (relationship endpoints,
            object_refs target presence, ATT&CK external_references shape)
  Layer 4 - Hypothesis property-based fuzzing (lives under tests/property/)

This module wires Layers 1-3. The Hypothesis layer is invoked by tests
(see ``tests/property/test_stix_invariants.py``) and not at runtime.
"""

from __future__ import annotations

import json
import re
from typing import Any

import stix2
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.intermediate_cti import IntermediateCTI

# STIX 2.1 vocab subset for relationship_type per (source_type, target_type).
# Phase 1 ships only Indicator + Report so relationship vocab is minimal;
# Phase 2 will broaden this.
_VALID_RELATIONSHIPS: dict[tuple[str, str], frozenset[str]] = {
    ("indicator", "malware"): frozenset({"indicates"}),
    ("indicator", "tool"): frozenset({"indicates"}),
    ("indicator", "attack-pattern"): frozenset({"indicates"}),
    ("indicator", "infrastructure"): frozenset({"indicates"}),
    ("indicator", "threat-actor"): frozenset({"indicates"}),
    ("indicator", "intrusion-set"): frozenset({"indicates"}),
}

_ATTACK_TECHNIQUE_RE = re.compile(r"^T\d{4}(\.\d{3})?$")
_ATTACK_TACTICS = frozenset(
    {
        "reconnaissance",
        "resource-development",
        "initial-access",
        "execution",
        "persistence",
        "privilege-escalation",
        "defense-evasion",
        "credential-access",
        "discovery",
        "lateral-movement",
        "collection",
        "command-and-control",
        "exfiltration",
        "impact",
    }
)


class ValidationIssue(BaseModel):
    """Single validation finding."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    layer: str
    code: str
    message: str
    target_id: str | None = None


class ValidationResult(BaseModel):
    """Aggregate result of running all layers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pydantic_ok: bool
    parse_ok: bool
    semantic_ok: bool
    issues: list[ValidationIssue] = Field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.pydantic_ok and self.parse_ok and self.semantic_ok


# ----- Layer 1 ---------------------------------------------------------------


def _check_pydantic_invariants(cti: IntermediateCTI, issues: list[ValidationIssue]) -> bool:
    """Re-validate evidence closure (already enforced by the schema).

    A defensive belt-and-braces check: if upstream code mutates a model via
    private API, this catches the drift before STIX is built.
    """
    chunk_ids = {c.chunk_id for c in cti.chunks}
    evidence_ids = {e.evidence_id for e in cti.evidence}
    ok = True

    for ev in cti.evidence:
        if ev.chunk_id not in chunk_ids:
            issues.append(
                ValidationIssue(
                    layer="pydantic",
                    code="dangling_evidence_chunk",
                    message=f"evidence {ev.evidence_id} -> unknown chunk {ev.chunk_id}",
                    target_id=ev.evidence_id,
                )
            )
            ok = False

    for ioc in cti.candidates.iocs:
        for eid in ioc.evidence_ids:
            if eid not in evidence_ids:
                issues.append(
                    ValidationIssue(
                        layer="pydantic",
                        code="dangling_ioc_evidence",
                        message=f"ioc {ioc.value!r} -> unknown evidence {eid}",
                    )
                )
                ok = False
    return ok


# ----- Layer 2 ---------------------------------------------------------------


def _check_strict_parse(bundle: stix2.v21.Bundle, issues: list[ValidationIssue]) -> bool:
    """Round-trip the bundle through ``stix2.parse(allow_custom=False)``."""
    try:
        serialized = bundle.serialize()
        stix2.parse(json.loads(serialized), allow_custom=False)
    except (stix2.exceptions.STIXError, ValueError) as e:
        issues.append(
            ValidationIssue(
                layer="parse",
                code="stix_parse_error",
                message=str(e),
            )
        )
        return False
    return True


# ----- Layer 3 ---------------------------------------------------------------


def _object_lookup(bundle: stix2.v21.Bundle) -> dict[str, dict[str, Any]]:
    return {cast_str(obj["id"]): _to_dict(obj) for obj in bundle.objects}


def cast_str(value: Any) -> str:
    return str(value)


def _to_dict(obj: Any) -> dict[str, Any]:
    if hasattr(obj, "_inner"):
        return dict(obj._inner)
    return dict(obj)


def _check_semantics(bundle: stix2.v21.Bundle, issues: list[ValidationIssue]) -> bool:
    by_id = _object_lookup(bundle)
    ok = True

    for obj_id, obj in by_id.items():
        obj_type = cast_str(obj.get("type", ""))

        # Report.object_refs must resolve
        if obj_type == "report":
            for ref in obj.get("object_refs", []) or []:
                if cast_str(ref) not in by_id:
                    issues.append(
                        ValidationIssue(
                            layer="semantic",
                            code="dangling_report_ref",
                            message=f"report {obj_id} -> unknown object {ref}",
                            target_id=obj_id,
                        )
                    )
                    ok = False

        # Relationship endpoints must resolve and the type must be in vocab
        if obj_type == "relationship":
            src = cast_str(obj.get("source_ref", ""))
            tgt = cast_str(obj.get("target_ref", ""))
            rtype = cast_str(obj.get("relationship_type", ""))

            if src not in by_id:
                issues.append(
                    ValidationIssue(
                        layer="semantic",
                        code="dangling_rel_source",
                        message=f"relationship {obj_id} source {src} not in bundle",
                        target_id=obj_id,
                    )
                )
                ok = False
            if tgt not in by_id:
                issues.append(
                    ValidationIssue(
                        layer="semantic",
                        code="dangling_rel_target",
                        message=f"relationship {obj_id} target {tgt} not in bundle",
                        target_id=obj_id,
                    )
                )
                ok = False

            src_type = src.split("--", 1)[0] if src else ""
            tgt_type = tgt.split("--", 1)[0] if tgt else ""
            allowed = _VALID_RELATIONSHIPS.get((src_type, tgt_type))
            if allowed is not None and rtype not in allowed:
                issues.append(
                    ValidationIssue(
                        layer="semantic",
                        code="invalid_relationship_type",
                        message=(
                            f"relationship {obj_id}: '{rtype}' not in"
                            f" {sorted(allowed)} for ({src_type} -> {tgt_type})"
                        ),
                        target_id=obj_id,
                    )
                )
                ok = False

        # Indicator must have pattern + pattern_type
        if obj_type == "indicator":
            if not obj.get("pattern"):
                issues.append(
                    ValidationIssue(
                        layer="semantic",
                        code="indicator_missing_pattern",
                        message=f"indicator {obj_id} missing pattern",
                        target_id=obj_id,
                    )
                )
                ok = False
            if not obj.get("pattern_type"):
                issues.append(
                    ValidationIssue(
                        layer="semantic",
                        code="indicator_missing_pattern_type",
                        message=f"indicator {obj_id} missing pattern_type",
                        target_id=obj_id,
                    )
                )
                ok = False

        # ATT&CK external_references shape (Phase 2+ but harmless guard now)
        for ref in obj.get("external_references", []) or []:
            ref_dict = ref if isinstance(ref, dict) else _to_dict(ref)
            if ref_dict.get("source_name") != "mitre-attack":
                continue
            ext_id = cast_str(ref_dict.get("external_id", ""))
            if not _ATTACK_TECHNIQUE_RE.match(ext_id):
                issues.append(
                    ValidationIssue(
                        layer="semantic",
                        code="invalid_attack_external_id",
                        message=f"{obj_id}: ATT&CK external_id {ext_id!r} fails T#### format",
                        target_id=obj_id,
                    )
                )
                ok = False

        # kill_chain_phases tactic vocab when chain is mitre-attack
        for kcp in obj.get("kill_chain_phases", []) or []:
            kcp_dict = kcp if isinstance(kcp, dict) else _to_dict(kcp)
            if kcp_dict.get("kill_chain_name") != "mitre-attack":
                continue
            phase = cast_str(kcp_dict.get("phase_name", ""))
            if phase not in _ATTACK_TACTICS:
                issues.append(
                    ValidationIssue(
                        layer="semantic",
                        code="invalid_attack_tactic",
                        message=f"{obj_id}: tactic {phase!r} not in ATT&CK tactic shortnames",
                        target_id=obj_id,
                    )
                )
                ok = False

    return ok


# ----- Public ----------------------------------------------------------------


def validate(cti: IntermediateCTI, bundle: stix2.v21.Bundle) -> ValidationResult:
    """Run all three runtime validation layers."""
    issues: list[ValidationIssue] = []

    pydantic_ok = _check_pydantic_invariants(cti, issues)
    parse_ok = _check_strict_parse(bundle, issues)
    semantic_ok = _check_semantics(bundle, issues)

    return ValidationResult(
        pydantic_ok=pydantic_ok,
        parse_ok=parse_ok,
        semantic_ok=semantic_ok,
        issues=issues,
    )


__all__ = ["ValidationIssue", "ValidationResult", "validate"]
