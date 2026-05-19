"""Typed exception hierarchy.

Every ``raise`` in ``app/`` should use one of these (or a subclass).
Catching ``AppError`` at the API boundary lets the error handler map to
RFC 7807 problem+json without ``except Exception``.
"""

from __future__ import annotations


class AppError(Exception):
    """Base for every application-level error."""


# ----- Ingestion ------------------------------------------------------------


class IngestionError(AppError):
    """Failure during document ingestion (parse, OCR, chunking)."""


class UnsupportedFormatError(IngestionError):
    """File format / MIME type the dispatcher cannot handle."""


class UnsupportedLanguageError(IngestionError):
    """Detected language is outside the project scope (English-only)."""


class OCRFailedError(IngestionError):
    """Tesseract failed to extract text from an image-only page."""


# ----- Extraction -----------------------------------------------------------


class ExtractionError(AppError):
    """Failure during the rules / encoder / LLM extraction layers."""


class EvidenceMissingError(ExtractionError):
    """An extractor produced a claim without an evidence span."""


class AbstentionRequired(ExtractionError):
    """An LLM judge cannot answer with sufficient confidence; route to review."""


# ----- STIX -----------------------------------------------------------------


class StixError(AppError):
    """STIX 2.1 layer failure."""


class StixSchemaError(StixError):
    """Bundle failed Pydantic or stix2 strict-parse validation."""


class StixSemanticError(StixError):
    """Bundle failed semantic ref-closure or vocab checks."""


# ----- Export ---------------------------------------------------------------


class ExportError(AppError):
    """Failure pushing a bundle to OpenCTI / MISP / TAXII."""


class OpenCTIError(ExportError):
    """OpenCTI GraphQL or worker import failure."""


class MISPError(ExportError):
    """MISP REST API failure."""


class TAXIIError(ExportError):
    """TAXII 2.1 server failure."""


# ----- Audit ----------------------------------------------------------------


class AuditChainError(AppError):
    """Audit log hash chain integrity violation."""


__all__ = [
    "AbstentionRequired",
    "AppError",
    "AuditChainError",
    "EvidenceMissingError",
    "ExportError",
    "ExtractionError",
    "IngestionError",
    "MISPError",
    "OCRFailedError",
    "OpenCTIError",
    "StixError",
    "StixSchemaError",
    "StixSemanticError",
    "TAXIIError",
    "UnsupportedFormatError",
    "UnsupportedLanguageError",
]
