"""Database layer: async SQLAlchemy 2.0 session, ORM models, repositories.

The package supports both **SQLite** (development default) and **Postgres**
(production target) via the same SQLAlchemy abstractions. ~10% of the
schema needs minor tweaks across the two backends:

  * UUID columns are stored as ``CHAR(36)`` strings for SQLite portability.
  * Lists (``evidence_ids``) are stored as JSON; Postgres deployments may
    later migrate to ``ARRAY(UUID)`` for index efficiency.
  * Audit row-locking uses application-level mutex on SQLite and
    ``SELECT ... FOR UPDATE`` on Postgres.
"""

from __future__ import annotations
