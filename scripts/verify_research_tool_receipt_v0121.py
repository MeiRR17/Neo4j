#!/usr/bin/env python3
"""Offline verification of a private v0.12.1 signed read-only tool run.

A private JSON file returned by /v1/research/agent-tools/execute/signed
is verified against the local service token. No Neo4j, LLM or network calls.
The token itself is never printed. A valid HMAC is a service-key assertion,
NOT proof of a scholarly reviewer, source rights or graph immutability.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_study_packet_v0100 import _read
from services.research_api.config import TOKEN_PATH, load_token
from services.research_api.research_tool_receipt_v0121 import (
    verify_signed_research_tool_run,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--token-path", type=Path, default=TOKEN_PATH)
    args = parser.parse_args(argv)
    try:
        report = _read(args.report)
        secret = load_token(args.token_path)
        result = verify_signed_research_tool_run(report, secret=secret)
        # Aggregate fields only: no query content, source refs, Evidence IDs,
        # tokens, confidential notes or research text on standard output.
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        print(
            "[FAIL] Private signed research tool receipt rejected.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
