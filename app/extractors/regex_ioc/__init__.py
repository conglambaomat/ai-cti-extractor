"""Regex IOC extractor — Phase 1 deterministic, high-precision IOC extraction.

Public surface:

    from app.extractors.regex_ioc import extract, ExtractionResult, __extractor_id__

The extractor is pure: same chunk → same output. Every match carries an
``Evidence`` row with absolute char offsets in the parent document.
"""

from __future__ import annotations

from app.extractors.regex_ioc.extractor import ExtractionResult, extract
from app.extractors.regex_ioc.version import __extractor_id__, __extractor_name__, __version__

__all__ = [
    "ExtractionResult",
    "__extractor_id__",
    "__extractor_name__",
    "__version__",
    "extract",
]
