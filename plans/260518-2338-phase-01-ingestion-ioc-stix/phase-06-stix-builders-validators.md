---
phase: 6
title: "STIX 2.1 builders + 4-layer validation"
status: pending
priority: P1
effort: "4d"
dependencies: [04, 05]
file_ownership:
  create:
    - app/stix/__init__.py
    - app/stix/ids.py
    - app/stix/ioc_to_pattern.py
    - app/stix/builders.py
    - app/stix/validators.py
    - app/stix/exporters.py
    - app/stix/version.py
    - tests/unit/stix/test_ids.py
    - tests/unit/stix/test_pattern_translation.py
    - tests/unit/stix/test_builders.py
    - tests/unit/stix/test_validators.py
    - tests/property/test_stix_invariants.py
    - tests/fixtures/stix/golden-bundle.json
    - tests/fixtures/stix/known-bad-bundles/
---

# Phase 06 — STIX 2.1 builders + 4-layer validation

## Overview

Translate the intermediate CTI JSON into a valid STIX 2.1 bundle. Phase 1 ships only three object types (`Report`, `Indicator`, `Relationship`), but with full strictness — deterministic UUIDv5 IDs, layered validation (Pydantic → `stix2.parse(allow_custom=False)` → semantic checks → Hypothesis property tests), no custom properties, every object traceable back to evidence.

This phase is where evidence grounding meets the OASIS spec. Get it wrong and OpenCTI silently rejects bundles in Phase 8.

## Requirements

### Functional
- `build_bundle(intermediate_cti) -> stix2.v21.Bundle` produces a parseable bundle
- Indicator IDs are `indicator--{uuidv5(NS, doc_id|pattern_type|pattern)}` — deterministic across runs
- Report IDs are `report--{uuidv5(NS, doc_id|"report")}`
- Relationship IDs are `relationship--{uuidv5(NS, source_ref|relationship_type|target_ref)}`
- `validate(bundle) -> ValidationResult` runs all 4 layers; aggregates errors
- Every Indicator has `pattern`, `pattern_type="stix"`, `valid_from`
- Every Report has `name`, `published`, `report_types`, `object_refs`

### Non-functional
- Bundle build for 50 IOCs < 100 ms
- `mypy --strict` clean
- Coverage ≥ 90% on `app/stix/`
- 100 Hypothesis property cases pass

## Architecture

### Layout

```
app/stix/
├── __init__.py
├── ids.py                  # deterministic UUIDv5 helpers
├── ioc_to_pattern.py       # IocCandidate -> STIX pattern string
├── builders.py             # IntermediateCTI -> Bundle
├── validators.py           # 4-layer validate()
├── exporters.py            # Bundle -> JSON (canonical, sorted)
└── version.py
```

### Deterministic IDs (`ids.py`)

```python
import uuid

# Project namespace UUID — pick once, never change
PROJECT_NS = uuid.UUID("a4d70b75-6f4a-5c66-8b6e-9c1f5d2a3e4f")

def indicator_id(doc_id: str, pattern: str, pattern_type: str = "stix") -> str:
    seed = f"{doc_id}|{pattern_type}|{pattern}"
    return f"indicator--{uuid.uuid5(PROJECT_NS, seed)}"

def report_id(doc_id: str) -> str:
    return f"report--{uuid.uuid5(PROJECT_NS, f'{doc_id}|report')}"

def relationship_id(source_ref: str, relationship_type: str, target_ref: str) -> str:
    seed = f"{source_ref}|{relationship_type}|{target_ref}"
    return f"relationship--{uuid.uuid5(PROJECT_NS, seed)}"
```

### IOC → STIX pattern (`ioc_to_pattern.py`)

Per-type translator, pure function:
```python
def ioc_to_stix_pattern(ioc: IocCandidate) -> str:
    n = ioc.normalized
    match ioc.type:
        case IocType.IPV4:    return f"[ipv4-addr:value = '{n}']"
        case IocType.IPV6:    return f"[ipv6-addr:value = '{n}']"
        case IocType.DOMAIN:  return f"[domain-name:value = '{n}']"
        case IocType.URL:     return f"[url:value = '{escape(n)}']"
        case IocType.EMAIL:   return f"[email-addr:value = '{n}']"
        case IocType.MD5:     return f"[file:hashes.MD5 = '{n}']"
        case IocType.SHA1:    return f"[file:hashes.'SHA-1' = '{n}']"
        case IocType.SHA256:  return f"[file:hashes.'SHA-256' = '{n}']"
        case IocType.SHA512:  return f"[file:hashes.'SHA-512' = '{n}']"
        case IocType.CVE:     raise ValueError("CVE → Vulnerability object, not Indicator")  # Phase 2
        case IocType.ASN:     return f"[autonomous-system:number = {int(n.removeprefix('AS'))}]"
        case _: raise ValueError(f"unsupported type {ioc.type}")
```

`escape(s)` doubles single quotes per STIX 2.1 pattern grammar.

### Bundle builder (`builders.py`)

```python
def build_bundle(cti: IntermediateCTI) -> stix2.v21.Bundle:
    objects: list[Any] = []
    indicator_refs: list[str] = []

    for ioc in cti.candidates.iocs:
        if ioc.type is IocType.CVE:
            continue  # Phase 2: produces Vulnerability instead

        pattern = ioc_to_stix_pattern(ioc)
        ind_id = indicator_id(cti.document.id, pattern)
        ind = stix2.v21.Indicator(
            id=ind_id,
            pattern=pattern,
            pattern_type="stix",
            valid_from=cti.document.ingested_at,
            indicator_types=["malicious-activity"],
            description=f"Extracted by {ioc.extractor} from chunk {_first_chunk(ioc, cti)}",
            confidence=int(ioc.confidence * 100),
        )
        objects.append(ind)
        indicator_refs.append(ind_id)

    rep_id = report_id(cti.document.id)
    rep = stix2.v21.Report(
        id=rep_id,
        name=cti.document.title or f"Report {cti.document.id}",
        published=cti.document.ingested_at,
        report_types=["threat-report"],
        object_refs=indicator_refs,
        description=cti.document.source_uri,
    )
    objects.insert(0, rep)

    # Phase 1: no Relationship objects yet (no entities to link to).
    # Relationship is reserved for Phase 2 when malware/threat-actor objects are added.

    return stix2.v21.Bundle(objects=objects, allow_custom=False)
```

Note: Phase 1 emits **no Relationship** because the only entities present are Indicators and one Report. STIX `Report.object_refs` already links the Report to its Indicators; a separate Relationship would be redundant. Phase 2 adds Malware/Threat-Actor objects — that's when Relationship fires.

The plan doc lists `relationship` as Phase 1 STIX subset because the **builder skeleton** ships in Phase 1, with one tested end-to-end case (e.g., `Indicator --indicates--> Malware` synthesized from a manual fixture). We get the relationship_type vocab + reference resolution tested without needing real Phase 2 entities.

### Validators (`validators.py`)

```python
class ValidationResult(BaseModel):
    parse_ok: bool
    semantic_ok: bool
    pydantic_ok: bool
    hypothesis_invariants_ok: bool | None = None  # only when running property tests
    errors: list[ValidationError] = []

def validate(cti: IntermediateCTI, bundle: stix2.v21.Bundle) -> ValidationResult:
    errors = []

    # Layer 1 — Pydantic invariants on intermediate (already enforced by schema, double-check here)
    pydantic_ok = _check_evidence_closure(cti, errors)

    # Layer 2 — stix2.parse strict
    try:
        reparsed = stix2.parse(json.loads(bundle.serialize()), allow_custom=False)
        parse_ok = True
    except stix2.exceptions.STIXError as e:
        parse_ok = False
        errors.append(ValidationError(layer="parse", message=str(e)))

    # Layer 3 — semantic checks
    semantic_ok = _check_semantics(bundle, errors)

    return ValidationResult(parse_ok=parse_ok, semantic_ok=semantic_ok, pydantic_ok=pydantic_ok, errors=errors)
```

Semantic checks (Phase 1):
1. Every `Relationship.source_ref` and `target_ref` resolves to an object in bundle (or is a known canonical ID like ATT&CK pattern from snapshot).
2. Every `Report.object_refs` references an existing object in bundle.
3. `relationship_type` belongs to STIX 2.1 vocab subset for the (source_type, target_type) pair.
4. `kill_chain_phases[*].kill_chain_name == "mitre-attack"` → `phase_name` in ATT&CK tactic shortname list. (Phase 2+; harmless guard in Phase 1.)
5. Every `external_references[?source_name=='mitre-attack'].external_id` matches `^T\d{4}(\.\d{3})?$`. (Phase 2+; harmless.)
6. No Indicator without `pattern + pattern_type`. (Phase 1 enforced.)

### Exporters (`exporters.py`)

```python
def serialize_canonical(bundle: stix2.v21.Bundle) -> str:
    """Sort keys for stable bytes; UTC Z timestamps; no whitespace inside arrays."""
    raw = json.loads(bundle.serialize())
    return json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def bundle_hash(bundle: stix2.v21.Bundle) -> str:
    return hashlib.sha256(serialize_canonical(bundle).encode()).hexdigest()
```

`bundle_hash` used in `exports.bundle_hash` audit field for tamper evidence.

## Implementation steps

1. Implement `app/stix/version.py`, `ids.py`, `ioc_to_pattern.py`.
2. Implement `app/stix/builders.py::build_bundle`.
3. Implement `app/stix/validators.py` with 4 layers + `ValidationResult`.
4. Implement `app/stix/exporters.py::serialize_canonical` + `bundle_hash`.
5. Build `tests/fixtures/stix/golden-bundle.json` (manually crafted, known-good Phase 1 bundle with 1 Report + 3 Indicators).
6. Build `tests/fixtures/stix/known-bad-bundles/`: 5 bundles each violating one semantic check (dangling object_ref, bad relationship_type vocab, custom property leak, etc.).
7. Write `tests/unit/stix/test_ids.py`: deterministic ID property — same input twice → same UUID; different inputs → different UUIDs (collision probability ~ 0).
8. Write `tests/unit/stix/test_pattern_translation.py`: per-type translation + escape correctness; CVE raises.
9. Write `tests/unit/stix/test_builders.py`: build from fixture intermediate CTI → assert object types, count, object_refs closure.
10. Write `tests/unit/stix/test_validators.py`: golden bundle passes all 4 layers; each known-bad bundle fails the right layer.
11. Write `tests/property/test_stix_invariants.py` (Hypothesis):
    - `parse_roundtrip`: any built bundle → serialize → parse → equivalent
    - `ref_closure`: every relationship endpoint exists in bundle
    - `pattern_grammar`: every Indicator pattern parses with `stix2.pattern_visitor.parse_pattern`
12. `make test && make types && make lint && make security` green.
13. Commit: `feat(p06): STIX 2.1 builders with deterministic IDs + 4-layer validation`. Push.

## Success criteria

- [ ] Build 50-IOC bundle in < 100 ms
- [ ] Same intermediate CTI → same bundle hash byte-for-byte across runs
- [ ] Golden bundle passes all 4 validation layers
- [ ] 5 known-bad bundles each fail their target layer (no false positives in passing layers)
- [ ] 100 Hypothesis cases pass for all 3 invariants
- [ ] Coverage ≥ 90% on `app/stix/`

## Risk assessment

| Risk | Mitigation |
|---|---|
| Pattern escape miss for URL containing single quote | Property test with quote-rich URLs; explicit fixture case |
| `confidence` field as float vs int (STIX 2.1 wants 0-100 int) | Round + clamp in builder; test boundary 0/50/100 |
| `published` field timezone (must be Z) | Builder coerces all timestamps to UTC Z; test with `Asia/Bangkok` source |
| Hash collision in deterministic IDs | UUIDv5 collision space 2^122; not a real risk; documented |
| `stix2` library version drift breaking pattern grammar | Pin `stix2 ==3.0.1` in pyproject; CI re-validates golden bundle on every dep update |
| Phase 2 wants to mutate Phase 1 bundle | Bundles are immutable post-creation; new run produces new IDs only if inputs change |
