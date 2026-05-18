---
phase: 5
title: "Regex IOC extractor with defang/refang"
status: pending
priority: P1
effort: "3d"
dependencies: [03, 04]
file_ownership:
  create:
    - app/extractors/__init__.py
    - app/extractors/regex_ioc/__init__.py
    - app/extractors/regex_ioc/extractor.py
    - app/extractors/regex_ioc/patterns.py
    - app/extractors/regex_ioc/defang.py
    - app/extractors/regex_ioc/normalize.py
    - app/extractors/regex_ioc/version.py
    - tests/unit/extractors/test_regex_ioc.py
    - tests/unit/extractors/test_defang.py
    - tests/unit/extractors/test_patterns_per_type.py
    - tests/fixtures/ioc/known-iocs-by-type.json
    - tests/fixtures/ioc/defang-corpus.txt
    - scripts/eval_ioc.py
---

# Phase 05 — Regex IOC extractor with defang/refang

## Overview

Deterministic, high-precision IOC extraction. Per-type compiled patterns operate on each chunk; defanged forms refanged before normalization; every match emits an `IocCandidate` with `evidence_ids` pointing to exact char offsets in the source. No LLM, no encoder — just regex + a small normalization layer. This is the trust floor of the whole project: if rule-based extraction is noisy, every later metric is noisy too.

## Requirements

### Functional
- Per-type extraction for: ipv4, ipv6, domain, url, email, md5, sha1, sha256, sha512, cve, asn (Phase 1 set; file_path / registry_key / mutex deferred to Phase 2)
- Refang 10 common defang formats from research-01 before matching where appropriate
- Normalize each match: lowercase domains/emails, validate IP octets, validate CVE format, etc.
- Emit `IocCandidate` per match with deterministic `evidence_id` keyed on `(chunk_id, char_start, char_end, type)`
- De-duplicate per `(type, normalized)` within a document; merge `evidence_ids`

### Non-functional
- Strict per-type precision ≥ 0.98, recall ≥ 0.85 on `known-iocs-by-type.json` holdout
- Throughput: 10 000 chunks/sec on commodity laptop (single core)
- No catastrophic backtracking under adversarial input (REDOS test included)
- Coverage ≥ 90% on `app/extractors/regex_ioc/`

## Architecture

### Layout

```
app/extractors/regex_ioc/
├── __init__.py        # exports extract(...)
├── extractor.py       # main loop: chunk -> IocCandidate[]
├── patterns.py        # compiled regex per type
├── defang.py          # refang utility
├── normalize.py       # per-type normalization
└── version.py         # __extractor_name__ = "regex_ioc", __version__ = "1.0.0"
```

### Patterns (`patterns.py`)

```python
import re

PATTERNS: dict[IocType, re.Pattern[str]] = {
    IocType.IPV4: re.compile(
        r"\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
        r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b"
    ),
    IocType.IPV6: re.compile(
        r"(?:[A-Fa-f0-9]{1,4}:){7}[A-Fa-f0-9]{1,4}"
        r"|(?:[A-Fa-f0-9]{1,4}:){1,7}:|"
        r"::(?:[A-Fa-f0-9]{1,4}:){0,6}[A-Fa-f0-9]{1,4}"
    ),
    IocType.DOMAIN: re.compile(
        r"\b(?=[a-zA-Z0-9-]{1,63}\.)"
        r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+"
        r"[a-zA-Z]{2,24}\b"
    ),
    IocType.URL: re.compile(
        r"https?://[^\s<>\"'`]+",
        re.IGNORECASE,
    ),
    IocType.EMAIL: re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
    ),
    IocType.MD5: re.compile(r"\b[a-fA-F0-9]{32}\b"),
    IocType.SHA1: re.compile(r"\b[a-fA-F0-9]{40}\b"),
    IocType.SHA256: re.compile(r"\b[a-fA-F0-9]{64}\b"),
    IocType.SHA512: re.compile(r"\b[a-fA-F0-9]{128}\b"),
    IocType.CVE: re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE),
    IocType.ASN: re.compile(r"\bAS\d{1,10}\b"),
}
```

### Defang (`defang.py`)

Order matters — most specific first:
```python
DEFANG_RULES = [
    (re.compile(r"hxxps?://", re.IGNORECASE), lambda m: m.group(0).replace("hxxp", "http").replace("HXXP", "HTTP")),
    (re.compile(r"\bfxp://", re.IGNORECASE), lambda m: "ftp://"),
    (re.compile(r"\[://\]"), lambda m: "://"),
    (re.compile(r"\[\.\]"), lambda m: "."),
    (re.compile(r"\(\.\)"), lambda m: "."),
    (re.compile(r"\[d\]"), lambda m: "."),
    (re.compile(r"\[at\]"), lambda m: "@"),
    (re.compile(r"\[@\]"), lambda m: "@"),
    (re.compile(r"[​‌‍﻿]"), lambda m: ""),  # zero-width
]

def refang(text: str) -> tuple[str, list[tuple[int, int, str, str]]]:
    """Returns (refanged_text, replacements) where each replacement = (orig_start, orig_end, orig, replacement)."""
```

Critical: **track offsets**. After refang, original char positions shift. The function must return a mapping so the extractor can resolve a match in refanged text back to its position in the **original chunk text** (which is what evidence_ids point to).

Strategy: do not actually rewrite the chunk. Instead, run regex on a virtual view: build a list of (orig_idx, refanged_char) tuples; regex sees refanged stream; on match, look up orig start/end via index lookup. This avoids drift.

### Normalize (`normalize.py`)

| Type | Normalization |
|---|---|
| ipv4 | parse to octets, reject reserved (0.0.0.0/8, 127.0.0.0/8, 169.254.0.0/16, 224.0.0.0/4, 240.0.0.0/4) |
| ipv6 | `ipaddress.IPv6Address`, compress |
| domain | lowercase, strip trailing dot, reject single-label, reject TLDs not in IANA list |
| url | parse with `urllib.parse`, lowercase scheme + host, preserve path |
| email | lowercase domain part, preserve local-part case |
| hashes | lowercase hex |
| cve | uppercase `CVE-YYYY-NNNN+` |
| asn | uppercase `AS` + integer |

### Extractor flow

```python
def extract(chunk: Chunk) -> list[IocCandidate]:
    refanged_view = build_refanged_view(chunk.text)
    out: dict[tuple[IocType, str], IocCandidate] = {}

    for ioc_type, pattern in PATTERNS.items():
        for m in pattern.finditer(refanged_view.text):
            orig_start, orig_end = refanged_view.resolve(m.start(), m.end())
            value = chunk.text[orig_start:orig_end]
            normalized = normalize(ioc_type, m.group(0))
            if normalized is None:
                continue  # rejected by validator

            ev = Evidence(
                evidence_id=deterministic_evidence_id(chunk.chunk_id, orig_start, orig_end, ioc_type),
                chunk_id=chunk.chunk_id,
                text_span=value,
                char_start=chunk.char_start + orig_start,
                char_end=chunk.char_start + orig_end,
            )

            key = (ioc_type, normalized)
            if key in out:
                out[key].evidence_ids.append(ev.evidence_id)
            else:
                out[key] = IocCandidate(
                    type=ioc_type,
                    value=value,
                    normalized=normalized,
                    evidence_ids=[ev.evidence_id],
                    confidence=1.0,  # rule-based = high
                    extractor=f"regex_ioc@{__version__}",
                )
            yield ev

    return list(out.values())
```

(Yields evidences as side effect, returns deduped IocCandidate list. In real impl, return both via a wrapper struct.)

### Filtering false positives
Phase 1 rejects:
- Domains with TLD not in IANA list (catches `something.local`, `README.md` mistaken as domain)
- IPs in reserved ranges (catches `127.0.0.1`, `0.0.0.0`)
- Hashes inside obvious code identifier patterns: `0x[a-f0-9]{64}` — match but lower confidence
- URLs with auth credentials: log + retain (analyst will review; could be IOC)

## Implementation steps

1. Define `app/extractors/regex_ioc/version.py` with name + version constants.
2. Implement `patterns.py` with all 11 compiled regexes.
3. Implement `defang.py` with refang tracking offset map.
4. Implement `normalize.py` per-type normalization + IANA TLD list (cache `tlds-alpha-by-domain.txt` snapshot in `tests/fixtures/iana/`).
5. Implement `extractor.py` main loop with deduplication.
6. Build `tests/fixtures/ioc/known-iocs-by-type.json`: 30 each of (ipv4, domain, url, email, md5, sha256, cve), with positive and adversarial negative examples.
7. Build `tests/fixtures/ioc/defang-corpus.txt`: 50 defanged samples covering all 10 patterns.
8. Write `tests/unit/extractors/test_regex_ioc.py`:
   - happy path per type
   - empty input → empty output
   - dedup: same domain twice → one IocCandidate with two evidence_ids
   - reserved IP rejected
   - non-IANA TLD rejected
   - REDOS test: 10MB of `aaaa@aaaa.com aaaa@aaaa.com ...` parses < 1s
9. Write `tests/unit/extractors/test_defang.py`:
   - all 10 defang patterns refang correctly
   - offset map round-trips: pre-defang position == post-defang resolved position
10. Write `tests/unit/extractors/test_patterns_per_type.py`:
    - per-type precision/recall ≥ 0.98 / 0.85 on holdout fixture
11. Write `scripts/eval_ioc.py`: load fixture, run extractor, print precision/recall/F1 per type. Used in `make eval-ioc`.
12. Add `make eval-ioc` target invoking the script.
13. `make test && make types && make lint && make security && make eval-ioc` green.
14. Commit: `feat(p05): regex IOC extractor with defang and offset preservation`. Push.

## Success criteria

- [ ] All 11 IOC types extract from holdout fixture
- [ ] Per-type precision ≥ 0.98, recall ≥ 0.85
- [ ] Defang offset round-trip property test passes 100 cases
- [ ] REDOS test passes (no pattern hangs > 1s on 10MB malicious input)
- [ ] Dedup: 100-IOC chunk with 30 duplicates → 70 IocCandidates with merged evidence_ids
- [ ] `IocCandidate` invariant satisfied — every candidate has ≥1 evidence_id

## Risk assessment

| Risk | Mitigation |
|---|---|
| Domain regex catches version strings (`v1.2.3`) | TLD whitelist via IANA list; reject TLDs ≤ 1 char or numeric-only |
| Hash regex catches non-hash hex strings (commit SHAs in code) | Confidence 1.0 anyway; analyst filters in review queue (Phase 2) |
| URL regex over-greedy on trailing punctuation | Stop at `<>"'\``; trim trailing `.,)!?` heuristic |
| Defang offset map drift on overlapping patterns | Apply rules longest-match-first; explicit test for `hxxps://evil[.]com` (two patterns) |
| IPv6 regex false positives on hex sequences | Require ≥2 colons in match; validate via `ipaddress.IPv6Address` |
| IANA TLD list staleness | Refresh quarterly; pin snapshot in fixtures with download timestamp |
