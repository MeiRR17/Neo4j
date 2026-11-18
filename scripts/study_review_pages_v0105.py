#!/usr/bin/env python3
"""Create or independently verify private, signed review queue pages.

The queue and 2–6 v0.10.0 study preview packets must be private regular
files. An opaque cursor is bound to the queue, filter and page size.
No database/network access, reviewer decisions, or source-text export.
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
from services.research_api.study_review_pages_v0105 import (
    FILTERS, page_review_candidates, verify_review_page,
)
from services.research_api.study_timeline_v0103 import (
    MIN_CAPTURES, MAX_CAPTURES,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("page", "verify"))
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--packet", type=Path, action="append", required=True)
    parser.add_argument("--token-path", type=Path, default=TOKEN_PATH)
    parser.add_argument("--filter", choices=sorted(FILTERS), default="all")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--cursor")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if (
        not MIN_CAPTURES <= len(args.packet) <= MAX_CAPTURES
        or (args.action == "page" and (args.output is None or args.report))
        or (args.action == "verify" and (args.report is None or args.output))
    ):
        parser.error(
            "Need 2–6 --packet inputs and action-specific --output/--report."
        )
    try:
        source_queue = _read(args.queue)
        previews = [_read(path) for path in args.packet]
        secret = load_token(args.token_path)
        opts = {
            "secret": secret,
            "reason_filter": args.filter,
            "limit": args.limit,
            "cursor": args.cursor,
        }
        if args.action == "page":
            page = page_review_candidates(source_queue, previews, **opts)
            verified = verify_review_page(
                page, source_queue, previews, **opts,
            )
            data = json.dumps(
                page, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            _save_private(args.output, data)
        else:
            page = _read(args.report)
            verified = verify_review_page(
                page, source_queue, previews, **opts,
            )
        # Cursor is an opaque metadata token; never print the local secret.
        summary = {
            **verified,
            "reason_filter": args.filter,
            "next_cursor": page["page"]["next_cursor"],
        }
        print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
        return 0
    except (ValueError, TypeError, KeyError, RuntimeError, OSError):
        print(
            "[FAIL] Signed review page invalid or private output refused.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
