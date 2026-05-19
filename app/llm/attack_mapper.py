"""ATT&CK technique candidate generation via Claude.

Phase 09 minimal: given a chunk's text + the IOCs found in it, ask the LLM to
propose at most 3 MITRE ATT&CK techniques (T#### or T####.###) with a short
justification quote. The justification MUST be a substring of the chunk
(evidence grounding); otherwise the candidate is dropped.

This is NOT the full RAG-grounded judge from the design doc — that needs an
ATT&CK retrieval index (Phase 11). Here we leverage the model's prior to
demonstrate the LLM-in-the-loop wiring end-to-end.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import structlog

from app.llm.client import LlmConfigError, get_client

log = structlog.get_logger(__name__)

_TECHNIQUE_RE = re.compile(r"^T\d{4}(?:\.\d{3})?$")

_SYSTEM = (
    "You are a CTI analyst mapping observations to MITRE ATT&CK Enterprise."
    " Read the supplied threat-report excerpt and the indicators extracted"
    " from it. Propose at most 3 plausible ATT&CK technique IDs.\n"
    "\n"
    "Constraints:\n"
    "- Use only technique IDs that exist in MITRE ATT&CK Enterprise (T####"
    " or T####.### format).\n"
    "- Each candidate MUST include a verbatim quote from the excerpt that"
    " supports the mapping. The quote is a substring of the excerpt; do not"
    " paraphrase.\n"
    "- If you cannot ground a candidate in the text, omit it.\n"
    "- Return ONLY a JSON array, no prose, no Markdown fences. Each item:"
    ' {"technique_id": "T####[.###]", "name": "...", "quote": "...",'
    ' "confidence": 0.0-1.0}.\n'
    "- If nothing can be grounded, return [].\n"
)


@dataclass(frozen=True, slots=True)
class AttackCandidate:
    """One LLM-proposed ATT&CK mapping with grounding quote."""

    technique_id: str
    name: str
    quote: str
    confidence: float


@dataclass(frozen=True, slots=True)
class AttackResult:
    """Aggregate result for a single chunk."""

    candidates: list[AttackCandidate]
    cached: bool
    input_tokens: int
    output_tokens: int


def _strip_code_fence(text: str) -> str:
    """Remove ```json fences if the model produced them despite instructions."""
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s)
    return s.strip()


def _validate_candidate(item: object, chunk_text: str) -> AttackCandidate | None:
    """Drop ungrounded or malformed entries; return :class:`AttackCandidate` on pass."""
    if not isinstance(item, dict):
        return None
    tid = str(item.get("technique_id", ""))
    if not _TECHNIQUE_RE.match(tid):
        return None
    quote = str(item.get("quote", "")).strip()
    if not quote or quote not in chunk_text:
        return None
    name = str(item.get("name", "")).strip()[:128] or "Unknown"
    try:
        conf = float(item.get("confidence", 0.5))
    except (TypeError, ValueError):
        conf = 0.5
    conf = max(0.0, min(1.0, conf))
    return AttackCandidate(technique_id=tid, name=name, quote=quote, confidence=conf)


def map_chunk_to_attack(
    chunk_text: str,
    *,
    ioc_summary: str = "",
    model: str | None = None,
) -> AttackResult:
    """Run ATT&CK candidate generation for a single chunk.

    Raises :class:`LlmConfigError` if no Anthropic credentials are configured.
    """
    client = get_client()  # may raise LlmConfigError
    user = (
        f"Excerpt:\n{chunk_text.strip()}\n\n"
        f"Indicators found in this excerpt:\n{ioc_summary.strip() or '(none)'}"
    )
    response = client.complete(
        system=_SYSTEM,
        user=user,
        model=model,
        temperature=0.0,
        max_tokens=1024,
    )

    raw = _strip_code_fence(response.text)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("attack_mapper.parse_error", body_head=raw[:200])
        parsed = []

    if not isinstance(parsed, list):
        log.warning("attack_mapper.unexpected_shape", got=type(parsed).__name__)
        parsed = []

    valid: list[AttackCandidate] = []
    for item in parsed:
        cand = _validate_candidate(item, chunk_text)
        if cand is not None:
            valid.append(cand)

    log.info(
        "attack_mapper.complete",
        proposed=len(parsed) if isinstance(parsed, list) else 0,
        valid=len(valid),
        cached=response.cached,
    )
    return AttackResult(
        candidates=valid,
        cached=response.cached,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )


__all__ = [
    "AttackCandidate",
    "AttackResult",
    "LlmConfigError",
    "map_chunk_to_attack",
]
