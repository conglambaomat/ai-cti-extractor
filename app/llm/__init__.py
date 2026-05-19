"""LLM client wrappers (provider-agnostic).

Phase 09 deliverable. Anthropic-compatible (covers both api.anthropic.com and
proxy gateways like the one in ~/.claude/settings.json).

Cache key: (prompt_hash, retrieved_hash, model). TTL >= 24h per CLAUDE.md.
"""

from __future__ import annotations

from app.llm.client import LlmClient, LlmResponse, get_client

__all__ = ["LlmClient", "LlmResponse", "get_client"]
