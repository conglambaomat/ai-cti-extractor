"""Stable identity for the regex IOC extractor.

The extractor name + version end up in:
- ``IocCandidate.extractor`` (e.g. ``"regex_ioc@1.0.0"``)
- ``Provenance.extractors[*].name`` and ``.version``
- audit log entries

Bump :data:`__version__` whenever extractor behavior changes (new pattern,
new normalization rule, new defang format) so re-runs can detect drift.
"""

from __future__ import annotations

__extractor_name__ = "regex_ioc"
__version__ = "1.0.0"
__extractor_id__ = f"{__extractor_name__}@{__version__}"

__all__ = ["__extractor_id__", "__extractor_name__", "__version__"]
