# Demo: AI-Assisted CTI Extractor

End-to-end demo of Phase 02-07 modules. **No Docker, no LLM, no external services.** SQLite + local filesystem only.

## Prerequisites

- Python 3.11+ in `.venv/` (already set up — `.venv/Scripts/python.exe` on Windows, `.venv/bin/python` on Unix)
- Repo at clean `feat/phase-07-api-pipeline` HEAD

## Run the demo

### Terminal 1 — start the API

```bash
bash scripts/demo.sh
```

This will:
1. Create `data/storage/` if missing
2. Bootstrap SQLite schema in `data/cti.db` on first run
3. Start FastAPI on http://127.0.0.1:8000 with auto-reload
4. Print Swagger UI URL: http://127.0.0.1:8000/docs

### Terminal 2 — run the client

```bash
.venv/Scripts/python.exe scripts/demo_client.py
```

Or with a custom file:

```bash
.venv/Scripts/python.exe scripts/demo_client.py path/to/your/report.md
```

## Expected output

```
[demo] /health -> {'status': 'ok', 'env': 'development', 'version': '0.1.0'}
[demo] POST /ingest/inline (557 chars, text/markdown)
[demo]   document_id=<uuid> duplicate=False
[demo] /documents/<uuid> -> status=complete chunks=3 iocs=7 stix_objects=7
[demo] /extractions/<uuid>: 7 IOCs
  - cve      CVE-2024-12345
  - domain   evil.com
  - domain   malicious.example.net
  - ipv4     185.220.101.45
  - ipv4     45.33.32.156
  - sha256   3a7bd3e2360a3f83e0c6f1f01b4fdd7f4f8c9e8a5d4f3b2a1c0d9e8f7a6b5c4d
  - url      https://evil.com/payload.exe
[demo] /stix/<uuid>: bundle id=bundle--<uuid> 7 objects
  types: ['indicator', 'report']
```

## API surface (Phase 07)

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness probe |
| POST | `/ingest` (multipart) | Upload a report file |
| POST | `/ingest/url` | Fetch a URL |
| POST | `/ingest/inline` | Inline JSON content |
| GET | `/documents/{id}` | Document state + counts |
| GET | `/documents/{id}/chunks` | All chunks for a document |
| POST | `/documents/{id}/extract` | Re-trigger extraction |
| GET | `/extractions/{id}` | All IOCs for a document |
| GET | `/stix/{id}` | STIX 2.1 bundle |
| POST | `/stix/validate` | Validate any bundle (parse + semantic) |

All errors are RFC 7807 `application/problem+json`. Every response carries `X-Correlation-Id`.

## Reset state

```bash
rm -f data/cti.db data/cti.db-shm data/cti.db-wal
rm -rf data/storage/*
```

Re-run `scripts/demo.sh` to rebootstrap.

## What runs

- **Phase 02**: SQLite via aiosqlite, structlog JSON logs, redaction, audit hash chain
- **Phase 03**: PDF/HTML/MD/TXT/URL parsers + chunker + English-only language gate
- **Phase 04**: Pydantic schemas with evidence-closure invariants
- **Phase 05**: Regex IOC extractor with defang/refang offset preservation (11 IOC types, IANA TLD whitelist)
- **Phase 06**: STIX 2.1 builder (deterministic UUIDv5 IDs) + 4-layer validation
- **Phase 07**: FastAPI app + BackgroundTasks pipeline orchestrator

## What's NOT in the demo

- No LLM calls (Phase 09+; needs API key)
- No NER/RE encoders (Phase 10+; needs SecureBERT model download)
- No ATT&CK mapping (Phase 09+; needs MITRE bundle + retrieval index)
- No OpenCTI/MISP/TAXII export (Phase 08+)
- No analyst review UI (Phase 12+)

## Troubleshooting

- **`NOT NULL constraint failed: audit_logs.id`** — stale DB schema. Run `rm -f data/cti.db` and re-run `scripts/demo.sh`.
- **`address already in use`** — port 8000 occupied. Kill the previous uvicorn or change `--port`.
- **Connection refused on demo_client.py** — wait 2-3 seconds after starting `demo.sh` for uvicorn to bind.
