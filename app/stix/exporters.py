"""Bundle serialization helpers for storage + comparison.

Canonical JSON (sorted keys, no whitespace, UTF-8) is required so the same
intermediate representation always produces the same byte string and the
same sha256 — used as ``exports.bundle_hash`` for tamper-evidence.
"""

from __future__ import annotations

import hashlib
import json

import stix2


def serialize_canonical(bundle: stix2.v21.Bundle) -> str:
    """Return canonical JSON: sorted keys, compact separators, ASCII-allowed."""
    raw = json.loads(bundle.serialize())
    return json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def bundle_hash(bundle: stix2.v21.Bundle) -> str:
    """sha256 of the canonical serialization (hex digest)."""
    return hashlib.sha256(serialize_canonical(bundle).encode("utf-8")).hexdigest()


__all__ = ["bundle_hash", "serialize_canonical"]
