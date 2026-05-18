# Code Standards

**Project:** AI-Assisted CTI Extractor
**Last updated:** 2026-05-18

This document defines coding rules. Every PR is checked against it. Deviations require explicit justification in the plan and approval before merge.

---

## 1. Core principles (in priority order)

1. **Evidence grounding.** Every output that claims a fact about the input report must carry evidence spans. Code that produces extracted data without `evidence_ids` is broken.
2. **Abstain over fabricate.** When uncertain, return `None` / raise typed exception / route to review. Never invent fields.
3. **Boring strictness.** Strict types, narrow exceptions, validated boundaries. Predictable beats clever.
4. **YAGNI / KISS / DRY.** Implement what's required by the plan. Refactor when duplication crosses 3 sites.
5. **Tests as contracts.** A feature without tests covering happy + error + abstention paths is incomplete.

## 2. Language & runtime

- Python **3.11+** (use `match`, `tomllib`, exception groups, fine-grained typing).
- Async-first for I/O paths. Sync only for pure CPU work (regex, parsing).
- Type hints on every public function. `mypy --strict` mandatory for `app/`.
- No `from __future__ import annotations` workaround — use real types.

## 3. File organization

```
app/
├── api/                   FastAPI routers, request/response Pydantic models
├── core/                  config, logging, security, telemetry
├── ingestion/             parsers, OCR, chunking
├── extractors/            regex / encoder / LLM extraction modules
│   └── prompts/           versioned prompt templates (v1.md, v2.md, ...)
├── rag/                   typed retrieval over 4 corpora
├── stix/                  builders, validators, exporters
├── review/                triage queue, diff, acceptance
├── db/
│   ├── models/            SQLAlchemy ORM models, one per table
│   ├── repositories/      data-access methods, one per aggregate
│   └── migrations/        Alembic
└── jobs/                  worker, pipelines
tests/                     mirrors app/ structure
scripts/                   one-off CLI utilities (with __main__ guard)
docker/                    Dockerfile, compose, entrypoint scripts
docs/                      project docs
plans/                     /ck:plan output
```

### File-size limits
- **Soft limit:** 300 LOC per `.py` file (excluding blank/comment/docstring).
- **Hard limit:** 500 LOC. Refactor required.
- Exception: auto-generated code (mark with `# auto-generated, do not edit`).

When approaching the limit:
- Extract pure functions to a sibling `_helpers.py`.
- Split classes by concern (e.g., `attack_mapper.py` → `attack_candidates.py` + `attack_reranker.py`).
- Extract Pydantic models to a `_schemas.py` next to the module.

## 4. Naming

| Kind | Convention | Examples |
|---|---|---|
| Files | kebab-case for shell scripts; **snake_case** for Python (PEP 8) | `regex_ioc_extractor.py`, `setup-dev.sh` |
| Modules | snake_case | `attack_mapper`, `stix_builders` |
| Classes | PascalCase | `IndicatorBuilder`, `AttackCandidate` |
| Functions / methods | snake_case verbs | `extract_iocs`, `validate_bundle` |
| Constants | UPPER_SNAKE_CASE | `MAX_CHUNK_TOKENS`, `DEFAULT_MODEL` |
| Private | leading underscore | `_normalize_domain`, `_HashChain` |
| Type aliases | PascalCase | `EvidenceId = str` |
| Pydantic models | PascalCase + suffix | `IngestRequest`, `ExtractionResponse`, `IndicatorPayload` |

Names should describe **what** not **how**. `parse_pdf` over `read_pdf_with_pdfplumber`.

## 5. Imports

- Order: stdlib → third-party → first-party (`app.*`) → relative (`.`). Blank line between groups.
- No `import *`.
- No relative imports across packages (within `app/api/`, relative is OK; cross-package use absolute).
- Avoid circular imports by keeping `core/` dependency-free of other packages.

## 6. Error handling

- Define typed exceptions in `app/core/exceptions.py`. Hierarchy:
  ```
  AppError
    IngestionError
      UnsupportedFormatError
      OCRFailedError
    ExtractionError
      EvidenceMissingError
      AbstentionRequired
    StixError
      StixSchemaError
      StixSemanticError
    ExportError
      OpenCTIError
      MISPError
      TAXIIError
  ```
- Catch specific. **Never** bare `except:` or `except Exception:` without a re-raise.
- Async error propagation: cancel cleanly. Use `anyio.create_task_group` not bare `asyncio.gather` when partial failure must abort siblings.
- Don't log + raise the same exception twice (avoids duplicate stack traces).
- HTTP errors: raise `HTTPException` only at the API boundary. Internal layers raise `AppError` subclasses; an exception handler maps them.

## 7. Logging

- Use `app.core.logging.get_logger(__name__)`. Never `print` in app code (only in `scripts/__main__`).
- Structured JSON in production. Include `correlation_id`, `document_id`, `pipeline_step` when present.
- Levels:
  - `DEBUG` — development trace
  - `INFO` — pipeline progress, export actions
  - `WARNING` — abstention, low-confidence rejection, retried operations
  - `ERROR` — handled failures
  - `CRITICAL` — data integrity violation, audit chain break
- Never log raw report text or secrets. Use `app.core.security.redact()`.

## 8. Configuration

- All config via `app.core.config.Settings` (Pydantic `BaseSettings`).
- No `os.environ.get()` scattered through code. Read once at module import via `settings`.
- Defaults safe for dev, explicit override required for prod (`APP_ENV=production`).
- Sensitive values: read from env or secrets manager, never default in code.

## 9. Pydantic models

- Use Pydantic v2.
- One model per concept. Don't reuse API models as DB models — separate them.
- Required fields are required. Don't make everything `Optional` "just in case".
- Validators (`field_validator`, `model_validator`) live with the model.
- Serializers explicit when format matters (timestamps, UUIDs).
- For STIX intermediate JSON, use Pydantic to enforce evidence-required invariant:
  ```python
  class IocCandidate(BaseModel):
      type: Literal["ipv4", "domain", "url", "hash", ...]
      value: str
      evidence_ids: list[str] = Field(min_length=1)  # invariant: must have evidence
  ```

## 10. Database

- SQLAlchemy 2.0 async. Sessions via context manager. Never share sessions across requests.
- Repository pattern: `app/db/repositories/<aggregate>.py` exposes domain methods, not raw queries.
- Migrations via Alembic. Every schema change ships with a migration in the same PR.
- No `SELECT *`. Project to columns you need.
- Bulk operations use `executemany` / `bulk_insert_mappings` for ≥ 100 rows.
- Foreign keys + indexes declared in models. Add indexes for any column used in `WHERE`.

## 11. LLM integration rules

- Any LLM call goes through `app.extractors.llm_judge`. No direct provider SDK calls scattered through code.
- Inputs **must** be evidence-typed:
  ```python
  judge(
      task: Literal["attack_rerank", "relation_normalize", "stix_complete"],
      evidence: list[Evidence],     # required
      retrieved: list[RetrievedDoc],
      schema: type[BaseModel],      # output schema
  ) -> BaseModel | AbstentionRequired
  ```
- Prompts in `app/extractors/prompts/<task>_v<n>.md`. Prompt hash recorded in `model_runs` table.
- Output goes through Pydantic validation before any downstream use.
- Abstention path: judge returns `AbstentionRequired` → log + route to review. Never silently fill with placeholder.
- Token counting: enforce `LLM_MAX_TOKENS`. Truncate retrieved context before prompt assembly, not in the prompt template.

## 12. Test rules

### Structure
```
tests/
├── unit/                  # one test file per app/ module
├── integration/           # cross-module pipeline slices
├── e2e/                   # full pipeline against fixture reports
├── property/              # Hypothesis-based fuzzing (esp. STIX)
└── fixtures/
    ├── reports/           # sample threat reports for ingestion tests
    ├── stix/              # known-good and known-bad STIX bundles
    └── attack/            # ATT&CK snapshot for deterministic tests
```

### Coverage targets
- `app/extractors/`, `app/stix/`, `app/rag/`: ≥ 80%
- `app/api/`, `app/db/`: ≥ 70%
- `app/core/`: ≥ 90% (config, security)

### Required test cases per extractor
- Happy path (typical input)
- Empty input
- Malformed input (truncated, mojibake, mixed languages)
- Evidence-span correctness (returned spans actually contain the claim)
- Abstention case (insufficient evidence → returns abstention)
- Idempotency (same input → same output)

### STIX tests use Hypothesis
- Property: any built bundle parses with `stix2.parse(allow_custom=False)`.
- Property: every relationship's `source_ref` and `target_ref` resolve to objects in the same bundle.
- Property: every `attack-pattern` `external_references` includes a valid ATT&CK ID.

## 13. Security rules

### Code-level
- Never `eval` / `exec` / `pickle.load` from untrusted input.
- SQL via parameterized queries / ORM only. No string interpolation.
- File paths: validate with `Path.resolve()` and check against allowed root.
- HTTP clients: explicit timeout. Default `httpx.Timeout(connect=5, read=30)`.
- TLS verification ON by default. `MISP_VERIFY_TLS=true`.

### CTI-specific
- Report content is untrusted. Never feed raw report text into a tool-calling LLM scope.
- Apply `redact_for_external_llm()` before any external LLM call.
- Audit log every: extraction run, analyst edit, export action, model version change.
- Audit log entries are append-only with hash chain (each row hashes previous row).
- Reports stored with original sha256 + ingest timestamp; treat as immutable evidence.

### Secret handling
- No hardcoded secrets. `bandit` enforces this.
- Secrets via env, Docker secrets, or Vault.
- `.env` gitignored. Only `.env.example` committed.
- Pre-commit hook (when re-enabled): scan for common secret patterns.

## 14. Concurrency rules

- API handlers: async.
- Pipeline steps: async, but CPU-bound work (regex on large text, embedding compute) runs in `asyncio.to_thread` or a worker process.
- Shared mutable state: don't. Use queue + worker. If unavoidable, document the lock.
- Job idempotency: `process_document(doc_id)` must produce identical output on re-run with same model versions.

## 15. Performance rules

- Profile before optimizing. Use `pyinstrument` for hot paths.
- Don't load 1M-row tables. Stream + paginate.
- Embeddings: batch (default 32). Don't embed one chunk at a time.
- LLM calls: cache by `(prompt_hash, retrieved_hash, model)` for 24h to dedupe re-runs.
- Cache invalidation: on prompt version bump or model version bump, version-prefix the cache key.

## 16. Documentation rules

- Public modules: top-of-file docstring describing purpose, key types, examples.
- Public functions: docstring with Args/Returns/Raises.
- Don't document obvious code. Document **why** when non-obvious; **what** for public API only.
- Module ↔ test cross-reference: every test file has `# tests: app/<module>.py` comment for navigation.
- Update `docs/codebase-summary.md` when adding/removing modules.

## 17. Git rules

- Conventional commits: `feat`, `fix`, `refactor`, `test`, `perf`, `chore`, `ci`, `build`, `docs`.
- Scope when sensible: `feat(extractors): ...`, `fix(stix): ...`.
- Subject ≤ 72 chars. Body wrapped at 100.
- One logical change per commit.
- Branch names: `<type>/<short-slug>` (matches `branchPattern` in `.claude/.ck.json`).
- No AI attribution. No `Co-authored-by: Claude`.
- Don't `--no-verify` to skip hooks.

## 18. Pre-merge checklist

```
[ ] Plan referenced (link to plans/<id>/plan.md)
[ ] mypy --strict app/  passes
[ ] ruff check app/     passes
[ ] bandit -r app/      no high/medium issues
[ ] pip-audit            no high CVEs
[ ] pytest -x            all pass
[ ] Coverage >= target for changed modules
[ ] STIX tests pass if changes touch app/stix/
[ ] Security review for changes touching app/api/, app/core/security.py, app/extractors/llm_judge.py
[ ] docs/codebase-summary.md updated if modules added/removed
[ ] Audit log entry verified for export-related changes
```

## 19. Anti-patterns (auto-rejected in review)

- Bare `except:` or `except Exception` without re-raise.
- Returning empty dict / list to "indicate failure" — raise instead.
- Using `Any` to escape mypy. Justify with comment if unavoidable.
- Mock objects in production code paths. Mocks live in `tests/`.
- Direct LLM SDK calls outside `app/extractors/llm_judge.py`.
- Reading raw report text into a context that gets passed to a tool-calling LLM scope.
- STIX bundles built with `allow_custom=True` to "make it work".
- TODO/FIXME comments without an issue ID and owner.
- `print()` in app code.
- Disabling tests to ship faster.

## 20. Naming for new artifacts created during runtime

| Artifact | Format |
|---|---|
| Plan dir | `plans/{date}-{issue}-{slug}/` (date = `YYMMDD-HHmm`) |
| Reports | `plans/{plan-dir}/reports/{type}-{date}-{slug}.md` |
| Phase files | `plans/{plan-dir}/phase-{NN}-{slug}.md` |
| Migrations | `app/db/migrations/{date}_{slug}.py` |
| Prompt versions | `app/extractors/prompts/{task}_v{n}.md` |
| STIX export bundles | `exports/{date}-{document-id}-{bundle-hash}.json` |

---

## Unresolved questions

1. Lock file: `uv.lock` (faster) vs `poetry.lock` (more mature) — decide in Phase 1 setup.
2. Pre-commit framework: revive `husky` (Node) or use `pre-commit` (Python-native)?
3. Code formatter: `ruff format` (one tool) vs `black` (battle-tested) — leaning ruff.
4. Type stubs for `stix2` library — write or rely on inline ignores?
