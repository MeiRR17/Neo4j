#!/usr/bin/env python3
"""Generate or validate a private bearer token without printing credentials."""
from __future__ import annotations
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.research_api.config import bootstrap_token

if __name__ == "__main__":
    try:
        bootstrap_token()
    except (OSError, ValueError) as exc:
        print(f"[BLOCKED] Research API secret: {exc}")
        raise SystemExit(1)
    print("[OK] Local research API token validated; secret value not displayed.")
