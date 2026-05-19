"""Provenance — append-only ledger of extractor runs that produced an extraction.

Every extractor that touched the document records itself here so that an
analyst can reproduce or audit any claim. Provenance is **immutable**: new
runs are appended via :meth:`Provenance.append` which returns a new instance.
"""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExtractorRun(BaseModel):
    """A single extractor invocation (rule layer, encoder, or LLM call)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, description="Human-readable extractor identifier")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$", description="SemVer of the extractor module")
    model: str | None = Field(
        default=None,
        description="Model identifier when LLM/encoder, e.g. 'gpt-4o-mini-2024-07-18'",
    )
    started_at: datetime
    ended_at: datetime
    config_hash: str = Field(
        pattern=r"^[a-f0-9]{64}$",
        description="sha256 of canonical-json of the extractor's effective config",
    )

    @model_validator(mode="after")
    def _validate_time_ordering(self) -> ExtractorRun:
        if self.ended_at < self.started_at:
            msg = f"ended_at ({self.ended_at}) must be >= started_at ({self.started_at})"
            raise ValueError(msg)
        return self


class Provenance(BaseModel):
    """Immutable append-only sequence of extractor runs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    extractors: list[ExtractorRun] = Field(default_factory=list)
    pipeline_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    schema_version: str = Field(default="2026.05.18")

    def append(self, run: ExtractorRun) -> Self:
        """Return a new :class:`Provenance` with ``run`` appended.

        Original instance is unchanged (frozen). Use the returned instance
        in subsequent steps.
        """
        return self.model_copy(update={"extractors": [*self.extractors, run]})
