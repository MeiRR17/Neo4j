#!/usr/bin/env python3
"""Offline integrity verification for a bounded v0.9.11 Research API export.

Requires the local protected Research API token file. Verifies HMAC and
schema without connecting to Neo4j. Does NOT establish a historical
corpus snapshot, a research license, or independent reviewer approval.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.research_api.audit_export_v0911 import (
    MAX_BYTES, verify_audit_export,
)
from services.research_api.config import TOKEN_PATH, load_token
from services.research_api.db import DatabaseUnavailable


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--token-path", type=Path, default=TOKEN_PATH)
    args = parser.parse_args(argv)
    try:
        if args.input.is_symlink() or not args.input.is_file():
            raise ValueError("Invalid export input path.")
        if args.input.stat().st_size > MAX_BYTES + 2048:
            raise ValueError("Export envelope exceeds size budget.")
        raw = args.input.read_bytes()
        if len(raw) > MAX_BYTES + 2048:
            raise ValueError("Export envelope exceeds size budget.")
        envelope = json.loads(raw.decode("utf-8"))
        result = verify_audit_export(
            envelope, secret=load_token(args.token_path),
        )
    except (ValueError, TypeError, UnicodeError, OSError,
            DatabaseUnavailable):
        print("[FAIL] Audit export integrity or local key verification failed.",
              file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
