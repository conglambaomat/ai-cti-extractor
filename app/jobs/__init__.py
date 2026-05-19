"""Background-task pipelines for the API surface."""

from __future__ import annotations

from app.jobs.pipelines import process_document

__all__ = ["process_document"]
