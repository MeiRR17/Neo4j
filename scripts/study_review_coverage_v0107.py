#!/usr/bin/env python3
"""Build/verify a private signed full-coverage receipt for review inbox pages.

Provide 2–6 complete source --packet files, the signed --queue, and every
signed --page in exact keyset order, including the final page with no cursor.
No network, DB writes, user decisions or source text are exported.
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
from services.research_api.study_review_coverage_v0107 import (
    MAX_PAGES, build_review_inbox_coverage, verify_review_inbox_coverage,
)
from services.research_api.study_review_pages_v0105 import FILTERS
from services.research_api.study_timeline_v0103 import (
    MIN_CAPTURES, MAX_CAPTURES,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "verify"))
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--packet", type=Path, action="append", required=True)
    parser.add_argument("--page", type=Path, action="append", required=True)
    parser.add_argument("--filter", choices=sorted(FILTERS), default="all")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--token-path", type=Path, default=TOKEN_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if (
        not MIN_CAPTURES <= len(args.packet) <= MAX_CAPTURES
        or not 1 <= len(args.page) <= MAX_PAGES
        or (args.action == "build" and (args.output is None or args.report))
        or (args.action == "verify" and (args.report is None or args.output))
    ):
        parser.error(
            "Require 2–6 ordered --packet, 1–600 ordered --page and "
            "build --output / verify --report."
        )
    try:
        queue = _read(args.queue)
        previews = [_read(p) for p in args.packet]
        pages = [_read(p) for p in args.page]
        secret = load_token(args.token_path)
        options = {
            "secret": secret,
            "reason_filter": args.filter,
            "limit": args.limit,
        }
        if args.action == "build":
            value = build_review_inbox_coverage(
                queue, previews, pages, **options,
            )
            report = verify_review_inbox_coverage(
                value, queue, previews, pages, **options,
            )
            raw = json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")
            _save_private(args.output, raw)
        else:
            value = _read(args.report)
            report = verify_review_inbox_coverage(
                value, queue, previews, pages, **options,
            )
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        return 0
    except (OSError, KeyError, RuntimeError, ValueError, TypeError):
        print("[FAIL] Private signed review coverage rejected.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
