"""RFC 7807 / RFC 9457 ``application/problem+json`` envelope.

Every API error response goes through :class:`Problem` so clients can rely on
a stable shape with the ``correlation_id`` extension for log correlation.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

PROBLEM_CONTENT_TYPE = "application/problem+json"


class Problem(BaseModel):
    """RFC 7807 / RFC 9457 problem envelope plus stable extensions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: str = Field(default="about:blank", description="URI for problem type")
    title: str = Field(description="Stable short summary of the problem type")
    status: int = Field(ge=400, le=599, description="HTTP status code")
    detail: str = Field(description="Occurrence-specific explanation")
    instance: str = Field(description="URI for this specific occurrence")
    correlation_id: str = Field(description="Request correlation ID")
    error_code: str = Field(description="Machine-readable error code")


_TYPE_NAMESPACE = "https://cti.local/errors"


def make_problem(
    *,
    title: str,
    status: int,
    detail: str,
    instance: str,
    correlation_id: str,
    error_code: str,
    type_slug: str | None = None,
) -> Problem:
    """Build a Problem with optional namespaced ``type`` URI."""
    type_uri = (
        f"{_TYPE_NAMESPACE}/{type_slug}" if type_slug else "about:blank"
    )
    return Problem(
        type=type_uri,
        title=title,
        status=status,
        detail=detail,
        instance=instance,
        correlation_id=correlation_id,
        error_code=error_code,
    )


__all__ = ["PROBLEM_CONTENT_TYPE", "Problem", "make_problem"]
