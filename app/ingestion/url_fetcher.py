"""URL fetcher + content-type dispatcher.

Reads from HTTP(S) only; follows redirects; respects a 30s read timeout.
Returns ``(content_bytes, mime_type)`` so the caller can dispatch to the
right parser.
"""

from __future__ import annotations

import httpx

from app.core.exceptions import IngestionError, UnsupportedFormatError

_USER_AGENT = "ai-cti-extractor/0.1 (+https://github.com/conglambaomat/ai-cti-extractor)"
_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=15.0, pool=5.0)
_ALLOWED_MIME_PREFIXES = ("text/", "application/pdf", "application/xhtml")


async def fetch_url(url: str) -> tuple[bytes, str]:
    """Fetch ``url`` and return ``(content, mime_type)``."""
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=_TIMEOUT,
        headers={"User-Agent": _USER_AGENT},
    ) as client:
        try:
            response = await client.get(url)
        except httpx.HTTPError as e:
            raise IngestionError(f"http fetch failed: {e}") from e

    if response.status_code >= 400:
        msg = f"http {response.status_code} for {url}"
        raise IngestionError(msg)

    mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if not any(mime.startswith(p) for p in _ALLOWED_MIME_PREFIXES):
        msg = f"unsupported content-type {mime!r} for {url}"
        raise UnsupportedFormatError(msg)

    return response.content, mime


__all__ = ["fetch_url"]
