# Codebase Summary

**Project:** AI-Assisted CTI Extractor
**Last updated:** 2026-05-18
**Phase:** 0 — Foundation setup (no application code yet)

---

## Status

The application code under `app/` does not exist yet. This file currently summarizes only the foundation layer (docs + Claude Code workflow).

`docs-manager` agent will rebuild this file once Phase 1 ships its first modules. Until then, treat this as a stub — do **not** assume any Python module exists in `app/`.

## Repository layout (current)

```
.
├── .claude/                              # Claude Code workflow assets (do not modify lightly)
│   ├── agents/        (14)               # planner, fullstack-developer, code-reviewer, ...
│   ├── skills/        (92)               # cook, plan, debug, fix, security-scan, ...
│   ├── hooks/         (16 .cjs)          # session-init, scout-block, privacy-block, ...
│   ├── rules/         (7)                # primary-workflow, development-rules, ...
│   ├── schemas/                          # JSON schemas (ck-config, skill)
│   ├── output-styles/
│   ├── settings.json                     # hook config + statusline
│   ├── settings.local.json               # user permissions overrides
│   ├── .ck.json                          # ClaudeKit config (codingLevel, plan naming)
│   ├── .ckignore                         # block heavy dirs
│   ├── .mcp.json.example                 # MCP servers template (copy to .mcp.json)
│   ├── .env.example                      # ClaudeKit notification env template
│   └── statusline.cjs
├── docs/                                 # Project documentation (source of truth)
│   ├── AI-assisted_CTI_extractor.md      # Original research-backed spec (READ-ONLY)
│   ├── project-overview-pdr.md           # PDR — vision, FR/NFR, scope, success criteria
│   ├── system-architecture.md            # Hybrid pipeline, components, DB schema, API surface
│   ├── code-standards.md                 # Python/FastAPI rules, evidence grounding, security
│   ├── project-roadmap.md                # 4-phase plan, eval gates, risks, decision log
│   └── codebase-summary.md               # This file
├── plans/                                # /ck:plan output goes here (currently empty)
├── CLAUDE.md                             # Project contract for every Claude session
├── README.md                             # Human-facing intro + quick start
├── LICENSE                               # MIT
├── package.json                          # Minimal Node config (Claude Code hooks runtime only)
├── .env.example                          # Project env template (DB, LLM, OpenCTI, MISP, TAXII)
└── .gitignore                            # Python-first; excludes .env, .claude/.mcp.json, models/, data/
```

## What lives where

### Source of truth for design intent
1. **`docs/AI-assisted_CTI_extractor.md`** — original research-backed spec. Treat as immutable reference.
2. **`docs/project-overview-pdr.md`** — distilled PDR with FR/NFR + success criteria.
3. **`docs/system-architecture.md`** — component map, data model, API surface, DB schema.

### Source of truth for execution rules
1. **`CLAUDE.md`** — project contract; every session reads this.
2. **`docs/code-standards.md`** — code conventions, security rules, test policy.
3. **`docs/project-roadmap.md`** — phase-aligned scope, eval gates.

### Workflow assets (rarely modified)
- `.claude/rules/primary-workflow.md` — plan → cook → test → review → docs cycle
- `.claude/rules/development-rules.md` — YAGNI/KISS/DRY, file-size limits, naming
- `.claude/rules/orchestration-protocol.md` — sequential vs parallel agent coordination
- `.claude/rules/skill-domain-routing.md` — which skill to use for which domain
- `.claude/rules/skill-workflow-routing.md` — typical skill chains

## Tech stack (planned, not installed yet)

See `docs/system-architecture.md` § 1-2 for full component map.

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Service | FastAPI + Pydantic v2 + SQLAlchemy 2.0 async |
| Job queue | Redis + RQ (decision pending; see roadmap P1 spike) |
| Stores | Postgres (auth metadata + audit), Elasticsearch (lexical), ChromaDB (vector), MinIO/S3 (raw) |
| STIX | `stix2`, `taxii2-client` |
| NLP | SecureBERT / SecRoBERTa class encoders |
| LLM | provider-agnostic (OpenAI / Anthropic / Azure / local Ollama-vLLM) |
| OCR | Tesseract |
| Quality | pytest, mypy --strict, ruff, bandit, pip-audit, hypothesis |

## Claude Code workflow surface

**Available agents** (`.claude/agents/*.md`):
planner, researcher, fullstack-developer, code-reviewer, tester, debugger, docs-manager, git-manager, code-simplifier, brainstormer, journal-writer, ui-ux-designer, project-manager, mcp-manager.

**Key skills** (`.claude/skills/*/SKILL.md`):
- Workflow: `cook`, `plan`, `debug`, `fix`, `code-review`, `test`, `ship`, `scout`, `research`
- CTI-relevant: `security`, `security-scan`, `cti-expert`, `databases`, `devops`, `backend-development`, `mcp-builder`, `mcp-management`
- Docs: `docs`, `docs-seeker`, `repomix`, `mintlify`
- Utility: `find-skills`, `journal`, `git`, `worktree`, `preview`

92 skills total — many irrelevant to this project (frontend, mobile, gaming, etc.) but harmless when not invoked.

**Active hooks** (`.claude/settings.json`):
- `session-init` — env detection, project-type, plan naming
- `dev-rules-reminder` — injects rules + Plan Context into every prompt
- `subagent-init` — minimal context for spawned agents
- `scout-block` — blocks heavy dirs (node_modules, .git, etc.) per `.ckignore`
- `privacy-block` — blocks sensitive files (.env, secrets) without explicit approval
- `descriptive-name` — file naming guidance on Write
- `simplify-gate` — blocks ship/merge verbs when diff is large + unsimplified
- `session-state` — persists session progress
- `plan-format-kanban` — warns on bad plan.md link text

## What is intentionally absent

- `app/` — application code, created in Phase 1
- `tests/` — test suites, mirrors `app/`
- `pyproject.toml` — Phase 1
- `docker/` — compose stack, Phase 1
- `models/` — fine-tuned encoders, Phase 2
- `notebooks/` — exploratory analysis, ad-hoc
- `exports/` — STIX bundle output, runtime
- Frontend — out of scope; minimal review UI is server-rendered Jinja2 in Phase 2

## How to update this file

After any non-trivial change to project structure:
1. Run `/ck:docs` (invokes `docs-manager` agent) — it rebuilds this file from current state.
2. Or manually update **only when CLAUDE.md or `docs/system-architecture.md` changes structurally**.
3. Do not let this file drift from reality. Stale codebase summaries actively mislead the planner agent.

## Pointers

- **Want to start coding?** Read `CLAUDE.md` then `docs/AI-assisted_CTI_extractor.md` then run `/ck:plan "Phase 1: ingestion + IOC + minimal STIX"`.
- **Confused about a design choice?** Check `docs/system-architecture.md` first. If the answer requires updating the design, update that doc, not this one.
- **Adding a new module?** Update this file's repository layout section + add an entry in the architecture component map.

---

## Unresolved

- Phase 1 scaffolding hasn't been generated yet. First Python file ships after `/ck:plan` produces a Phase 1 plan, then `/ck:cook` executes it.
