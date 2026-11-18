#!/usr/bin/env python3
"""Build or verify a signed cross-page private review handoff.

Provide six FILTER=PATH --coverage receipts and all original ordered
FILTER=PATH --page files, the signed v0.10.8 --matrix, --queue, ordered
--packet captures and 1–12 sorted --ids. No live API, graph or DvirOS writes.
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
from scripts.study_review_matrix_v0108 import _named_paths
from services.research_api.config import TOKEN_PATH, load_token
from services.research_api.study_review_matrix_v0108 import FILTER_ORDER
from services.research_api.study_review_coverage_v0107 import MAX_PAGES
from services.research_api.study_review_bundle_v0109 import (
    build_cross_page_review_bundle, verify_cross_page_review_bundle,
)
from services.research_api.study_timeline_v0103 import MIN_CAPTURES, MAX_CAPTURES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "verify"))
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--packet", type=Path, action="append", required=True)
    parser.add_argument("--coverage", action="append", required=True)
    parser.add_argument("--page", action="append", required=True)
    parser.add_argument("--ids", required=True)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--token-path", type=Path, default=TOKEN_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if (
        not MIN_CAPTURES <= len(args.packet) <= MAX_CAPTURES
        or len(args.coverage) != len(FILTER_ORDER)
        or not 6 <= len(args.page) <= 6 * MAX_PAGES
        or (args.action == "build" and (args.output is None or args.report))
        or (args.action == "verify" and (args.report is None or args.output))
    ):
        parser.error(
            "Need 2–6 ordered packets, six complete filter views and "
            "build --output / verify --report."
        )
    try:
        coverage_paths = _named_paths(args.coverage, unique=True)
        page_paths = _named_paths(args.page, unique=False)
        queue = _read(args.queue)
        matrix = _read(args.matrix)
        previews = [_read(p) for p in args.packet]
        coverages = {
            name: _read(coverage_paths[name][0]) for name in FILTER_ORDER
        }
        pages = {
            name: [_read(p) for p in page_paths[name]]
            for name in FILTER_ORDER
        }
        secret = load_token(args.token_path)
        options = {
            "secret": secret,
            "evidence_ids": args.ids,
            "limit": args.limit,
        }
        if args.action == "build":
            receipt = build_cross_page_review_bundle(
                matrix, queue, previews, coverages, pages, **options,
            )
            result = verify_cross_page_review_bundle(
                receipt, matrix, queue, previews, coverages, pages, **options,
            )
            raw = json.dumps(
                receipt, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            _save_private(args.output, raw)
        else:
            receipt = _read(args.report)
            result = verify_cross_page_review_bundle(
                receipt, matrix, queue, previews, coverages, pages, **options,
            )
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (ValueError, TypeError, KeyError, OSError, RuntimeError):
        print(
            "[FAIL] Signed cross-page review handoff rejected.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
