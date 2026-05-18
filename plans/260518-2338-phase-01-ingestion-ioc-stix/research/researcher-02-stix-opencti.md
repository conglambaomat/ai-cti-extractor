# Research Report — STIX 2.1 + OpenCTI

**Date:** 2026-05-18
**Author:** main session (sub-agents lost on session resume; synthesized from training knowledge + library docs)
**Scope:** Phase 1 STIX subset (`report`, `indicator`, `relationship`) with strict validation + OpenCTI round-trip.

---

## A. cti-python-stix2 (OASIS official)

### A.1 Version + compatibility
- **Library:** `stix2` on PyPI (a.k.a. cti-python-stix2). Repo: https://github.com/oasis-open/cti-python-stix2
- **Pin:** `stix2 >=3.0.1, <4` — 3.x defaults to STIX 2.1 (`stix2.v21.*`). Python 3.11+ supported.
- **Companion:** `taxii2-client >=2.3.0` for TAXII 2.1 (deferred to Phase 3+ per roadmap).

### A.2 Builder API minimum required fields

```python
import stix2

# Indicator (Phase 1 core target)
ind = stix2.v21.Indicator(
    pattern="[ipv4-addr:value = '203.0.113.5']",
    pattern_type="stix",                       # required for STIX 2.1
    valid_from="2026-05-18T00:00:00Z",         # required
    indicator_types=["malicious-activity"],    # open vocab; recommended
    name="C2 IP from Mandiant report",
    description="Observed in DELIVERY phase of intrusion",
)

# Report
rep = stix2.v21.Report(
    name="APT-X Campaign Report",
    published="2026-05-18T00:00:00Z",
    report_types=["threat-report"],
    object_refs=[ind.id],                       # MUST contain ≥1 ref
    description="Mandiant report on APT-X infrastructure",
)

# Relationship
rel = stix2.v21.Relationship(
    source_ref=ind.id,
    target_ref="malware--<uuid>",                # forward-ref OK if in same bundle
    relationship_type="indicates",               # STIX 2.1 vocab; "indicates" links Indicator -> Malware
    description="IP belongs to APT-X C2 infrastructure",
)

bundle = stix2.v21.Bundle(objects=[rep, ind, rel])
```

### A.3 Indicator pattern syntax (STIX 2.1)

| IOC type | Pattern |
|---|---|
| IPv4 | `[ipv4-addr:value = '203.0.113.5']` |
| IPv6 | `[ipv6-addr:value = '2001:db8::1']` |
| Domain | `[domain-name:value = 'evil.example.com']` |
| URL | `[url:value = 'https://evil.example.com/payload']` |
| MD5 | `[file:hashes.MD5 = 'd41d8cd98f00b204e9800998ecf8427e']` |
| SHA-256 | `[file:hashes.'SHA-256' = 'e3b0c44...']` |
| Email addr | `[email-addr:value = 'attacker@evil.com']` |
| CVE | (CVE is `vulnerability` STIX object, NOT an indicator pattern. Build as `Vulnerability(external_references=[{source_name:'cve', external_id:'CVE-2024-XXXX'}])`.) |

Quotes: hash names with hyphen (`SHA-256`, `SHA-512`) need single quotes around the dict key. Library validates this.

### A.4 Deterministic IDs (CRITICAL for Phase 1)

Default behavior: `Indicator(...)` generates random UUIDv4. **Bad** for re-runs — every pipeline execution creates new STIX object IDs, breaks audit + dedup.

**Solution:** UUIDv5 keyed on `(document_id, claim_hash)` where `claim_hash = sha256(pattern + pattern_type)[:32]`:

```python
import uuid, hashlib
NS = uuid.UUID("a4d70b75-6f4a-5c66-8b6e-9c1f5d2a3e4f")  # project-scoped namespace, fixed

def deterministic_id(doc_id: str, pattern: str, pattern_type: str = "stix") -> str:
    seed = f"{doc_id}|{pattern_type}|{pattern}"
    return f"indicator--{uuid.uuid5(NS, seed)}"

ind = stix2.v21.Indicator(
    id=deterministic_id("doc-uuid-123", "[ipv4-addr:value = '203.0.113.5']"),
    pattern="[ipv4-addr:value = '203.0.113.5']",
    pattern_type="stix",
    valid_from="2026-05-18T00:00:00Z",
)
```

NS UUID: pick once for project, never change. Same `(doc_id, pattern)` -> same indicator ID across runs.

### A.5 ATT&CK link via external_references

```python
ap = stix2.v21.AttackPattern(
    name="PowerShell",
    external_references=[{
        "source_name": "mitre-attack",
        "external_id": "T1059.001",
        "url": "https://attack.mitre.org/techniques/T1059/001/",
    }],
    kill_chain_phases=[{
        "kill_chain_name": "mitre-attack",
        "phase_name": "execution",   # MUST match ATT&CK tactic shortname
    }],
)
```

ATT&CK tactic shortnames: `reconnaissance`, `resource-development`, `initial-access`, `execution`, `persistence`, `privilege-escalation`, `defense-evasion`, `credential-access`, `discovery`, `lateral-movement`, `collection`, `command-and-control`, `exfiltration`, `impact`.

### A.6 Pitfalls
- **`allow_custom=False`** — keep this. Phase 1 has zero need for custom properties. If Phase 2 needs analyst notes, use `note` STIX object instead of custom fields.
- **`revoked` / `modified`** — leave default. Phase 1 doesn't update objects.
- **Versioning** — STIX has built-in object versioning via `modified` timestamp. Out of scope Phase 1 (only `created`).
- **Spec compliance vs OpenCTI quirks:** OpenCTI internally uses STIX 2.1 but adds custom OCTI properties (e.g., `x_opencti_score`). Strip these on import; preserve only on export if Phase 2+.

## B. STIX validation layers

### Layer 1 — Pydantic invariants (we control)
Phase 1 must enforce:
1. Every `IocCandidate` has ≥1 `evidence_id`.
2. Every `evidence_id` resolves to chunk with valid `(char_start, char_end)`.
3. `pattern` field non-empty + matches `^\[\w+(-\w+)*:.+\]$` (trivial STIX pattern smell test).
4. `valid_from` is RFC3339 UTC.
5. Indicator `name` ≤ 1024 chars; `description` ≤ 8192 chars.

### Layer 2 — `stix2.parse(allow_custom=False)`
**Catches:** missing required fields, wrong vocab values, ID format `<type>--<uuid>`, malformed pattern grammar, custom properties without `allow_custom`.
**Misses:** semantic refs (e.g., relationship pointing to non-existent ID in same bundle), kill_chain_phase value semantics, ATT&CK ID validity.

### Layer 3 — Semantic checks (Phase 1 must-have, recommend 6)
1. Every `Relationship.source_ref` and `target_ref` resolves to an object in the bundle (or to a known canonical ID like ATT&CK pattern).
2. Every `Report.object_refs` references existing objects in bundle.
3. `relationship_type` belongs to STIX 2.1 vocab subset for the (source_type, target_type) pair (e.g., `indicates` is valid Indicator→Malware/Tool/AttackPattern, NOT Indicator→Report).
4. `kill_chain_phases[*].kill_chain_name == "mitre-attack"` → `phase_name` in ATT&CK tactic shortname list.
5. `external_references[?source_name=='mitre-attack'].external_id` matches `^T\d{4}(\.\d{3})?$` and resolves in local ATT&CK snapshot.
6. No Indicator without `pattern` + `pattern_type` (Phase 2 may add Indicator-without-pattern but Phase 1 rejects).

### Layer 4 — Hypothesis property tests (3 invariants)
1. **Round-trip parse:** `stix2.parse(json.dumps(bundle.serialize()), allow_custom=False) == bundle` (idempotent serialization).
2. **Ref closure:** for any generated bundle, every relationship endpoint exists in bundle.objects.
3. **Pattern grammar:** every Indicator generated by builder must have a pattern that passes `stix2.pattern_visitor.parse_pattern()`.

## C. OpenCTI integration

### C.1 Client
- **`pycti`** — official OpenCTI client. Repo: https://github.com/OpenCTI-Platform/client-python
- **Pin:** `pycti >=6.0.0` matching OpenCTI server major version. Phase 1 against latest stable OpenCTI (6.x as of mid-2026).

### C.2 Local dev instance (minimal services)

`OpenCTI-Platform/docker/docker-compose.yml` brings up: `redis`, `elasticsearch`, `minio`, `rabbitmq`, `opencti`, `worker`, `connector-import-document-file`, plus several connectors. **For Phase 1 round-trip test**, only need:
- `redis`, `elasticsearch`, `minio`, `rabbitmq` (mandatory deps)
- `opencti` (server)
- `worker` (one instance enough for ingest)

Skip all `connector-*` services. Disable in compose override.

Ports: OpenCTI UI on `:8080`, GraphQL endpoint at `http://localhost:8080/graphql`.

### C.3 Bundle import
```python
from pycti import OpenCTIApiClient

client = OpenCTIApiClient(
    url="http://localhost:8080",
    token="<admin-token-from-UI>",
)

# Submit a STIX bundle
client.stix2.import_bundle_from_json(
    json_data=bundle.serialize(),
    update=True,
    types=None,        # import all object types in bundle
)
```

### C.4 Round-trip query
After import, query back the Report via STIX ID:
```python
report_back = client.report.read(id=rep.id)
# report_back is dict with OpenCTI internal field names (camelCase + x_opencti_*)
# Compare core fields: name, published, description, object_refs/objectRefs
```

Equivalence assertion: compare `(name, published, len(object_refs), {ind.id for ind in object_refs})`. Don't expect byte-equal — OpenCTI normalizes timestamps, may strip blank fields, adds `x_opencti_score`.

### C.5 Auth env var
`pycti` reads from `OPENCTI_URL` and `OPENCTI_TOKEN` env vars by default (or pass to constructor). Project `.env.example` already has both.

### C.6 Common round-trip failure modes
1. **Timezone drift:** STIX requires `Z` UTC suffix. OpenCTI accepts `+00:00` but normalizes. Always serialize with `Z`.
2. **`object_refs` order:** STIX preserves order; OpenCTI re-orders alphabetically on read. Don't assert order; assert set equality.
3. **`external_references` deduplication:** OpenCTI dedupes by `(source_name, external_id)` tuple. Duplicates silently merged.
4. **`Report.object_refs` to non-imported objects:** if bundle references an ID not in bundle and not in OpenCTI yet, ref is dropped silently. Always include all referenced objects in same bundle.
5. **Custom OpenCTI properties:** `x_opencti_*` props in bundle bypass `allow_custom=False`. Strip them at export boundary.

## Unresolved questions

1. **OpenCTI worker latency** — bundle import is async via worker queue. Round-trip test must poll for read completion (suggest exponential backoff, max 30s) before asserting. Will document in test fixture.
2. **STIX 2.1 spec ambiguity:** `Report.report_types` vocab — open or closed? Library accepts arbitrary strings, but OpenCTI may reject unknown values. Test with `["threat-report", "campaign", "malware"]` first.
3. **Indicator pattern validation cost:** `stix2.parse_pattern()` is non-trivial; should we cache validated patterns? Phase 1 likely fine; revisit if validation > 5% of pipeline time.

---

**Status:** DONE
**Summary:** stix2 v3.0.1+ for builders with deterministic UUIDv5 IDs; 4-layer validation (Pydantic, parse, semantic, Hypothesis); pycti for OpenCTI roundtrip with minimal-service docker compose; 5 known round-trip pitfalls documented.
**Concerns/Blockers:** None blocking. Worker latency requires polling pattern in roundtrip tests.
