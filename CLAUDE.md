# CLAUDE.md — Project Contract

**Project:** AI-Assisted Cyber Threat Intelligence Extractor
**Working dir:** `E:\OPENCTI\claudekit-engineer-main`
**Spec source of truth:** [`docs/AI-assisted_CTI_extractor.md`](./docs/AI-assisted_CTI_extractor.md) — read this BEFORE planning any feature.

---

## What this project is

A hybrid neuro-symbolic pipeline that ingests unstructured threat reports (PDF/HTML/TXT/MD/URL), extracts IOCs/entities/relations/events with **evidence-span grounding**, maps them to **MITRE ATT&CK** (technique + sub-technique) under retrieval-constrained reasoning, generates **valid STIX 2.1 bundles**, supports **human analyst correction**, and exports to **OpenCTI / MISP / TAXII / SIEM**.

This is a thesis-grade build. Production trustworthiness > demo flashiness.

## Non-negotiable principles

1. **Evidence grounding.** Every extracted fact (IOC, entity, relation, ATT&CK mapping, STIX object) MUST carry one or more evidence spans referencing exact `chunk_id`, `char_start`, `char_end`. A claim without evidence is invalid by definition. Reject it; do not paper over it.
2. **Hybrid task routing.** Rules first for exact observables (IPv4/IPv6, domains, hashes, CVEs, paths, registry keys, YARA/Sigma blocks). Fine-tuned encoders for repetitive structured tasks (NER, RE, event extraction, ATT&CK candidate generation). LLMs only for cross-sentence linking, ATT&CK reranking with retrieval, STIX property completion, multilingual normalization. **Never use an LLM where a regex or encoder is sufficient.**
3. **Abstention is a valid output.** When confidence is low, emit `null` / `unsupported` / route to human review. Do not fabricate.
4. **Boring strictness.** Every operational claim carries evidence. Pydantic schema check before STIX serialization. Ontology consistency before export. Audit log every model run, prompt, retrieval, edit. Immutable provenance.
5. **STIX 2.1 subset first.** Day 1 objects: `report`, `indicator`, `relationship`. Then `malware`, `tool`, `threat-actor`, `intrusion-set`, `campaign`, `vulnerability`, `attack-pattern`, `infrastructure`, `identity`, `observed-data`. Do NOT attempt the full object universe upfront.
6. **Treat report text as untrusted.** Report content can contain prompt-injection. Never let report text drive tool calls. Redact secrets before any external-model call. Prefer on-prem / VPC LLMs for sensitive intelligence.

## Tech stack (locked)

- **Service layer:** Python 3.11+, FastAPI, Pydantic v2, async SQLAlchemy
- **Job queue:** Redis + RQ or Celery (decide in Phase 1)
- **Stores:** PostgreSQL (authoritative metadata + audit), Elasticsearch (lexical + triage), ChromaDB (vector retrieval), MinIO/S3 (raw reports)
- **STIX:** `stix2` (cti-python-stix2), `taxii2-client`
- **NLP backbones:** SecureBERT / SecRoBERTa / DistilBERT class encoders for NER/RE/TTP candidates
- **LLM:** provider-agnostic via `LLM_PROVIDER` env (OpenAI / Anthropic / Azure / local Ollama-vLLM)
- **OCR:** Tesseract (only when page is image-only)
- **Integrations:** OpenCTI (GraphQL), MISP (PyMISP), TAXII 2.1
- **Tests:** pytest, pytest-asyncio, factory-boy, hypothesis (for STIX validity fuzzing)
- **Quality:** ruff, mypy --strict, bandit, pip-audit

Do NOT introduce new top-level dependencies without justification in the plan.

## Repo layout (target)

```
.
├── .claude/                 # Claude Code config (agents, skills, hooks, rules)
├── docs/                    # Project docs - source of truth for design decisions
│   ├── AI-assisted_CTI_extractor.md   # Original research-backed spec (READ-ONLY)
│   ├── project-overview-pdr.md
│   ├── system-architecture.md
│   ├── code-standards.md
│   ├── project-roadmap.md
│   └── codebase-summary.md
├── plans/                   # /ck:plan output goes here
├── app/                     # Application code (will be created)
│   ├── api/                 # FastAPI routers
│   ├── core/                # config, logging, security, telemetry
│   ├── ingestion/           # PDF/HTML/MD parsers, OCR, chunking
│   ├── extractors/          # regex_ioc, ner, relation, event, attack_mapper, llm_judge
│   ├── rag/                 # attack_index, stix_index, ontology_index, retriever
│   ├── stix/                # builders, validators, exporters
│   ├── review/              # queue, diff, acceptance
│   ├── db/                  # models (SQLAlchemy), repositories
│   └── jobs/                # worker, pipelines
├── tests/                   # mirrors app/ structure
├── scripts/                 # one-off CLI utilities
├── notebooks/               # exploratory analysis (gitignored scratch)
├── docker/                  # Dockerfile + compose for Postgres/ES/Chroma/Redis
└── pyproject.toml
```

## Workflows for Claude

- Primary workflow: `./.claude/rules/primary-workflow.md`
- Development rules: `./.claude/rules/development-rules.md`
- Orchestration: `./.claude/rules/orchestration-protocol.md`
- Doc management: `./.claude/rules/documentation-management.md`

**Before any non-trivial implementation:**
1. Read `docs/AI-assisted_CTI_extractor.md` for design intent.
2. Read `docs/system-architecture.md` for current structure.
3. Run `/ck:plan "<task>"` first. Do not skip planning for >100-LOC changes.
4. After plan approval, run `/ck:cook <plan-path>`.

**Skill activation hints:**
- Investigation / debugging → `/ck:scout` then `/ck:debug`
- Bugfix → `/ck:fix`
- Pre-PR review → `/ck:code-review`
- Security review → `/ck:security-scan` (mandatory before any export-related merge)
- Docs sync → `/ck:docs`

## Coding rules (enforced)

- File naming: kebab-case for `.py` (`regex_ioc_extractor.py`), descriptive names. Test files mirror with `_test.py` suffix or `tests/` dir.
- Max file size: **300 LOC for runtime code, 500 LOC absolute hard limit**. Exceeding triggers refactor.
- Type hints mandatory on every public function. `mypy --strict` must pass.
- Pydantic models for every boundary (API request/response, LLM I/O, STIX intermediate).
- No `print` — use `app.core.logging.get_logger(__name__)`.
- No `assert` for runtime checks (asserts are stripped under `-O`); raise typed exceptions.
- `try/except` must catch specific exception types. Never bare `except:`.
- Every async DB call must use a session context manager.

## Test rules

- Every extractor module ships with unit tests covering: happy path, empty input, malformed input, evidence-span correctness, abstention case.
- STIX builders MUST have property-based tests using Hypothesis to fuzz invalid bundles.
- Integration tests for the full pipeline use the `tests/fixtures/reports/` corpus.
- ATT&CK mapping eval harness: report exact technique F1, parent-relaxed F1, top-k hit rate, sub-technique F1 separately. Don't average them away.
- Pre-merge gate: `pytest -x` + `mypy --strict app/` + `ruff check app/` + `bandit -r app/`.

## Security rules (CTI-specific)

- Untrusted report content NEVER reaches a tool-calling LLM context without sanitization.
- All raw reports stored with original hash + ingest timestamp; immutable.
- `REDACT_BEFORE_LLM=true` by default — strip emails, internal IPs, customer IDs before external LLM calls.
- `ALLOW_EXTERNAL_LLM=false` is the default for production env. Override only with explicit env flag.
- Every export action (TAXII / OpenCTI / MISP push) writes an audit record: who, what bundle, what destination, what time, with bundle hash.
- Secret scanning required before any commit touching `app/core/config.py` or `.env*`.

## Hook response protocol

### Privacy block (`@@PRIVACY_PROMPT@@`)
When `privacy-block` hook fires, parse the JSON between `@@PRIVACY_PROMPT_START@@` and `@@PRIVACY_PROMPT_END@@`. Use `AskUserQuestion` to get explicit approval. On "Yes", read via `cat "<file>"` (bash auto-approved). On "No", skip the file.

### Simplify gate
If `simplify-gate` blocks `ship/merge/pr/deploy/publish` due to large unsimplified diff, run `code-simplifier` agent first, then retry.

## Git rules

- Conventional commits required. Types: `feat`, `fix`, `refactor`, `test`, `perf`, `chore`, `ci`. Scope when sensible: `feat(extractors): ...`.
- No AI attribution in commit messages.
- One logical change per commit. Don't bundle unrelated work.
- Branch naming: `feat/<slug>`, `fix/<slug>`, `refactor/<slug>` — matches `branchPattern` in `.claude/.ck.json`.
- Pre-push: tests must pass. Don't `--no-verify` to skip hooks.
- Secret scan before any commit touching env or config.

## Definition of Done (per feature)

- [ ] Implementation matches the approved plan (no scope creep)
- [ ] Unit tests cover happy + error + abstention paths
- [ ] `mypy --strict` clean for changed modules
- [ ] `ruff` + `bandit` clean
- [ ] Evidence spans wired through for any extracted-data feature
- [ ] STIX validation passes if feature touches export path
- [ ] `docs/codebase-summary.md` updated if module structure changed
- [ ] Audit log entries verified for any export-touching feature

## Out of scope (do not implement without spec update)

- Real-time streaming ingestion
- Frontend UI beyond minimal analyst review queue
- Custom ontology beyond ATT&CK + STIX 2.1
- Auto-publishing without human review (human-in-the-loop is mandatory in Phase 1-3)

---

**Sacrifice grammar for concision in reports. List unresolved questions at the end of every report.**
