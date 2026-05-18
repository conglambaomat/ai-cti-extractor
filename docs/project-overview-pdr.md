# Project Overview & Product Development Requirements (PDR)

**Project:** AI-Assisted Cyber Threat Intelligence Extractor for STIX, ATT&CK, and SOC Operations
**Status:** Pre-implementation (Phase 0)
**Last updated:** 2026-05-18
**Source spec:** [`AI-assisted_CTI_extractor.md`](./AI-assisted_CTI_extractor.md) — research-backed design rationale.

---

## 1. Vision

Convert noisy unstructured threat reports (PDF, HTML, blog posts, screenshots, multilingual prose) into **grounded, standardized, queryable cyber threat intelligence** that security teams actually use. Produce STIX 2.1 bundles, MITRE ATT&CK mappings, and SOC-ready detection artifacts — every claim traceable back to exact text spans in the source report.

## 2. Problem statement

Current CTI workflows fail at three points:

1. **Translation gap.** Threat reports are prose, but downstream tools (SIEM, SOAR, OpenCTI, MISP) need structured data. Manual translation is slow and inconsistent.
2. **Behavioral abstraction gap.** IoC extraction is solved; mapping behavior to ATT&CK at technique + sub-technique level remains noisy. Best supervised baselines hit ~72% F1 on 188 techniques (CTI-to-MITRE); multi-report aggregation pushes this to 78.6% F1.
3. **Hallucination + faithfulness gap.** LLM-only extractors produce plausible-looking output without evidence anchoring, making review expensive and trust low.

This project addresses all three with a hybrid neuro-symbolic pipeline that grounds every output in exact evidence spans.

## 3. Target users

| Persona | Primary need |
|---|---|
| **CTI analyst** | Convert reports into STIX bundles + ATT&CK mappings, review/correct outputs, push to OpenCTI/MISP |
| **Detection engineer** | Get sigma/splunk-ready candidate rules from extracted TTPs |
| **SOC L2/L3** | Investigate incidents using extracted graph relationships and prior-report knowledge |
| **Researcher / thesis evaluator** | Reproduce evaluation, inspect evidence chains, audit decisions |

## 4. Scope

### In scope (this project)
- Ingestion: PDF, HTML, TXT, Markdown, URL fetch, OCR fallback
- Layout-aware parsing + chunking with section/page/offset tracking
- Deterministic IOC extraction (IPv4/IPv6, domain, URL, hash, email, CVE, path, registry, ASN)
- Domain NER + relation + event extraction (fine-tuned encoders)
- ATT&CK technique + sub-technique mapping with retrieval reranking
- STIX 2.1 bundle generation (subset listed below)
- Knowledge graph entity resolution (alias/canonicalization)
- Confidence scoring (5-signal composite)
- Human review queue with diff/edit/accept
- Export to OpenCTI, MISP, TAXII 2.1
- Evaluation harness across public benchmarks + custom gold set

### STIX 2.1 object subset (Phase 1-3)
Phase 1 minimum: `report`, `indicator`, `relationship`.
Phase 2-3 expansion: `malware`, `tool`, `threat-actor`, `intrusion-set`, `campaign`, `vulnerability`, `attack-pattern`, `infrastructure`, `identity`, `observed-data`.

### Out of scope (this project)
- Real-time streaming ingestion (batch only)
- Frontend beyond minimal analyst review UI
- Custom ontology beyond ATT&CK + STIX 2.1
- Auto-publish without human review
- Active threat hunting / response actions

## 5. Functional requirements

| ID | Requirement | Acceptance |
|---|---|---|
| FR-1 | Ingest PDF/HTML/TXT/MD/URL | Parser preserves page, section, char offsets |
| FR-2 | OCR image-only pages | Tesseract fallback when text layer absent |
| FR-3 | Language detect + translation cache | Non-English reports normalized; original retained |
| FR-4 | Deterministic IOC extraction | Per-type strict-match precision ≥ 0.98 |
| FR-5 | NER on CTI entities | Span-level F1 ≥ 0.85 on AnnoCTR holdout |
| FR-6 | Relation + event extraction | Labeled relation F1 ≥ 0.70 on AZERG holdout |
| FR-7 | ATT&CK mapping | Exact technique F1 ≥ 0.65; parent-relaxed F1 ≥ 0.78 |
| FR-8 | Evidence spans on every output | 100% — claims without spans rejected |
| FR-9 | STIX 2.1 bundle generation | Parse + semantic validation pass rate ≥ 0.99 |
| FR-10 | Confidence score | 5-signal composite per `intermediate_cti_json` claim |
| FR-11 | Human review queue | Diff vs auto-output, edit, accept/reject, reason captured |
| FR-12 | OpenCTI / MISP / TAXII export | Round-trip success ≥ 0.95 on validated bundles |
| FR-13 | Audit trail | Immutable record of every extraction, edit, export |
| FR-14 | Search + retrieval | Lexical (Elasticsearch) + vector (ChromaDB) + KG queries |
| FR-15 | Re-extract on updated model | Versioned model runs, idempotent re-run with diff |

## 6. Non-functional requirements

| ID | Requirement | Target |
|---|---|---|
| NFR-1 | Latency: single report (10-page PDF) | ≤ 90 seconds end-to-end |
| NFR-2 | Throughput | ≥ 100 reports/hour with 2 workers |
| NFR-3 | Faithfulness | Unsupported-claim rate ≤ 2% |
| NFR-4 | Hallucination control | Abstention preferred over confabulation |
| NFR-5 | Schema strictness | STIX bundle parse failure ≤ 0.5% |
| NFR-6 | Privacy | External LLM disabled by default; redaction ON |
| NFR-7 | Auditability | Every claim traces to evidence + model version + prompt version |
| NFR-8 | Test coverage | ≥ 80% on `app/extractors/`, `app/stix/`, `app/rag/` |
| NFR-9 | Type safety | `mypy --strict` clean |
| NFR-10 | Security | Bandit + pip-audit clean; OWASP top 10 reviewed |
| NFR-11 | Reproducibility | Pinned dependencies, deterministic seeds for evaluation |
| NFR-12 | Operational | Docker compose for full local stack |

## 7. Architecture pillars

See [`system-architecture.md`](./system-architecture.md) for full diagram.

1. **Hybrid neuro-symbolic pipeline.** Rules → encoders → LLM judge, in that order.
2. **Intermediate CTI JSON schema** as the canonical internal representation. STIX 2.1 is built from it, not from raw text.
3. **Typed RAG layer** with 4 corpora: ATT&CK, STIX schema, local ontology, validated examples.
4. **Knowledge graph** as normalized memory (aliases, canonical entities, prior-report cross-refs).
5. **Human review** before any export.
6. **Layered validation:** Pydantic → STIX library parse → semantic checks → ontology consistency.

## 8. Data sources

### Training / fine-tuning
- **AZERG** (141 reports, 4011 STIX entities, 2075 relationships) — STIX entity/relation training
- **AnnoCTR** (400 commercial reports, full-document annotation) — entity + ATT&CK concept detection
- **WAVE-27K** (27 techniques, 22.5K single + 5.3K multi-technique samples) — ATT&CK mapping
- **CTI-to-MITRE** — baseline reproduction
- **TRAM** — sentence-level ATT&CK mapping; up to 50 common techniques out-of-the-box
- **CTI-HAL** — high-quality manually-annotated, inter-annotator agreement reported
- **SynthCTI** — synthetic augmentation for rare techniques

### Evaluation
- **AttackSeqBench** — sequence understanding
- **ExCyTIn-Bench** — graph-anchored explainable ground truth
- **CTI-REALM** — agentic detection-rule generation eval
- **Custom gold set** — 150-250 reports, double-annotated 20-30%, Krippendorff's alpha reported

### Reference / ontology
- MITRE ATT&CK STIX/TAXII bundle
- OASIS STIX 2.1 schema
- OpenCTI graph schema
- MISP object templates

## 9. Success criteria

### Technical
- All FR/NFR targets met on holdout test set
- End-to-end pipeline runs reproducibly via `docker compose up` + sample report
- STIX bundles round-trip into OpenCTI dev instance without errors
- Evaluation harness produces layered metrics report (no single-number summary)

### Research
- Custom gold benchmark released with documented annotation methodology
- Comparison vs LLM-only baseline shows ≥ 15% reduction in unsupported claims
- Multi-report aggregation experiment reproduces literature finding (≥ 20% ATT&CK improvement)

### Operational
- Analyst acceptance rate ≥ 0.70 on Phase 3 review queue
- Detection rule generation: ≥ 0.90 compilation success on generated Sigma/Splunk artifacts

## 10. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| ATT&CK mapping below 0.65 F1 | Medium | High | Ensemble + retrieval rerank + SynthCTI augmentation |
| LLM hallucination on STIX completion | High | Critical | Evidence-required schema; abstention; strict validation |
| Annotation quality on custom gold | High | High | Double annotation + Krippendorff α reporting + iterate |
| Dataset license restrictions on commercial reports | Medium | Medium | Vendor-disjoint splits; document provenance per report |
| OpenCTI/MISP API drift | Medium | Low | Pinned client versions; integration test suite |
| Compute cost for fine-tuning encoders | Medium | Medium | Distill / use existing SecureBERT checkpoints first |
| Multilingual quality | High | Medium | Translation cache; report orig + translated; manual eval per language |
| Evidence-span misalignment after OCR | Medium | High | Layout-aware OCR; offset reconciliation tests |

## 11. Out-of-scope but adjacent (potential future work)

- Real-time streaming pipeline (Kafka-based ingest)
- Multi-tenant SaaS deployment
- Custom analyst dashboard with graph visualization
- Federated learning across orgs
- Active threat hunting integration

## 12. Compliance & ethics

- NIST SP 800-150 alignment for trust, handling, sharing constraints
- ENISA CTL methodology for STIX 2.1 + ATT&CK structuring
- Document attribution preserved; no stripping of vendor/author metadata
- Dataset provenance auditable for all training/evaluation corpora

---

## Unresolved questions

1. Self-host vs managed Elasticsearch? (Cost vs ops complexity)
2. Which LLM for grounded judge: GPT-4o-mini, Claude Sonnet, or local Qwen2.5-72B? Need benchmark on AZERG holdout.
3. Custom gold set: 150 vs 250 reports — depends on annotator availability.
4. ChromaDB vs Qdrant vs pgvector for vector store — pgvector reduces ops surface.
5. RQ vs Celery vs Arq for job queue — decide in Phase 1 spike.
6. Whether to ship a minimal React review UI or rely on OpenCTI's built-in review.
