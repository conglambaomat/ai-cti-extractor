"""Evidence span: the load-bearing primitive of evidence grounding.

Every claim in :class:`IntermediateCTI.candidates` references one or more
``Evidence`` records by id. An evidence record cites exact byte offsets in a
chunk so an analyst can reproduce the claim from the source document.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Evidence(BaseModel):
    """An exact byte-offset citation inside a chunk.

    Invariants:
        * ``char_end`` is strictly greater than ``char_start``.
        * ``text_span`` is non-empty.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str = Field(
        pattern=r"^e-[0-9a-f]{16,}$",
        description="Stable id; deterministic per (chunk_id, char_start, char_end, claim_type)",
    )
    chunk_id: str
    text_span: str = Field(min_length=1, max_length=8192)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_offsets(self) -> Evidence:
        if self.char_end <= self.char_start:
            msg = f"char_end ({self.char_end}) must be > char_start ({self.char_start})"
            raise ValueError(msg)
        return self
