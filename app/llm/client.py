"""Anthropic-compatible LLM client with sqlite-backed response cache.

The cache key is sha256 of canonicalized (system + prompt + retrieved + model + temperature).
TTL is 30 days for ATT&CK candidate generation (mappings are stable; refresh
when the technique catalog updates).

Settings priority order (matching ~/.claude/settings.json convention):
1. ``ANTHROPIC_AUTH_TOKEN`` + ``ANTHROPIC_BASE_URL`` (proxy)
2. ``ANTHROPIC_API_KEY`` (direct api.anthropic.com)
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.redaction import redact_for_external_llm

log = structlog.get_logger(__name__)

_CACHE_TTL_SECONDS = 30 * 24 * 3600
_CACHE_PATH = Path(settings.STORAGE_LOCAL_DIR).parent / "llm_cache.sqlite"


class LlmConfigError(AppError):
    """No usable Anthropic credential."""


class LlmCallError(AppError):
    """SDK raised an error after retries exhausted."""


@dataclass(frozen=True, slots=True)
class LlmResponse:
    """Single Claude completion result."""

    text: str
    model: str
    cached: bool
    input_tokens: int
    output_tokens: int


class _Cache:
    """Tiny sqlite cache, key = sha256 hex; value = JSON blob."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS llm_cache ("
            " key TEXT PRIMARY KEY,"
            " value TEXT NOT NULL,"
            " created_at INTEGER NOT NULL"
            ")"
        )
        self._conn.commit()

    def get(self, key: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT value, created_at FROM llm_cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        if int(time.time()) - int(row[1]) > _CACHE_TTL_SECONDS:
            self._conn.execute("DELETE FROM llm_cache WHERE key = ?", (key,))
            self._conn.commit()
            return None
        return json.loads(row[0])  # type: ignore[no-any-return]

    def put(self, key: str, value: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO llm_cache (key, value, created_at) VALUES (?, ?, ?)",
            (key, json.dumps(value, ensure_ascii=False), int(time.time())),
        )
        self._conn.commit()


def _digest(*parts: Any) -> str:
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class LlmClient:
    """Thin Anthropic SDK wrapper with redaction + caching."""

    def __init__(self) -> None:
        # Lazy import keeps the SDK out of import time for tests/lint.
        import anthropic

        api_key = (
            settings.ANTHROPIC_AUTH_TOKEN.get_secret_value()
            if settings.ANTHROPIC_AUTH_TOKEN is not None
            else (
                settings.ANTHROPIC_API_KEY.get_secret_value()
                if settings.ANTHROPIC_API_KEY is not None
                else None
            )
        )
        if not api_key:
            msg = (
                "no Anthropic credential found; set ANTHROPIC_AUTH_TOKEN or"
                " ANTHROPIC_API_KEY"
            )
            raise LlmConfigError(msg)

        kwargs: dict[str, Any] = {"api_key": api_key}
        if settings.ANTHROPIC_BASE_URL:
            # Anthropic SDK appends /v1/messages itself; strip a trailing /v1
            # so proxies configured with .../v1 don't hit /v1/v1/messages.
            base = settings.ANTHROPIC_BASE_URL.rstrip("/")
            if base.endswith("/v1"):
                base = base[: -len("/v1")]
            kwargs["base_url"] = base
        self._client = anthropic.Anthropic(**kwargs)
        self._cache = _Cache(_CACHE_PATH)

    def complete(
        self,
        *,
        system: str,
        user: str,
        retrieved: str = "",
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LlmResponse:
        """Run a single chat completion. Redacts before send. Caches result."""
        chosen_model = model or settings.ANTHROPIC_DEFAULT_HAIKU_MODEL
        chosen_temp = temperature if temperature is not None else settings.LLM_TEMPERATURE
        chosen_max = max_tokens or settings.LLM_MAX_TOKENS

        safe_user = (
            redact_for_external_llm(user)[0] if settings.REDACT_BEFORE_LLM else user
        )
        safe_retrieved = (
            redact_for_external_llm(retrieved)[0]
            if (retrieved and settings.REDACT_BEFORE_LLM)
            else retrieved
        )
        full_prompt = (
            f"{safe_user}\n\n<retrieved>\n{safe_retrieved}\n</retrieved>"
            if safe_retrieved
            else safe_user
        )

        cache_key = _digest(system, full_prompt, chosen_model, chosen_temp)
        hit = self._cache.get(cache_key)
        if hit is not None:
            return LlmResponse(
                text=hit["text"],
                model=hit["model"],
                cached=True,
                input_tokens=hit.get("input_tokens", 0),
                output_tokens=hit.get("output_tokens", 0),
            )

        from anthropic.types import MessageParam, TextBlockParam

        prompt_block: TextBlockParam = {"type": "text", "text": full_prompt}
        message: MessageParam = {"role": "user", "content": [prompt_block]}
        try:
            msg = self._client.messages.create(
                model=chosen_model,
                max_tokens=chosen_max,
                temperature=chosen_temp,
                system=system,
                messages=[message],
            )
        except Exception as e:  # SDK raises various subclasses
            # Surface upstream body to make 400-class errors debuggable.
            body = getattr(getattr(e, "response", None), "text", "") or str(e)
            log.warning("llm.call.upstream_error", error=str(e), body=body[:500])
            msg_str = f"Anthropic call failed: {body[:300] or e}"
            raise LlmCallError(msg_str) from e

        # The SDK returns a list of content blocks; concat text-typed ones.
        from anthropic.types import TextBlock

        text_parts = [block.text for block in msg.content if isinstance(block, TextBlock)]
        text = "".join(text_parts).strip()

        usage_in = int(getattr(msg.usage, "input_tokens", 0))
        usage_out = int(getattr(msg.usage, "output_tokens", 0))

        record = {
            "text": text,
            "model": chosen_model,
            "input_tokens": usage_in,
            "output_tokens": usage_out,
        }
        self._cache.put(cache_key, record)

        log.info(
            "llm.call",
            model=chosen_model,
            input_tokens=usage_in,
            output_tokens=usage_out,
            cached=False,
        )
        return LlmResponse(
            text=text,
            model=chosen_model,
            cached=False,
            input_tokens=usage_in,
            output_tokens=usage_out,
        )


_client_singleton: LlmClient | None = None


def get_client() -> LlmClient:
    """Return the process-wide :class:`LlmClient` singleton."""
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = LlmClient()
    return _client_singleton


__all__ = ["LlmCallError", "LlmClient", "LlmConfigError", "LlmResponse", "get_client"]
