---
phase: 1
title: "Config flags + DB schema additions + upsert helper"
status: pending
priority: P1
effort: "1h"
dependencies: []
---

# Phase 01: Config flags, DB schema additions, upsert helper

## Overview

Foundational tweaks needed by every subsequent phase. Pure additive — no behavior change to existing modules.

## Requirements

- Functional:
  - `Settings.DEBUG: bool = False` — gates `str(exc)` exposure in 5xx responses
  - `Settings.TRUST_PROXY_HEADERS: bool = False` — controls correlation_id spoof prevention
  - `Settings.MAX_CONCURRENT_PIPELINES: int = 3` — pipeline semaphore size
  - `EvidenceSpan` gets `evidence_id` column (unique, indexed) — string with `e-` prefix
  - `app/db/upsert.py` helper for dialect-portable `INSERT ... ON CONFLICT DO NOTHING`
- Non-functional:
  - mypy --strict clean
  - All existing tests still pass

## Architecture

### Settings additions
```python
# app/core/config.py — Add to Settings class
DEBUG: bool = False
TRUST_PROXY_HEADERS: bool = False
MAX_CONCURRENT_PIPELINES: int = Field(default=3, ge=1, le=32)
```

### EvidenceSpan model fix
```python
# app/db/models/evidence_span.py
class EvidenceSpan(UuidMixin, TimestampMixin, Base):
    __tablename__ = "evidence_spans"

    evidence_id: Mapped[str] = mapped_column(
        String(96), unique=True, nullable=False, index=True
    )  # NEW: schema-side deterministic id (e-{sha256[:16+]})
    chunk_id: Mapped[str] = mapped_column(...)
    text_span: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
```

UUID PK kept for FK consistency. `evidence_id` is the user-facing key (matches `Evidence.evidence_id` from `app/schemas/evidence.py`).

### Upsert helper
```python
# app/db/upsert.py
"""Dialect-portable ON CONFLICT DO NOTHING helper.

SQLite via app.db.session today; Postgres in Phase 08+.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import Insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession


def insert_ignore(
    session: AsyncSession,
    table: Any,
    rows: list[dict[str, Any]],
    *,
    index_elements: list[str],
) -> Insert:
    """Build INSERT ... ON CONFLICT DO NOTHING for the session's dialect."""
    bind = session.bind or session.get_bind()
    dialect = bind.dialect.name  # type: ignore[union-attr]
    builder = sqlite_insert if dialect == "sqlite" else pg_insert
    stmt = builder(table).values(rows).on_conflict_do_nothing(
        index_elements=index_elements
    )
    return stmt
```

## Related Code Files

- Modify: `app/core/config.py` (3 settings)
- Modify: `app/db/models/evidence_span.py` (1 column)
- Create: `app/db/upsert.py` (~40 LOC)
- Create: `tests/unit/db/test_upsert.py`

## Implementation Steps

1. Add `DEBUG`, `TRUST_PROXY_HEADERS`, `MAX_CONCURRENT_PIPELINES` to `Settings`. Re-export nothing new.
2. Add `evidence_id` column to `EvidenceSpan`. Re-run `Base.metadata.create_all` in test fixtures (auto via existing conftest).
3. Implement `insert_ignore`. Test: insert duplicate row twice, count rows = 1.
4. Run `pytest tests/unit/db/ -x`. Run `mypy --strict app/`. Run `ruff check app/`.

## Success Criteria

- [ ] `Settings().DEBUG is False` in default env
- [ ] `EvidenceSpan` accepts `evidence_id` and rejects duplicate `evidence_id` (UNIQUE)
- [ ] `insert_ignore` works on SQLite; signature is dialect-agnostic
- [ ] All existing tests still pass
- [ ] mypy + ruff clean

## Risk Assessment

- **Risk**: existing audit_chain or extraction tests broken by schema change. **Mitigation**: `evidence_id` is nullable=False but no production data exists yet → in-memory test DB recreates fresh.
