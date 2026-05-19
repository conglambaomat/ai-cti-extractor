"""Sanity tests for the ``app`` package itself.

Phase 1 baseline. Phase 02+ replace these with real domain tests.
"""

from __future__ import annotations

import re

import app


def test_version_present_and_semver_like() -> None:
    assert isinstance(app.__version__, str)
    assert re.match(r"^\d+\.\d+\.\d+", app.__version__)


def test_version_in_all_export() -> None:
    assert "__version__" in app.__all__
