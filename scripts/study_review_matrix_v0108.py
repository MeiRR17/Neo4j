#!/usr/bin/env python3
"""Build or replay a private, signed six-filter Evidence triage matrix.

Provide six --coverage FILTER=private.json receipts and the original ordered
--page FILTER=private.json pages for each filter, along with the queue and
2–6 capture packets. Files remain local/owner-only; no Neo4j or DvirOS writes.
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
from services.research_api.study_review_matrix_v0108 import (
    FILTER_ORDER, build_review_triage_matrix, verify_review_triage_matrix,
)
from services.research_api.study_review_coverage_v0107 import MAX_PAGES
from services.research_api.study_timeline_v0103 import MIN_CAPTURES, MAX_CAPTURES


def _named_paths(specifications: list[str], *, unique: bool) -> dict[str, list[Path]]:
    """Require explicit known filter labels; never silently replace a view."""
    found: dict[str, list[Path]] = {}
    for entry in specifications:
        if type(entry) is not str or "=" not in entry:
            raise ValueError("Named filter path missing.")
        name, value = entry.split("=", 1)
        if name not in FILTER_ORDER or not value:
            raise ValueError("Unknown or empty filter path.")
        if unique and name in found:
            raise ValueError("Duplicate filter coverage receipt.")
        found.setdefault(name, []).append(Path(value))
        if len(found[name]) > (1 if unique else MAX_PAGES):
            raise ValueError("Too many pages per review filter.")
    if set(found) != set(FILTER_ORDER):
        raise ValueError("Exactly six review filters are required.")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "verify"))
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--packet", type=Path, action="append", required=True)
    parser.add_argument(
        "--coverage", action="append", required=True, metavar="FILTER=PATH",
    )
    parser.add_argument(
        "--page", action="append", required=True, metavar="FILTER=PATH",
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--token-path", type=Path, default=TOKEN_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if (
        not MIN_CAPTURES <= len(args.packet) <= MAX_CAPTURES
        or not 6 <= len(args.page) <= 6 * MAX_PAGES
        or len(args.coverage) != len(FILTER_ORDER)
        or (args.action == "build" and (args.output is None or args.report))
        or (args.action == "verify" and (args.report is None or args.output))
    ):
        parser.error(
            "Require 2–6 packets, six coverages, all ordered filter pages "
            "and build --output / verify --report."
        )
    try:
        receipt_paths = _named_paths(args.coverage, unique=True)
        page_paths = _named_paths(args.page, unique=False)
        queue = _read(args.queue)
        previews = [_read(path) for path in args.packet]
        coverages = {
            name: _read(receipt_paths[name][0]) for name in FILTER_ORDER
        }
        pages = {
            name: [_read(path) for path in page_paths[name]]
            for name in FILTER_ORDER
        }
        secret = load_token(args.token_path)
        if args.action == "build":
            value = build_review_triage_matrix(
                queue, previews, coverages, pages,
                secret=secret, limit=args.limit,
            )
            summary = verify_review_triage_matrix(
                value, queue, previews, coverages, pages,
                secret=secret, limit=args.limit,
            )
            output = json.dumps(
                value, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            _save_private(args.output, output)
        else:
            value = _read(args.report)
            summary = verify_review_triage_matrix(
                value, queue, previews, coverages, pages,
                secret=secret, limit=args.limit,
            )
        print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
        return 0
    except (OSError, KeyError, ValueError, TypeError, RuntimeError):
        print(
            "[FAIL] Private six-filter review matrix rejected.", file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
