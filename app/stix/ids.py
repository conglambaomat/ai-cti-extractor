"""Deterministic STIX object IDs.

The default ``stix2`` library generates a fresh UUIDv4 per object; this is
useful for one-shot scripts but breaks our pipeline because re-running the
extractor on the same document would emit different IDs every time, which:

  * Inflates audit logs (every run looks like new data).
  * Breaks dedup at OpenCTI on re-import.
  * Prevents stable cross-references in tests.

We override with UUIDv5 keyed on stable content. The project namespace is
fixed forever; bumping it is a breaking change to every stored bundle.
"""

from __future__ import annotations

import uuid

# Project-scoped UUIDv5 namespace. NEVER change.
PROJECT_NS = uuid.UUID("a4d70b75-6f4a-5c66-8b6e-9c1f5d2a3e4f")


def indicator_id(doc_id: str, pattern: str, pattern_type: str = "stix") -> str:
    """Deterministic ``indicator--<uuid>`` keyed on (doc, pattern_type, pattern)."""
    seed = f"{doc_id}|{pattern_type}|{pattern}"
    return f"indicator--{uuid.uuid5(PROJECT_NS, seed)}"


def report_id(doc_id: str) -> str:
    """Deterministic ``report--<uuid>`` keyed on doc id."""
    seed = f"{doc_id}|report"
    return f"report--{uuid.uuid5(PROJECT_NS, seed)}"


def relationship_id(source_ref: str, relationship_type: str, target_ref: str) -> str:
    """Deterministic ``relationship--<uuid>`` keyed on (source, type, target)."""
    seed = f"{source_ref}|{relationship_type}|{target_ref}"
    return f"relationship--{uuid.uuid5(PROJECT_NS, seed)}"


def bundle_id(child_object_ids: list[str]) -> str:
    """Deterministic ``bundle--<uuid>`` keyed on the sorted set of child ids.

    Two builds with identical child objects (in any order) produce the same
    Bundle id, which keeps :func:`app.stix.exporters.bundle_hash` stable
    across pipeline re-runs.
    """
    seed = "|".join(sorted(set(child_object_ids)))
    return f"bundle--{uuid.uuid5(PROJECT_NS, seed)}"


__all__ = ["PROJECT_NS", "bundle_id", "indicator_id", "relationship_id", "report_id"]
