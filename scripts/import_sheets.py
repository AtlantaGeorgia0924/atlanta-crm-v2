#!/usr/bin/env python3
"""Incremental Google Sheets -> Supabase sync wrapper.

This script delegates to the hardened backend sync pipeline which provides:
- incremental upsert by legacy_source_id
- phone-first client deduplication
- placeholder row filtering
- malformed date handling with warnings
- sync error logging
- retry logic for transient failures
- GOOGLE_SERVICE_ACCOUNT_JSON path/raw JSON/base64 support
"""

from __future__ import annotations

import json
import logging
import os
import sys

from dotenv import load_dotenv


ROOT = os.path.join(os.path.dirname(__file__), "..")
BACKEND_DIR = os.path.join(ROOT, "backend")
sys.path.insert(0, BACKEND_DIR)

load_dotenv(os.path.join(BACKEND_DIR, ".env"))

from app.db.supabase_client import get_supabase  # noqa: E402
from app.core.metrics_refresh import recompute_and_persist_metrics  # noqa: E402
from app.core.service_normalization import normalize_service_jobs_data  # noqa: E402
from app.core.sheets_import_sync import import_google_sheets_to_supabase  # noqa: E402


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("import_sheets")


def main() -> int:
    logger.info("Starting incremental Google Sheets import")
    sb = get_supabase()

    try:
        import_result = import_google_sheets_to_supabase(sb)
        normalization = normalize_service_jobs_data(sb)
        metrics = recompute_and_persist_metrics(sb, source="script_import_google_sheets")
    except Exception as exc:
        logger.exception("Incremental import failed")
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1

    payload = {
        "ok": True,
        "import": import_result,
        "normalization": normalization,
        "metrics": metrics,
    }
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
