# AI-Assisted CTI Extractor

> Convert unstructured threat reports (PDF, HTML, blog posts, multilingual prose) into grounded, standardized **STIX 2.1** intelligence with **MITRE ATT&CK** mappings, ready to push into **OpenCTI**, **MISP**, **TAXII**, and SIEM detection pipelines. Every claim traces back to exact evidence spans in the source report.

**Status:** Phase 0 — Foundation setup. No application code yet. See [`docs/project-roadmap.md`](./docs/project-roadmap.md).

---

## Why this exists

Security teams need machine-readable intelligence, but threat reports come as prose. Manual translation is slow and inconsistent. LLM-only extractors hallucinate. Pure rule systems miss semantics.

This project takes a **hybrid neuro-symbolic** approach:
- **Rules first** for exact observables (IPs, domains, hashes, CVEs).
- **Fine-tuned encoders** for repetitive structured tasks (NER, relations, ATT&CK candidates).
- **LLMs only** for cross-sentence reasoning, with retrieval-grounded constraints.
- **Evidence spans on every claim** — abstain over fabricate.
- **Human review** before any export.

Design rationale comes from a research-backed spec at [`docs/AI-assisted_CTI_extractor.md`](./docs/AI-assisted_CTI_extractor.md), distilled from STIXnet, AZERG, AttacKG, MITREtrieval, CTINexus, IntelEX, and current CTI benchmarks (AnnoCTR, WAVE-27K, AttackSeqBench, ExCyTIn-Bench, CTI-REALM).

## What it does (target capability)

```
Threat report (PDF / HTML / TXT / MD / URL)
        |
        v
Layout-aware parsing + chunking + OCR fallback
        |
        v
Deterministic IOC extraction
Domain NER + relation + event extraction
ATT&CK candidate generation (encoder)
        |
        v
RAG over ATT&CK + STIX schema + local ontology + validated examples
LLM grounded reranker / judge (evidence-required, abstention-aware)
        |
        v
Knowledge graph entity resolution + confidence scoring
        |
        v
STIX 2.1 bundle (validated, layered checks)
        |
        v
Human review queue
        |
        v
Export: OpenCTI / MISP / TAXII 2.1 / Sigma / Splunk
```

## Documentation

| Document | Purpose |
|---|---|
| [`CLAUDE.md`](./CLAUDE.md) | Project contract — read first, especially for AI-assisted work |
| [`docs/AI-assisted_CTI_extractor.md`](./docs/AI-assisted_CTI_extractor.md) | Original research-backed spec with full literature review |
| [`docs/project-overview-pdr.md`](./docs/project-overview-pdr.md) | PDR — vision, FR/NFR, datasets, success criteria |
| [`docs/system-architecture.md`](./docs/system-architecture.md) | Component map, data flow, DB schema, API surface |
| [`docs/code-standards.md`](./docs/code-standards.md) | Python rules, evidence grounding, security, test policy |
| [`docs/project-roadmap.md`](./docs/project-roadmap.md) | 4-phase plan, evaluation gates, decision log |
| [`docs/codebase-summary.md`](./docs/codebase-summary.md) | Current repo state — kept in sync by `docs-manager` agent |

## Tech stack (planned)

- **Service:** Python 3.11+, FastAPI, Pydantic v2, async SQLAlchemy 2.0
- **Stores:** PostgreSQL (authoritative + audit), Elasticsearch (lexical), ChromaDB (vector), MinIO/S3 (raw reports)
- **Job queue:** Redis + RQ
- **STIX/TAXII:** `cti-python-stix2`, `taxii2-client`
- **NLP:** SecureBERT / SecRoBERTa class encoders for NER/RE/TTP candidates
- **LLM:** provider-agnostic (OpenAI / Anthropic / Azure / local Ollama or vLLM)
- **Quality:** pytest, mypy `--strict`, ruff, bandit, pip-audit, hypothesis

## Phases

| Phase | Window (target) | Headline deliverable |
|---|---|---|
| **0 — Foundation** | now | Repo + docs + Claude Code workflow |
| **1 — Ingestion + IOC + minimal STIX** | ~3-4 weeks | End-to-end pipeline: PDF → valid STIX bundle (`report`, `indicator`, `relationship`) |
| **2 — NER + RE + ATT&CK + review UI** | ~6-8 weeks | Encoder-based extraction; ATT&CK mapping; analyst review queue; OpenCTI/MISP export |
| **3 — RAG + LLM judge + KG + multilingual** | ~6-8 weeks | LLM-grounded reranking; knowledge graph; multilingual ingestion; TAXII export |
| **4 — Downstream SOC artifacts** | ~4-6 weeks | Sigma/Splunk rule generation; custom gold benchmark release; analyst acceptance study |

## Quick start

> Application code lands in Phase 1. Until then, this section is a placeholder for the eventual setup flow.

### Prerequisites

- Python 3.11+
- Docker + Docker Compose
- Git
- (Optional) Claude Code CLI for AI-assisted development workflow

### When Phase 1 ships

```bash
# 1. Clone + enter
git clone <this-repo> && cd ai-cti-extractor

# 2. Configure environment
cp .env.example .env
# Edit .env — set DATABASE_URL, LLM_PROVIDER, OPENCTI_TOKEN, etc.

# 3. Bring up local stack
docker compose up -d

# 4. Initialize database
make migrate

# 5. Run
make dev          # FastAPI dev server
make worker       # Background extraction worker

# 6. Smoke test
make test
```

## AI-assisted development workflow

This repository ships with the **ClaudeKit Engineer** workflow assets in `.claude/`. With Claude Code CLI installed:

```bash
claude

# Inside Claude session:
/ck:plan "Phase 1: ingestion + regex IOC + STIX subset"
# planner agent reads docs/, spawns researchers, writes plans/<id>/plan.md

/ck:cook plans/<id>/plan.md
# fullstack-developer executes phases; tester runs tests; code-reviewer validates

/ck:security-scan
# mandatory before any export-related merge
```

Read [`CLAUDE.md`](./CLAUDE.md) for the full workflow and project rules. The kit provides 14 specialized agents and 92 skills — most are irrelevant to CTI work but harmless when not invoked.

## Project structure

```
.
├── .claude/                  # Claude Code workflow (agents, skills, hooks, rules)
├── docs/                     # Project documentation (source of truth)
│   ├── AI-assisted_CTI_extractor.md
│   ├── project-overview-pdr.md
│   ├── system-architecture.md
│   ├── code-standards.md
│   ├── project-roadmap.md
│   └── codebase-summary.md
├── plans/                    # /ck:plan output (per-feature plans + reports)
├── app/                      # Application code (Phase 1+, not yet present)
├── tests/                    # Test suites (Phase 1+)
├── docker/                   # Compose stack + Dockerfiles (Phase 1+)
├── CLAUDE.md                 # Project contract for AI-assisted work
└── README.md                 # This file
```

## Standards & references

- [OASIS STIX 2.1](https://docs.oasis-open.org/cti/stix/v2.1/)
- [OASIS TAXII 2.1](https://docs.oasis-open.org/cti/taxii/v2.1/)
- [MITRE ATT&CK](https://attack.mitre.org/)
- [NIST SP 800-150](https://csrc.nist.gov/pubs/sp/800/150/final) — Guide to Cyber Threat Information Sharing
- [OpenCTI Docs](https://docs.opencti.io/)
- [MISP Project](https://www.misp-project.org/)

## License

MIT — see [LICENSE](./LICENSE).

## Acknowledgements

- Workflow scaffold by [**ClaudeKit Engineer**](https://github.com/claudekit/claudekit-engineer) (MIT) — agent definitions, hooks, and skills under `.claude/`.
- Research foundation distilled in [`docs/AI-assisted_CTI_extractor.md`](./docs/AI-assisted_CTI_extractor.md) cites STIXnet, AZERG, AttacKG, MITREtrieval, CTINexus, IntelEX, LLMCloudHunter, AnnoCTR, WAVE-27K, AttackSeqBench, ExCyTIn-Bench, and CTI-REALM among others.
