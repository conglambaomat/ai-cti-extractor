# Demo runner — start API + run sample ingest end-to-end (no Docker, no LLM)
# Run from repo root: bash scripts/demo.sh

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# All settings inline — no .env needed
export APP_ENV=development
export DATABASE_URL="sqlite+aiosqlite:///data/cti.db"
export STORAGE_BACKEND=local
export STORAGE_LOCAL_DIR="$REPO_ROOT/data/storage"
export JOB_QUEUE_BACKEND=background_tasks
export MAX_CONCURRENT_PIPELINES=3
export TRUST_PROXY_HEADERS=false
export DEBUG=true
export LOG_LEVEL=INFO
export ALLOW_EXTERNAL_LLM=false
export REDACT_BEFORE_LLM=true
export SECRET_KEY="demo-key-only-not-for-production-use-32"

mkdir -p "$REPO_ROOT/data/storage"

PYTHON=".venv/Scripts/python.exe"
[ -x "$PYTHON" ] || PYTHON=".venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="python"

# Bootstrap SQLite schema if DB doesn't exist
if [ ! -f "$REPO_ROOT/data/cti.db" ]; then
    echo "[demo] Bootstrapping SQLite schema at data/cti.db"
    "$PYTHON" -c "
import asyncio
from app.db.session import _build_engine
from app.db.models import Base
async def init():
    eng = _build_engine()
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    await eng.dispose()
asyncio.run(init())
"
fi

echo "[demo] Booting FastAPI on http://127.0.0.1:8000"
echo "[demo] Open http://127.0.0.1:8000/docs for Swagger UI"
echo "[demo] In another shell: $PYTHON scripts/demo_client.py"
echo "[demo] Press Ctrl+C to stop"

exec "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
