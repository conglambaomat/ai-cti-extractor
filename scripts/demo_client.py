"""Demo client — POST sample CTI report, poll until complete, print results.

Usage:
    python scripts/demo_client.py                  # uses bundled fixture
    python scripts/demo_client.py path/to/file.md  # custom file
    python scripts/demo_client.py --url https://...

Assumes the API is running at http://127.0.0.1:8000 (start via scripts/demo.sh).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

BASE_URL = "http://127.0.0.1:8000"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "reports" / "sample_cti.md"


async def _wait_complete(client: httpx.AsyncClient, doc_id: str, *, timeout_s: float = 30.0) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout_s
    while True:
        r = await client.get(f"/documents/{doc_id}")
        r.raise_for_status()
        body = r.json()
        if body["status"] in ("complete", "no_iocs", "empty", "failed_parse", "failed"):
            return body
        if asyncio.get_event_loop().time() > deadline:
            raise TimeoutError(f"timeout; last status={body['status']}")
        await asyncio.sleep(0.25)


async def run(file_path: Path | None, url: str | None) -> int:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        # 1. Health
        r = await client.get("/health")
        r.raise_for_status()
        print(f"[demo] /health -> {r.json()}")

        # 2. Ingest
        if url:
            print(f"[demo] POST /ingest/url -> {url}")
            r = await client.post("/ingest/url", json={"url": url})
        else:
            assert file_path is not None
            content = file_path.read_text(encoding="utf-8")
            mime = "text/markdown" if file_path.suffix in {".md", ".markdown"} else "text/plain"
            print(f"[demo] POST /ingest/inline ({len(content)} chars, {mime})")
            r = await client.post(
                "/ingest/inline", json={"content": content, "mime_type": mime}
            )
        r.raise_for_status()
        body = r.json()
        doc_id = body["document_id"]
        print(f"[demo]   document_id={doc_id} duplicate={body['duplicate']}")

        # 3. Poll
        state = await _wait_complete(client, doc_id)
        print(
            f"[demo] /documents/{doc_id} -> status={state['status']} "
            f"chunks={state['chunk_count']} iocs={state['ioc_count']} "
            f"stix_objects={state['stix_object_count']}"
        )
        if state["status"] not in ("complete", "no_iocs"):
            print(f"[demo] FAILED — payload: {json.dumps(state, indent=2)}")
            return 1

        # 4. Extraction details
        r = await client.get(f"/extractions/{doc_id}")
        r.raise_for_status()
        ex = r.json()
        print(f"[demo] /extractions/{doc_id}: {len(ex['iocs'])} IOCs")
        for ioc in ex["iocs"][:10]:
            print(f"  - {ioc['type']:8s} {ioc['normalized']}  (conf {ioc['confidence']:.2f})")

        # 5. STIX bundle
        r = await client.get(f"/stix/{doc_id}")
        if r.status_code == 200:
            bundle = r.json()
            types = [o["type"] for o in bundle["objects"]]
            print(f"[demo] /stix/{doc_id}: bundle id={bundle['id']} {len(bundle['objects'])} objects")
            print(f"  types: {sorted(set(types))}")
        else:
            print(f"[demo] /stix/{doc_id}: status={r.status_code} body={r.text}")

        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", nargs="?", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--url", help="Ingest a URL instead of a local file")
    args = parser.parse_args()

    if args.url:
        return asyncio.run(run(file_path=None, url=args.url))
    if not args.file.exists():
        print(f"file not found: {args.file}")
        return 2
    return asyncio.run(run(file_path=args.file, url=None))


if __name__ == "__main__":
    sys.exit(main())
