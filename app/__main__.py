"""Module entry: ``python -m app`` — prints diagnostic info.

Phase 1 placeholder. Phase 7 will mount the FastAPI server here when invoked
without args, and route to subcommands (e.g. ``python -m app worker``).
"""

from __future__ import annotations

import platform
import sys

from app import __version__


def main() -> int:
    print(f"ai-cti-extractor {__version__}")
    print(f"python {sys.version.split()[0]} on {platform.system()} {platform.release()}")
    print("Phase 1 placeholder — see plans/260518-2338-phase-01-ingestion-ioc-stix/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
