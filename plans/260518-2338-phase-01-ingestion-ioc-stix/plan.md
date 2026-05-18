---
title: "Phase 1 — Ingestion + IOC + Minimal STIX + OpenCTI Round-trip"
description: "End-to-end pipeline from PDF/HTML/MD/TXT/URL → regex IOC extraction → STIX 2.1 bundle (report+indicator+relationship) → OpenCTI ingest with audit trail."
status: pending
priority: P1
effort: "5-6 weeks (solo dev, evenings)"
branch: feat/phase-01-ingestion-ioc-stix
tags: [phase-1, ingestion, ioc, stix, opencti]
created: 2026-05-18
blockedBy: []
blocks: []
---

# Phase 1 — Ingestion + IOC + Minimal STIX + OpenCTI Round-trip

> **Spec source:** [`docs/AI-assisted_CTI_extractor.md`](../../docs/AI-assisted_CTI_extractor.md)
> **Architecture:** [`docs/system-architecture.md`](../../docs/system-architecture.md)
> **Research:** [`research/researcher-01-ingestion-pdf-html-md.md`](research/researcher-01-ingestion-pdf-html-md.md), [`research/researcher-02-stix-opencti.md`](research/researcher-02-stix-opencti.md)

## Goal

Stand up a working pipeline that takes an English-language threat report (PDF, HTML, Markdown, TXT, or URL), extracts deterministic indicators of compromise with **evidence-span grounding**, builds a **valid STIX 2.1 bundle** (subset: `report`, `indicator`, `relationship`), and pushes it into a local OpenCTI instance with verifiable round-trip equivalence. No NER, no ATT&CK mapping, no LLM judge yet — those are Phase 2/3.

This phase establishes the **invariant contract** for the entire project: every claim → evidence span → STIX object. Get that right; the rest of the system depends on it.

## Non-goals (defer to later phases)

- Domain NER / relation / event extraction → Phase 2
- ATT&CK technique mapping → Phase 2
- LLM judge / RAG → Phase 3
- Knowledge graph entity resolution → Phase 3
- MISP / TAXII export → Phase 4 (or never if OpenCTI sufficient)
- Frontend / analyst review UI → Phase 2

## Phase breakdown

| # | Phase | Effort | Owns |
|---|---|---|---|
| 01 | Bootstrap project + pyproject + Docker stack | 4d | `pyproject.toml`, `docker/`, `app/core/` |
| 02 | Core infrastructure (config, logging, security, db schema) | 3d | `app/core/`, `app/db/` |
| 03 | Ingestion layer (PDF / HTML / MD / TXT / URL + chunking) | 5d | `app/ingestion/` |
| 04 | Intermediate CTI JSON schema (Pydantic) | 2d | `app/schemas/` |
| 05 | Regex IOC extractor + defang/refang | 3d | `app/extractors/regex_ioc/` |
| 06 | STIX 2.1 builders + 4-layer validators | 4d | `app/stix/` |
| 07 | FastAPI service + RQ worker + pipeline orchestrator | 4d | `app/api/`, `app/jobs/` |
| 08 | OpenCTI dev compose + round-trip test + CI | 3d | `docker/opencti/`, `tests/integration/`, `.github/workflows/` |

**Sequencing rules:**
- 01 → 02 (infra before db)
- 02 → 03, 04 (parallel after infra)
- 03 + 04 → 05 (IOC needs chunks + schema)
- 04 → 06 (STIX needs intermediate schema)
- 05 + 06 → 07 (pipeline needs both)
- 07 → 08 (round-trip needs API + worker)

## Acceptance criteria (whole phase)

- [ ] `docker compose up -d` brings up Postgres + Redis + MinIO + (separate compose) OpenCTI dev stack
- [ ] `make migrate` applies Alembic migrations cleanly
- [ ] `make test` passes: ≥ 80% coverage on `app/extractors/regex_ioc/` and `app/stix/`
- [ ] `make eval-ioc` runs IOC eval: precision ≥ 0.98, recall ≥ 0.85 on 30-report custom holdout
- [ ] `mypy --strict app/` clean
- [ ] `ruff check app/` clean
- [ ] `bandit -r app/` no high/medium issues
- [ ] `pip-audit` no high CVEs
- [ ] One sample CTI PDF (Mandiant or Talos) ingests end-to-end, produces valid STIX bundle, round-trips into OpenCTI dev instance, queries back equivalent (set equality on object_refs, name, published)
- [ ] Audit log entry exists for every ingest, extract, export action
- [ ] Every indicator carries `evidence_ids` resolving to chunks with valid offsets
- [ ] All commits follow conventional commits; CI green on `main`

## Key decisions (autonomous mode)

Per CLAUDE.md autonomous policy, these are decided here. Document in journal if reconsidered.

| Decision | Choice | Why |
|---|---|---|
| Job queue | **RQ** | Simplest; sufficient for batch ingestion at Phase 1 scale |
| Lock file | **uv** | Faster than poetry; modern; lockfile compatible with pip |
| Vector store | (deferred to Phase 3 — pgvector when needed) | KISS — no vector retrieval in Phase 1 |
| Linter / formatter | **ruff** (one tool) | Eliminates black + flake8 + isort |
| Type checker | **mypy --strict** | Per CLAUDE.md |
| PDF parser | **pdfplumber** primary, pdfminer.six fallback | Char-offset fidelity (research-01) |
| HTML parser | **trafilatura** primary, BeautifulSoup fallback | Best article extraction (research-01) |
| MD parser | **markdown-it-py** | Only one with AST source positions |
| OCR | **pytesseract**, gated to image-only pages | Keep OCR cheap |
| STIX lib | **stix2 >=3.0.1** | OASIS official; Phase 1 needs only 3 object types |
| OpenCTI client | **pycti >=6.0.0** | Official; matches OpenCTI server major |
| Indicator IDs | UUIDv5 keyed on `(doc_id, pattern, pattern_type)` | Deterministic across re-runs |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| pdfplumber chokes on multi-column AV PDFs | Medium | Fallback to pdfminer.six; keep test corpus diverse |
| OpenCTI worker async ingest causes flaky round-trip tests | High | Polling with backoff (max 30s); explicit `eventually` helper |
| Defang regex misses vendor-specific format | Medium | Maintain golden test fixture; add patterns as encountered |
| Char offsets drift after OCR reconciliation | High | Property-based test: every offset back-resolves to ≤2-char window in source |
| STIX bundle valid but OpenCTI silently strips field | Medium | Round-trip equivalence test asserts on whitelist of fields, not byte equality |
| Solo dev burnout, scope creep on Phase 1 | High | Strict acceptance criteria; defer anything not on the list |

## Phases (detail)

| # | File | Title |
|---|---|---|
| 01 | [phase-01-bootstrap-project.md](phase-01-bootstrap-project.md) | Bootstrap project, pyproject, docker stack |
| 02 | [phase-02-core-infrastructure.md](phase-02-core-infrastructure.md) | Core infra: config, logging, security, DB schema |
| 03 | [phase-03-ingestion-layer.md](phase-03-ingestion-layer.md) | Ingestion: parsers, OCR, chunking |
| 04 | [phase-04-intermediate-cti-schema.md](phase-04-intermediate-cti-schema.md) | Pydantic schema for intermediate CTI JSON |
| 05 | [phase-05-regex-ioc-extractor.md](phase-05-regex-ioc-extractor.md) | Regex IOC extractor + defang |
| 06 | [phase-06-stix-builders-validators.md](phase-06-stix-builders-validators.md) | STIX builders + 4-layer validation |
| 07 | [phase-07-api-worker-pipeline.md](phase-07-api-worker-pipeline.md) | FastAPI + RQ worker + orchestrator |
| 08 | [phase-08-opencti-roundtrip-ci.md](phase-08-opencti-roundtrip-ci.md) | OpenCTI compose + round-trip test + CI |

## Definition of Done

All acceptance criteria boxed; one Mandiant-style sample report demoably round-trips into OpenCTI; documentation refreshed (`docs/codebase-summary.md`, `docs/project-roadmap.md` Phase 1 → completed); journal entries written for each phase.

## Unresolved questions

1. Which Mandiant/Talos/CrowdStrike sample report do we lock as the canonical Phase 1 fixture? Pick one with: ≥10 IOCs, multi-section, English, no OCR-required pages.
2. OpenCTI server version pin — track latest stable or pin to 6.4.x for stability?
3. Should Phase 1 ship a tiny CLI (`cti ingest <file>`) or only HTTP API? KISS says only API; CLI is 30-line wrapper anyway.
