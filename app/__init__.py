"""AI-Assisted Cyber Threat Intelligence Extractor.

Hybrid neuro-symbolic pipeline for converting unstructured threat reports
into STIX 2.1 bundles with MITRE ATT&CK mappings and evidence-span grounding.

Public surface:
    __version__: package version (read by app.api.main + diagnostics)
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]
