"""End-to-end pipeline test covering the full HTTP surface.

Uses ``httpx.AsyncClient`` with ``ASGITransport`` so no real network is
needed. The same in-memory SQLite engine backs both the request session and
the BackgroundTask orchestrator via ``app.db.session.SessionFactory``, so we
need the orchestrator to share the same engine. We override
``SessionFactory`` for this test to point at the test app's engine.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import structlog
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.db.audit_chain import verify_chain
from app.main import create_app

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "reports" / "sample_cti.md"


@pytest.fixture(autouse=True)
def _isolated_logging() -> None:
    structlog.contextvars.clear_contextvars()


@pytest.fixture()
async def app_and_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Per-test SQLite + storage roots
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'cti.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("LOG_LEVEL", "ERROR")

    cfg = Settings()
    app = create_app(cfg)

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with LifespanManager(app):
        # The orchestrator runs as a background task and opens its own
        # ``SessionFactory``. Redirect that module-level factory to the same
        # engine the request path uses so writes are visible.
        from app.jobs import pipelines as pipelines_mod

        monkeypatch.setattr(
            pipelines_mod, "SessionFactory", app.state.session_factory
        )

        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield app, c, app.state.session_factory


async def _wait_complete(
    client: AsyncClient,
    doc_id: str,
    *,
    timeout: float = 10.0,
    accept: tuple[str, ...] = ("complete", "no_iocs"),
) -> dict:  # type: ignore[type-arg]
    deadline = asyncio.get_event_loop().time() + timeout
    last: dict = {}  # type: ignore[type-arg]
    while asyncio.get_event_loop().time() < deadline:
        r = await client.get(f"/documents/{doc_id}")
        last = r.json()
        if last.get("status") in accept or last.get("status", "").startswith(
            "failed"
        ):
            return last
        await asyncio.sleep(0.1)
    return last


async def test_full_pipeline_md_report(app_and_client) -> None:  # type: ignore[no-untyped-def]
    app, client, factory = app_and_client

    # Health
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    # Inline ingest of fixture content (avoid multipart for simplicity)
    content = _FIXTURE.read_text(encoding="utf-8")
    r = await client.post(
        "/ingest/inline",
        json={"content": content, "mime_type": "text/markdown"},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    doc_id = body["document_id"]
    assert body["duplicate"] is False

    # Wait for orchestrator to finish
    state = await _wait_complete(client, doc_id)
    assert state["status"] in ("complete", "no_iocs"), state

    # Sample fixture has IOCs (IP/domain/sha256), so we expect "complete"
    assert state["status"] == "complete"
    assert state["chunk_count"] >= 1
    assert state["ioc_count"] >= 3
    assert state["stix_object_count"] >= 2  # report + at least 1 indicator

    # Extraction details
    r = await client.get(f"/extractions/{doc_id}")
    assert r.status_code == 200
    extraction = r.json()
    normalized = {i["normalized"] for i in extraction["iocs"]}
    assert "185.220.101.45" in normalized
    assert "evil.com" in normalized
    assert "45.33.32.156" in normalized
    assert "malicious.example.net" in normalized

    # STIX bundle
    r = await client.get(f"/stix/{doc_id}")
    assert r.status_code == 200
    bundle = r.json()
    assert bundle["type"] == "bundle"
    assert any(o["type"] == "indicator" for o in bundle["objects"])
    assert any(o["type"] == "report" for o in bundle["objects"])

    # /stix/validate against the produced bundle
    r = await client.post("/stix/validate", json={"bundle": bundle})
    assert r.status_code == 200
    val = r.json()
    assert val["is_valid"] is True

    # Audit chain integrity
    async with factory() as session:
        ok, count = await verify_chain(session)
    assert ok is True
    assert count >= 5

    # Idempotent re-ingest
    r2 = await client.post(
        "/ingest/inline",
        json={"content": content, "mime_type": "text/markdown"},
    )
    assert r2.status_code == 202
    body2 = r2.json()
    assert body2["document_id"] == doc_id
    assert body2["duplicate"] is True


async def test_unsupported_mime_returns_problem_json(app_and_client) -> None:  # type: ignore[no-untyped-def]
    _, client, _ = app_and_client
    r = await client.post(
        "/ingest",
        files={"file": ("payload.zip", b"PK\x03\x04bad", "application/zip")},
    )
    assert r.status_code == 415
    assert "application/problem+json" in r.headers["content-type"]
    body = r.json()
    assert body["error_code"] == "UnsupportedFormatError"


async def test_unknown_document_returns_404_problem(app_and_client) -> None:  # type: ignore[no-untyped-def]
    _, client, _ = app_and_client
    r = await client.get("/documents/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
    body = r.json()
    assert body["error_code"] == "HTTPException"
