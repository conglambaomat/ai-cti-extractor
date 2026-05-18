---
phase: 4
title: "Intermediate CTI JSON schema (Pydantic)"
status: pending
priority: P1
effort: "2d"
dependencies: [02]
file_ownership:
  create:
    - app/schemas/__init__.py
    - app/schemas/document.py
    - app/schemas/evidence.py
    - app/schemas/ioc.py
    - app/schemas/intermediate_cti.py
    - app/schemas/provenance.py
    - tests/unit/schemas/test_intermediate_cti.py
    - tests/unit/schemas/test_evidence_invariant.py
---

# Phase 04 — Intermediate CTI JSON schema

## Overview

Define the canonical internal representation that bridges raw text and STIX 2.1. Every extracted fact lives here first; STIX is **built from** this schema, not from text directly. Strict Pydantic v2 invariants enforce evidence grounding at the type level — an `IocCandidate` without ≥1 `evidence_id` cannot be instantiated.

## Requirements

### Functional
- Pydantic models for: `Document`, `Chunk`, `Evidence`, `IocCandidate`, `IntermediateCTI`, `Provenance`
- `IntermediateCTI.model_validate(payload)` rejects any candidate lacking evidence
- Serialization to JSON preserves all fields; round-trip `model_validate(model.model_dump_json())` returns equivalent
- Provenance is append-only (no mutation of existing extractor entries)

### Non-functional
- mypy --strict clean; no `Any` escapes
- All fields documented with `Field(description=...)`
- Validation error messages name the specific invariant violated
- Performance: instantiate 10 000 `IocCandidate` < 1s

## Architecture

### Schema layout

```
app/schemas/
├── __init__.py            # exports public types
├── document.py            # DocumentMeta, ChunkRef
├── evidence.py            # Evidence (with offset invariants)
├── ioc.py                 # IocCandidate, IocType enum
├── intermediate_cti.py    # IntermediateCTI (top-level), Candidates container
└── provenance.py          # Provenance, ExtractorRun
```

### `app/schemas/evidence.py`

```python
from pydantic import BaseModel, Field, model_validator

class Evidence(BaseModel):
    evidence_id: str = Field(pattern=r"^e-[0-9a-f]{16,}$")
    chunk_id: str
    text_span: str = Field(min_length=1, max_length=8192)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_offsets(self) -> "Evidence":
        if self.char_end <= self.char_start:
            raise ValueError("char_end must be > char_start")
        return self
```

### `app/schemas/ioc.py`

```python
class IocType(str, Enum):
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
    FILE_PATH = "file_path"
    REGISTRY_KEY = "registry_key"
    MUTEX = "mutex"

class IocCandidate(BaseModel):
    type: IocType
    value: str = Field(min_length=1, max_length=2048)
    normalized: str = Field(description="defanged + normalized, used for STIX pattern")
    evidence_ids: list[str] = Field(min_length=1, description="MUST have ≥1 evidence")
    confidence: float = Field(ge=0.0, le=1.0)
    extractor: str = Field(description="extractor name + version, e.g. 'regex_ioc@1.0'")
```

### `app/schemas/intermediate_cti.py`

```python
class Candidates(BaseModel):
    iocs: list[IocCandidate] = Field(default_factory=list)
    # Phase 2+ adds: entities, relations, events, attack_mappings

class IntermediateCTI(BaseModel):
    document: DocumentMeta
    chunks: list[ChunkRef]
    candidates: Candidates
    evidence: list[Evidence]
    provenance: Provenance
    version: str = "2026.05.18"

    @model_validator(mode="after")
    def _evidence_closure(self) -> "IntermediateCTI":
        evidence_ids = {e.evidence_id for e in self.evidence}
        chunk_ids = {c.chunk_id for c in self.chunks}
        for e in self.evidence:
            if e.chunk_id not in chunk_ids:
                raise ValueError(f"evidence {e.evidence_id} references unknown chunk {e.chunk_id}")
        for ioc in self.candidates.iocs:
            for eid in ioc.evidence_ids:
                if eid not in evidence_ids:
                    raise ValueError(f"ioc {ioc.value!r} references unknown evidence {eid}")
        return self
```

### `app/schemas/provenance.py`

```python
class ExtractorRun(BaseModel):
    name: str           # e.g., "regex_ioc"
    version: str        # e.g., "1.0.0"
    model: str | None = None  # populated for LLM/encoder runs
    started_at: datetime
    ended_at: datetime
    config_hash: str    # sha256 of config used

class Provenance(BaseModel):
    extractors: list[ExtractorRun] = Field(default_factory=list)
    pipeline_version: str
    schema_version: str = "2026.05.18"

    def append(self, run: ExtractorRun) -> "Provenance":
        return self.model_copy(update={"extractors": [*self.extractors, run]})
```

(Append-only via `model_copy`; original frozen.)

## Implementation steps

1. Create all 5 schema files per spec.
2. Wire imports from `app/schemas/__init__.py`.
3. Write `tests/unit/schemas/test_intermediate_cti.py`:
   - Happy path: build full document + 1 IOC + evidence + provenance, serialize, round-trip
   - Negative: IOC with empty `evidence_ids` raises `ValidationError`
   - Negative: evidence references missing chunk_id raises
   - Negative: IOC references missing evidence_id raises
   - Negative: invalid offset (start ≥ end) raises
4. Write `tests/unit/schemas/test_evidence_invariant.py`:
   - Property test: any IocCandidate generated by Hypothesis with ≥1 evidence_id passes; with 0 fails
   - Round-trip: `IntermediateCTI.model_validate(model.model_dump())` returns equivalent
5. Performance benchmark: instantiate 10 000 IocCandidates with Hypothesis stub data < 1s.
6. `make test && make types && make lint` green.
7. Commit: `feat(p04): intermediate CTI Pydantic schema with evidence invariants`. Push.

## Success criteria

- [ ] All schema models import cleanly
- [ ] Empty `evidence_ids` raises `ValidationError` mentioning "evidence_ids"
- [ ] Round-trip JSON preserves all fields
- [ ] Property test: 100 random valid models all pass; 100 with empty evidence all fail
- [ ] mypy --strict clean

## Risk assessment

| Risk | Mitigation |
|---|---|
| Pydantic v2 `model_validator(mode='after')` interaction with `model_copy` | Test explicitly: copy + revalidate goes through validator chain |
| Forward references between schemas (chunks ↔ evidence) | Single top-level `IntermediateCTI` validates closure; sub-models stay independent |
| Schema drift between Phase 1 and later phases | `version` field present; bump when adding `entities`/`relations` in Phase 2 |
| `IocType` enum churn | Phase 1 freezes 14 types; new types added only with migration note |
