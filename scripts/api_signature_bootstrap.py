#!/usr/bin/env python3
"""Provision a local HMAC key without exposing it in stdout or source."""
from __future__ import annotations

from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.research_api.signature import bootstrap_signature_key

if __name__ == "__main__":
    try:
        bootstrap_signature_key()
        print("[OK] DvirOS HMAC key provisioned; secret value not printed.")
    except (ValueError, OSError) as exc:
        print(f"[BLOCKED] Signature key setup: {exc}")
        raise SystemExit(1)
