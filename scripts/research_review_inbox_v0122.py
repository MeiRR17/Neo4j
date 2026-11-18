#!/usr/bin/env python3
"""Build/verify one owner-only v0.12.2 signed Evidence review inbox offline.

Pass two to six original v0.12.1 signed-run JSON files. Each must be 0600
and must match the local research service secret. The output contains only
metadata, never source text, raw prompts, service keys or reviewer decisions.
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
from scripts.study_review_queue_v0104 import _save_private
from services.research_api.config import TOKEN_PATH, load_token
from services.research_api.research_review_inbox_v0122 import (
    MAX_RUNS, MIN_RUNS, build_research_review_inbox,
    verify_research_review_inbox,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "verify"))
    parser.add_argument("--run", action="append", type=Path, required=True)
    parser.add_argument("--token-path", type=Path, default=TOKEN_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if (
        not MIN_RUNS <= len(args.run) <= MAX_RUNS
        or len(set(args.run)) != len(args.run)
        or (args.action == "build" and (args.output is None or args.report))
        or (args.action == "verify" and (args.report is None or args.output))
    ):
        parser.error(
            "Require 2–6 different --run paths and build --output or verify --report."
        )
    try:
        runs = [_read(path) for path in args.run]
        secret = load_token(args.token_path)
        if args.action == "build":
            receipt = build_research_review_inbox(runs, secret=secret)
            result = verify_research_review_inbox(
                receipt, runs, secret=secret,
            )
            output = json.dumps(
                receipt, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            _save_private(args.output, output)
        else:
            receipt = _read(args.report)
            result = verify_research_review_inbox(
                receipt, runs, secret=secret,
            )
        # Aggregate-only stdout, no source refs, Evidence IDs or tokens.
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        print(
            "[FAIL] Private signed Evidence review inbox rejected.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
