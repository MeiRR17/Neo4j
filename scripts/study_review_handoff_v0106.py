#!/usr/bin/env python3
"""Create or verify a signed, private Evidence review handoff draft.

Requires the original signed review page, its queue, and all 2–6 complete
source preview packets. --ids contains 1–12 sorted canonical Evidence IDs
that appear ON THE REQUESTED PAGE; it cannot select off-page candidates.
No reviewer identity, saved notes, decision or graph mutation is created.
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
from services.research_api.study_review_handoff_v0106 import (
    build_review_handoff, verify_review_handoff,
)
from services.research_api.study_review_pages_v0105 import FILTERS
from services.research_api.study_timeline_v0103 import (
    MIN_CAPTURES, MAX_CAPTURES,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "verify"))
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--page", type=Path, required=True)
    parser.add_argument("--packet", type=Path, action="append", required=True)
    parser.add_argument("--ids", required=True)
    parser.add_argument("--filter", choices=sorted(FILTERS), default="all")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--cursor")
    parser.add_argument("--token-path", type=Path, default=TOKEN_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if (
        not MIN_CAPTURES <= len(args.packet) <= MAX_CAPTURES
        or (args.action == "build" and (args.output is None or args.report))
        or (args.action == "verify" and (args.report is None or args.output))
    ):
        parser.error(
            "Need 2–6 ordered --packet files and build --output / verify --report."
        )
    try:
        queue = _read(args.queue)
        page = _read(args.page)
        previews = [_read(p) for p in args.packet]
        secret = load_token(args.token_path)
        options = {
            "secret": secret, "evidence_ids": args.ids,
            "reason_filter": args.filter, "limit": args.limit,
            "cursor": args.cursor,
        }
        if args.action == "build":
            handoff = build_review_handoff(
                page, queue, previews, **options,
            )
            result = verify_review_handoff(
                handoff, page, queue, previews, **options,
            )
            raw = json.dumps(
                handoff, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            _save_private(args.output, raw)
        else:
            handoff = _read(args.report)
            result = verify_review_handoff(
                handoff, page, queue, previews, **options,
            )
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (ValueError, TypeError, KeyError, OSError, RuntimeError):
        print("[FAIL] Private signed review handoff rejected.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
