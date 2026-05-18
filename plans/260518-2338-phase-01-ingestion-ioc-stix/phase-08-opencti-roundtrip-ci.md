---
phase: 8
title: "OpenCTI dev compose + round-trip test + CI integration"
status: pending
priority: P1
effort: "3d"
dependencies: [06, 07]
file_ownership:
  create:
    - docker/opencti/docker-compose.opencti.yml
    - docker/opencti/.env.opencti.example
    - docker/opencti/README.md
    - app/integrations/__init__.py
    - app/integrations/opencti/__init__.py
    - app/integrations/opencti/client.py
    - app/integrations/opencti/exporter.py
    - app/integrations/opencti/poller.py
    - app/api/routers/export.py
    - tests/integration/test_opencti_roundtrip.py
    - tests/fixtures/reports/sample-canonical-mandiant.pdf
    - .github/workflows/ci.yml
    - scripts/setup-opencti-token.sh
    - scripts/eval-phase1.sh
---

# Phase 08 — OpenCTI dev compose + round-trip test + CI

## Overview

Final Phase 1 piece: stand up a minimal OpenCTI dev stack, ship the OpenCTI exporter (`pycti`-based), implement the round-trip integration test that proves "ingest a real CTI report → produce STIX bundle → push into OpenCTI → query back equivalent". Wire CI to run the unit + property suite on every push, and to run the heavier integration test on a labeled PR or nightly schedule (don't burn CI minutes on every commit).

This phase is the Phase 1 acceptance gate. If round-trip passes on a real Mandiant or Talos PDF, the foundation is sound.

## Requirements

### Functional
- `docker compose -f docker/opencti/docker-compose.opencti.yml up -d` brings up OpenCTI + minimal deps (redis, ES, MinIO, RabbitMQ, opencti, worker)
- `OpenCTIExporter.push(bundle) -> ExportResult` submits via `pycti.OpenCTIApiClient.stix2.import_bundle_from_json`
- `wait_for_report(stix_id, timeout=30s)` polls until OpenCTI worker indexes the report
- `roundtrip_compare(local_bundle, opencti_response) -> RoundtripResult` asserts whitelist of fields equal: `(name, published, set(object_refs))`
- `POST /export/opencti` triggers exporter on a completed extraction
- CI: lint + types + security + unit tests on every push (already from Phase 1)
- CI: integration tests (incl. round-trip) on PR labeled `integration` OR nightly cron

### Non-functional
- OpenCTI compose ready in ≤ 5 min on first boot (cold pull); ≤ 30 s warm
- Round-trip test E2E ≤ 90 s (incl. ingest + worker poll)
- Exporter retries on transient 5xx (3 attempts, exponential backoff)
- Integration test isolated from main test suite (separate marker `integration_opencti`)

## Architecture

### OpenCTI compose (`docker/opencti/docker-compose.opencti.yml`)

Minimal services:
- `redis:7-alpine`
- `elasticsearch:8.x` (single-node, security disabled for dev)
- `minio/minio:latest`
- `rabbitmq:3-management`
- `opencti/platform:6.4.x`
- `opencti/worker:6.4.x` (one replica)

Skip all `connector-*` services. Override admin email/password via `.env.opencti` (gitignored). Network `opencti-net`. Healthchecks per service. Persistent volumes named `opencti_*`.

Token retrieval: after first boot, `scripts/setup-opencti-token.sh` logs in via the GraphQL `login` mutation with admin creds, extracts API token, writes to `.env` as `OPENCTI_TOKEN`. (Idempotent: if token exists, skip.)

### Exporter (`app/integrations/opencti/exporter.py`)

```python
class OpenCTIExporter:
    def __init__(self, client: OpenCTIApiClient):
        self._client = client

    def push(self, bundle: stix2.v21.Bundle, *, update: bool = True) -> ExportResult:
        bundle_json = bundle.serialize()
        attempt = 0
        while True:
            try:
                self._client.stix2.import_bundle_from_json(
                    json_data=bundle_json, update=update, types=None,
                )
                return ExportResult(status="submitted", bundle_hash=bundle_hash(bundle))
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                attempt += 1
                if attempt >= 3:
                    raise OpenCTIError(f"import failed after 3 attempts: {e}") from e
                time.sleep(1 << attempt)  # 2s, 4s, 8s
```

### Poller (`app/integrations/opencti/poller.py`)

```python
def wait_for_report(client: OpenCTIApiClient, stix_id: str, timeout: float = 30) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    delay = 0.5
    while time.monotonic() < deadline:
        try:
            obj = client.report.read(id=stix_id)
            if obj is not None:
                return obj
        except Exception:
            pass
        time.sleep(delay)
        delay = min(delay * 1.5, 4.0)
    raise OpenCTIError(f"report {stix_id} not visible after {timeout}s")
```

### Round-trip compare

```python
def roundtrip_compare(local: stix2.v21.Bundle, remote_report: dict) -> RoundtripResult:
    local_report = next(o for o in local.objects if o.type == "report")
    expected_refs = set(local_report.object_refs)
    actual_refs = {ref["standard_id"] if isinstance(ref, dict) else ref
                   for ref in remote_report.get("objectsIds", [])}

    return RoundtripResult(
        name_match=local_report.name == remote_report["name"],
        published_match=_eq_iso8601(local_report.published, remote_report["published"]),
        object_refs_match=expected_refs == actual_refs,
        missing_refs=list(expected_refs - actual_refs),
        extra_refs=list(actual_refs - expected_refs),
    )
```

Whitelist comparison only; we explicitly tolerate OpenCTI normalization (timestamps, score field, id reordering).

### Export endpoint

```python
# app/api/routers/export.py
@router.post("/opencti/{document_id}")
async def export_to_opencti(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    exporter: OpenCTIExporter = Depends(get_opencti_exporter),
) -> ExportResponse:
    bundle = stix_repo.load_bundle_for_document(db, document_id)
    if bundle is None:
        raise HTTPException(404, "no bundle for document")
    result = exporter.push(bundle)
    await audit_repo.append(actor="api", action="export.opencti", target_type="document",
                            target_id=document_id, payload={"bundle_hash": result.bundle_hash})
    return ExportResponse(status=result.status, bundle_hash=result.bundle_hash)
```

### CI (`.github/workflows/ci.yml`)

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
  schedule:
    - cron: "0 18 * * *"  # 18:00 UTC = 01:00 ICT, off-peak

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --frozen
      - run: uv run ruff check app tests
      - run: uv run ruff format --check app tests
      - run: uv run mypy app
      - run: uv run bandit -r app
      - run: uv run pip-audit
      - run: uv run pytest -m "not integration_opencti"

  integration-opencti:
    if: contains(github.event.pull_request.labels.*.name, 'integration') || github.event_name == 'schedule'
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --frozen
      - run: docker compose -f docker/docker-compose.yml up -d
      - run: docker compose -f docker/opencti/docker-compose.opencti.yml up -d
      - run: bash scripts/setup-opencti-token.sh
      - run: uv run pytest -m integration_opencti
      - if: always()
        run: docker compose -f docker/opencti/docker-compose.opencti.yml logs --tail=200
```

## Implementation steps

1. Author `docker/opencti/docker-compose.opencti.yml` with minimal services.
2. Author `docker/opencti/.env.opencti.example` (admin email/password placeholders, secrets, ports).
3. Author `docker/opencti/README.md`: how to bring up, troubleshoot, common issues.
4. Author `scripts/setup-opencti-token.sh`: idempotent token setup via GraphQL.
5. Implement `app/integrations/opencti/client.py`: thin factory `make_opencti_client()` reading env.
6. Implement `app/integrations/opencti/exporter.py` per spec with retry.
7. Implement `app/integrations/opencti/poller.py` per spec.
8. Implement `app/api/routers/export.py` and wire into FastAPI app.
9. Find a canonical Phase 1 fixture: pick a real Mandiant or Talos report (≥10 IOCs, multi-section, English). Save as `tests/fixtures/reports/sample-canonical-mandiant.pdf`. Document license/attribution in README.
10. Write `tests/integration/test_opencti_roundtrip.py`:
    - Spin up OpenCTI compose (pytest fixture, session-scoped)
    - Ingest canonical fixture via `POST /ingest`
    - Wait for extraction completion (poll `/documents/{id}`, max 60s)
    - POST `/export/opencti/{id}`
    - `wait_for_report(stix_id)`
    - Assert `roundtrip_compare(...)` `name_match=True, published_match=True, object_refs_match=True`
    - Mark with `@pytest.mark.integration_opencti`
11. Update `pyproject.toml` `[tool.pytest.ini_options]`:
    ```toml
    markers = [
      "integration_opencti: requires OpenCTI dev stack running",
    ]
    ```
12. Update `.github/workflows/ci.yml` per spec; gate integration job on label/cron.
13. Author `scripts/eval-phase1.sh`: end-to-end smoke — ingest fixture, run pipeline, validate STIX, push to OpenCTI, compare. Used as Phase 1 demo.
14. Update `Makefile` with `make eval-phase1`.
15. Update `docs/codebase-summary.md` to reflect Phase 1 modules + status.
16. Bump `docs/project-roadmap.md` Phase 1 → `completed` with date when all checks green.
17. Run full Phase 1 acceptance: `make eval-phase1` end-to-end on a fresh checkout. Save log.
18. Commit: `feat(p08): OpenCTI compose + round-trip + CI`. Push. Open PR `Phase 1 → main`. Mark PR ready for review.
19. After PR merged, write Phase 1 completion journal: `docs/journals/2026-05-{date}-phase-01-complete.md`.

## Success criteria

- [ ] OpenCTI compose `up -d` healthy in ≤ 5 min cold
- [ ] `setup-opencti-token.sh` idempotent
- [ ] Canonical Mandiant fixture round-trips: name + published + object_refs match
- [ ] Round-trip test stable (20 consecutive runs without flake)
- [ ] CI quality job green on every push
- [ ] CI integration-opencti job green on `integration`-labeled PR
- [ ] `make eval-phase1` passes end-to-end on fresh laptop
- [ ] Phase 1 acceptance criteria from plan.md fully checked

## Risk assessment

| Risk | Mitigation |
|---|---|
| OpenCTI version skew between `pycti` and platform image | Pin both to `6.4.x`; document upgrade procedure |
| Worker async ingest causes flaky round-trip | Polling with backoff (max 30s); explicit `eventually_visible` helper; mark `xfail` if exceeded with diagnostic dump |
| Real Mandiant PDF license | Use a public Mandiant blog post export (CC-BY) or Talos blog (CC-BY); document attribution in `tests/fixtures/reports/README.md`; if unavailable, generate a synthetic CTI report with realistic structure |
| OpenCTI silently strips fields | Round-trip compare uses whitelist; missing fields logged but not fatal unless in whitelist |
| Token setup script breaks on OpenCTI version bump | Script tolerates schema variants (login mutation field renames); fallback: print manual UI instructions |
| CI integration job costs minutes | Gated on label / nightly cron; not on every push; max 30 min timeout |
| Disk usage from Elasticsearch volume | Bind mount with size limit on CI runner; periodic cleanup script |
