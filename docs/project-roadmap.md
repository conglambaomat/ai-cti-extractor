# Project Roadmap

**Project:** AI-Assisted CTI Extractor
**Status:** Phase 0 — Foundation setup
**Last updated:** 2026-05-18
**Source spec:** [`AI-assisted_CTI_extractor.md`](./AI-assisted_CTI_extractor.md)

---

## Phase 0 — Foundation (current)

**Goal:** Repo + docs + Claude Code workflow ready before any Python code is written.

| Deliverable | Status |
|---|---|
| `CLAUDE.md` project contract | done |
| `docs/project-overview-pdr.md` | done |
| `docs/system-architecture.md` | done |
| `docs/code-standards.md` | done |
| `docs/project-roadmap.md` (this file) | done |
| `docs/codebase-summary.md` stub | pending |
| `README.md` rewrite | pending |
| `.env.example` for full stack | done |
| `.gitignore` Python-first | done |
| `.claude/.mcp.json` (context7 + sequential-thinking) | pending |
| Git init + baseline commit | pending |
| Hook smoke test pass | pending |

**Exit gate:** `/ck:plan` triggered from CLI must read project docs (not kit docs) and emit a structurally correct plan.

---

## Phase 1 — Ingestion + IOC + Minimal STIX

**Window:** ~3-4 weeks (target completion: 2026-06-15)
**Goal:** End-to-end pipeline from a single PDF/HTML report to a valid STIX 2.1 bundle with `report` + `indicator` + `relationship` only. No NER yet, no LLM yet, no review UI yet.

### Deliverables

**Infrastructure**
- `pyproject.toml` with locked dependencies (FastAPI, SQLAlchemy 2.0, stix2, taxii2-client, pdfplumber, BeautifulSoup, markdown-it-py, pytest, mypy, ruff, bandit)
- `docker compose` stack: Postgres, Redis, MinIO (Elasticsearch + Chroma deferred to P2)
- Alembic migration baseline
- `app/core/{config,logging,security,telemetry}.py`

**Pipeline (minimal path)**
- `app/ingestion/pdf_parser.py` — pdfplumber, preserves page + char offsets
- `app/ingestion/html_parser.py` — BeautifulSoup with section heuristics
- `app/ingestion/markdown_parser.py`, `txt_parser.py`, `url_fetcher.py`
- `app/ingestion/chunking.py` — semantic chunking with offset preservation
- `app/extractors/regex_ioc.py` — IPv4, IPv6, domain, URL, MD5/SHA1/SHA256/SHA512, email, CVE, ASN. Defang/refang aware.
- `app/extractors/_evidence.py` — shared evidence-span dataclass
- `app/stix/builders.py` — `report`, `indicator`, `relationship` builders only
- `app/stix/validators.py` — Pydantic + `stix2.parse` + minimal semantic checks
- `app/stix/exporters.py` — JSON bundle serialization

**API (slice)**
- `POST /ingest` (file upload + URL)
- `POST /documents/{id}/extract`
- `GET /documents/{id}`
- `GET /extractions/{id}` returns intermediate CTI JSON
- `POST /stix/validate`
- `GET /health`

**Jobs**
- `app/jobs/worker.py` — RQ-based worker (decision: RQ wins for simplicity over Celery)
- `app/jobs/pipelines.py::process_document` orchestrator (idempotent)

**Tests**
- Unit: per extractor, per parser, per builder
- Integration: `tests/fixtures/reports/<sample>.pdf` → end-to-end → valid STIX bundle
- Property: Hypothesis fuzzes IOC patterns + STIX validity invariants
- Coverage target: ≥ 80% on `app/extractors/`, `app/stix/`

### Evaluation gates (Phase 1)

| Metric | Target | Source |
|---|---|---|
| Strict-match P/R/F1 per IOC type | P ≥ 0.98, R ≥ 0.85 | Custom 30-report holdout |
| STIX bundle parse success | ≥ 0.99 | All generated bundles |
| STIX bundle semantic validation | ≥ 0.95 | All generated bundles |
| End-to-end latency (10-page PDF) | ≤ 30s (no OCR, no LLM) | benchmark fixture |
| `mypy --strict` | clean | `app/` |
| Coverage | ≥ 80% | `app/extractors/`, `app/stix/` |

### Phase 1 risks
- Layout-aware PDF parsing on multi-column reports — use `pdfplumber.extract_text(layout=True)` and validate offsets with side-by-side test
- Defang formats (`example[.]com`, `hxxp://...`) vary by vendor — maintain a defang regex table with golden test
- STIX bundle ID stability across re-runs — use deterministic UUID-v5 keyed on (document_id, claim_hash)

---

## Phase 2 — NER + RE + ATT&CK + Review UI

**Window:** ~6-8 weeks (target: 2026-08-15)
**Goal:** Pipeline extracts entities, relations, events. ATT&CK mapping with encoder + ontology rerank (no LLM yet). Analyst review queue functional.

### Deliverables

**Encoders + training**
- Fine-tune `securebert-cti-ner` on AnnoCTR + AZERG entities → `models/securebert-cti-ner/`
- Fine-tune `securebert-cti-re` on AZERG relations → `models/securebert-cti-re/`
- Train event extraction module on AZERG event schema
- Fine-tune `secroberta-attack` candidate generator on WAVE-27K + TRAM → `models/secroberta-attack/`
- Build training pipeline scripts under `scripts/training/`

**Pipeline expansion**
- `app/extractors/ner_model.py`
- `app/extractors/relation_model.py`
- `app/extractors/event_model.py`
- `app/extractors/attack_mapper.py` — stage 1 (encoder candidates) + stage 2 (ATT&CK ontology rerank using MITREtrieval-style voting). Stage 3 (LLM judge) deferred to P3.
- Expand `app/stix/builders.py`: add `malware`, `tool`, `threat-actor`, `intrusion-set`, `campaign`, `vulnerability`, `attack-pattern`, `infrastructure`, `identity`, `observed-data`

**Storage expansion**
- Bring up Elasticsearch in `docker compose`
- `app/db/repositories/*` for entities, relations, events, attack_mappings
- Elasticsearch indexes: `cti_reports`, `cti_objects`, `cti_triage`

**Review UI (minimal)**
- `POST /reviews/{id}/accept|edit|reject`
- Server-rendered HTML triage queue (Jinja2 template, no React yet)
- Diff view: auto-output vs analyst-edited
- Acceptance writes to `feedback_examples` table

**OCR**
- `app/ingestion/ocr.py` (Tesseract) — only for image-only pages
- Offset reconciliation tests

**OpenCTI integration (full)**
- `app/stix/exporters.py::OpenCTIExporter` via GraphQL
- Round-trip test: bundle → OpenCTI dev instance → query back → assert equivalence

**MISP integration**
- `app/stix/exporters.py::MISPExporter` via PyMISP

### Evaluation gates (Phase 2)

| Metric | Target | Source |
|---|---|---|
| NER span F1 | ≥ 0.85 | AnnoCTR holdout |
| Labeled relation F1 | ≥ 0.70 | AZERG holdout |
| Event trigger F1 | ≥ 0.75 | AZERG event subset |
| ATT&CK exact technique F1 | ≥ 0.65 | WAVE-27K holdout |
| ATT&CK parent-relaxed F1 | ≥ 0.78 | WAVE-27K holdout |
| ATT&CK top-5 hit rate | ≥ 0.90 | TRAM holdout |
| Sub-technique exact F1 | ≥ 0.55 | WAVE-27K subset |
| Analyst acceptance rate (review queue) | ≥ 0.55 | Phase 2 manual review |
| End-to-end latency (10-page PDF, no LLM) | ≤ 60s | benchmark fixture |

### Phase 2 risks
- Fine-tuning compute cost — start with parameter-efficient LoRA on existing SecureBERT base
- WAVE-27K only covers 27 techniques — augment with SynthCTI for long tail before reporting full-188 numbers
- Model checkpoint storage — exclude from git (already in `.gitignore`); use HuggingFace Hub or S3-compatible store
- ATT&CK data drift — schedule monthly refresh of `enterprise-attack.json`; lock version per evaluation run

---

## Phase 3 — RAG + LLM Judge + KG + Multilingual

**Window:** ~6-8 weeks (target: 2026-10-15)
**Goal:** LLM-grounded reranking layer; knowledge graph for entity resolution; multilingual ingestion.

### Deliverables

**RAG layer**
- ChromaDB collections operational: `report_chunks`, `attack_techniques`, `stix_docs`, `local_ontology`, `validated_examples`
- `app/rag/{attack_index,stix_index,ontology_index,retriever}.py`
- Typed retrieval — corpus-aware queries, no generic mixing
- Embedding pipeline: BGE base or SecureBERT-derived, batched

**LLM judge**
- `app/extractors/llm_judge.py` — function-calling, evidence-required, abstention-aware
- Prompt templates: `app/extractors/prompts/{attack_rerank,relation_normalize,stix_complete}_v1.md`
- Three judge tasks:
  - Stage-3 ATT&CK reranker (top-k from encoder + retrieved context → final pick or abstain)
  - Cross-sentence relation normalization
  - STIX property completion (only fields with explicit evidence support)
- Provider-agnostic (`LLM_PROVIDER` env): OpenAI / Anthropic / Azure / local Ollama or vLLM
- Caching: `(prompt_hash, retrieved_hash, model_version)` → 24h TTL

**Knowledge graph + entity resolution**
- `canonical_entities` table populated from validated reviews
- `app/jobs/pipelines.py::entity_resolution` step
- Alias matching: exact, normalized (lowercase, defanged), embedding-similarity, ATT&CK group/software cross-ref
- KG queries via Postgres recursive CTE (or Neo4j embedded if pipeline complexity requires — decision in P3 spike)

**Multilingual**
- `app/ingestion/language.py` — langdetect + translation cache
- Translation provider: local Argos by default, Google API optional
- Original + translated both stored; evidence spans always against original

**TAXII export**
- `app/stix/exporters.py::TAXIIExporter`
- Validate against TAXII 2.1 server

**Confidence scoring (full 5-signal composite)**
- `app/extractors/confidence.py` implements:
  ```
  0.25 * extractor_confidence
  + 0.20 * evidence_coverage
  + 0.20 * ensemble_agreement
  + 0.20 * ontology_consistency
  + 0.15 * stix_validation_score
  ```

### Evaluation gates (Phase 3)

| Metric | Target | Source |
|---|---|---|
| LLM unsupported-claim rate | ≤ 0.02 | 50-report manual audit |
| Abstention precision (when judge abstains, was abstention correct?) | ≥ 0.80 | 30-claim audit |
| ATT&CK technique F1 (encoder + LLM rerank vs encoder only) | improvement ≥ +0.05 absolute F1 | WAVE-27K holdout |
| Multi-report ATT&CK aggregation gain | ≥ +0.20 F1 vs single-report (literature ~0.26 expected) | clustered report set |
| Multilingual support (ES, FR, RU, ZH, AR) | NER F1 within −0.10 of EN | per-language eval set |
| Analyst acceptance rate | ≥ 0.70 | Phase 3 review queue |
| End-to-end latency (10-page PDF + LLM) | ≤ 90s p95 | benchmark fixture |

### Phase 3 risks
- LLM cost runaway — enforce token budget per pipeline run, hard cap; cache aggressively
- Prompt injection from report content — wrap LLM context with system-level constraint, never let report text replace instructions
- Translation quality on technical CTI content — manual eval per language; flag low-quality translations for review queue priority
- KG growth + alias collisions — track alias confidence; demote low-confidence aliases; analyst can fork canonical entities

---

## Phase 4 — Downstream SOC artifacts

**Window:** ~4-6 weeks (target: 2026-12-01)
**Goal:** Generate detection-engineering artifacts. Demonstrate operational usefulness.

### Deliverables

**Detection rule generation**
- `app/exporters/sigma_generator.py` — Sigma rules from extracted TTPs
- `app/exporters/splunk_generator.py` — SPL queries
- `app/exporters/elastic_generator.py` — Elastic detection rules
- Compilation/validation of generated rules
- Test: `≥ 0.90` of generated Sigma rules pass `sigma-cli check`; `≥ 0.99` of Splunk SPL parses

**Custom gold benchmark release**
- 200 reports, double-annotated 30%
- Krippendorff α reported per layer (entities, relations, ATT&CK techniques)
- Eval harness: `scripts/eval/run_full_benchmark.py`
- Layered metrics report (no single-number summary)
- Public release on HuggingFace Datasets (license review pending)

**SOC usefulness eval**
- Analyst acceptance study (target: 5 analysts, 50 reports)
- Downstream rule utility: how many generated rules survived analyst review?
- Latency + cost dashboard

**Reasoning eval against benchmarks**
- AttackSeqBench score
- ExCyTIn-Bench score
- CTI-REALM score
- Direct comparison with state-of-art numbers

**Hardening**
- Audit log hash chain integration with optional Sigstore
- Bandit + pip-audit clean
- Penetration test of API surface (basic OWASP coverage)

**Operations**
- Grafana dashboards in `docker/grafana/`
- Alerting rules: queue depth, validation failure rate, abstention spike

### Evaluation gates (Phase 4)

| Metric | Target | Source |
|---|---|---|
| Sigma rule compilation success | ≥ 0.90 | sigma-cli check |
| Splunk SPL parse success | ≥ 0.99 | splunk parse |
| Custom gold benchmark Krippendorff α | ≥ 0.70 (entities), ≥ 0.65 (ATT&CK) | annotator agreement |
| Analyst acceptance rate (final) | ≥ 0.70 | study |
| Vs LLM-only baseline: unsupported-claim reduction | ≥ 0.15 | head-to-head |
| AttackSeqBench score | beat reported baselines | published benchmark |
| ExCyTIn-Bench reward | exceed median LLM-agent | published benchmark |
| CTI-REALM detection-rule generation | ≥ published median | published benchmark |

### Phase 4 risks
- Analyst time scarcity for acceptance study — start recruiting Phase 3
- Custom gold release license — vendor-disjoint clause; review legal at start of P4
- Benchmark drift (new versions release) — pin evaluation versions, document in eval report

---

## Cross-phase non-goals (will not be done)

- Real-time streaming ingestion (batch-only)
- Mobile / iOS / Android client
- Federated learning across orgs
- Active threat hunting (system extracts; analysts/SOC act)
- Auto-publish to OpenCTI without human review (Phase 1-3); even Phase 4 reserves auto-publish for "high-confidence + ontology-validated + analyst-pre-approved policy" path

## Dataset roadmap

| Dataset | Phase used | Role |
|---|---|---|
| AnnoCTR | P2 | NER + ATT&CK concept training |
| AZERG | P2 | STIX entity + relation training |
| WAVE-27K | P2, P3 | ATT&CK mapping eval |
| TRAM | P2 | ATT&CK baseline reproduction |
| CTI-to-MITRE | P2 | baseline reproduction |
| CTI-HAL | P2, P3 | annotation methodology reference |
| SynthCTI | P2 | augmentation for rare techniques |
| AttackSeqBench | P3, P4 | sequence understanding eval |
| ExCyTIn-Bench | P4 | downstream investigation eval |
| CTI-REALM | P4 | detection-rule generation eval |
| Custom gold (200 reports) | P4 | end-to-end benchmark release |

## External dependency roadmap

| Dependency | Phase introduced | Notes |
|---|---|---|
| pdfplumber, BeautifulSoup, markdown-it-py | P1 | parsers |
| stix2, taxii2-client | P1 | OASIS official libs |
| pytest, mypy, ruff, bandit, hypothesis | P1 | quality |
| SQLAlchemy 2.0 (async), Alembic | P1 | DB |
| Tesseract | P2 | OCR |
| Transformers (HF), accelerate, peft | P2 | encoder fine-tuning |
| Elasticsearch client | P2 | lexical search |
| ChromaDB client | P3 | vector retrieval |
| LLM SDKs (provider-agnostic) | P3 | judge layer |
| Argos / translation provider | P3 | multilingual |
| sigma-cli | P4 | detection-rule validation |

## Decision log placeholders

These need decisions early in their phase. Capture in journal entries when made.

- **P1**: RQ vs Celery vs Arq for job queue
- **P1**: `uv` vs `poetry` for lock file
- **P2**: Argos local vs Google translate API
- **P2**: pgvector vs ChromaDB vs Qdrant for vector store (decision feeds P3)
- **P3**: Default LLM provider (OpenAI / Anthropic / local) per cost-quality benchmark
- **P3**: Neo4j embedded vs Postgres recursive CTE for KG queries
- **P4**: Custom gold license — CC BY-SA vs Apache 2.0

---

## Unresolved questions

1. Thesis defense timeline — drives whether Phase 4 must complete by a fixed academic deadline.
2. Compute budget for Phase 2 fine-tuning — local GPU available, or cloud?
3. Annotator availability for custom gold — solo, paired, or crowdsourced via security MSc students?
4. Whether to publish custom gold dataset publicly (license risk) or keep internal (smaller impact).
5. Coordination with OpenCTI / MISP communities for upstream contributions of any improvements made during integration.
