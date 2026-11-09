#!/usr/bin/env python3
"""Discover Sefaria editions, validate human rights review, report seed QA.

All network and graph writes are explicit opt-in operations. Dry discovery
does not download any text, and only approved *metadata* may reach Neo4j.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingestion.seed_catalog import (  # noqa: E402
    DEFAULT_CATALOG, build_inventory, load_catalog, request_versions,
    write_immutable_json,
)
from ingestion.seed_quality import (  # noqa: E402
    make_review_queue, quality_report, read_jsonl, verify_inventory,
)
from ingestion.seed_apply import apply_approved_editions  # noqa: E402
from ingestion.graph_apply import load_verified_plan  # noqa: E402
from scripts.bootstrap import DEFAULT_SECRET_PATH  # noqa: E402
from scripts.migrate import LocalQueryClient  # noqa: E402


def run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    discover = sub.add_parser("discover", help="Fetch metadata of candidate editions (no text).")
    discover.add_argument("--live", action="store_true", required=False)
    discover.add_argument("--offline-snapshots", type=Path)
    discover.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    discover.add_argument("--output", type=Path, required=True)

    queue = sub.add_parser("review-queue", help="Sample unreviewed real links for human adjudication.")
    queue.add_argument("--stage", type=Path, required=True)
    queue.add_argument("--output", type=Path, required=True)
    queue.add_argument("--sample-size", type=int, default=120)
    queue.add_argument("--ci-fixture", action="store_true")

    audit = sub.add_parser("audit", help="Fail-closed research seed readiness and quality report.")
    audit.add_argument("--inventory", type=Path, required=True)
    audit.add_argument("--rights", type=Path, required=True)
    audit.add_argument("--review-queue", type=Path, required=True)
    audit.add_argument("--evidence-reviews", type=Path, required=True)
    audit.add_argument("--stage", type=Path, required=True)
    audit.add_argument("--output", type=Path, required=True)
    audit.add_argument("--ci-fixture", action="store_true")

    apply = sub.add_parser("apply-editions", help="Write only human-reviewed metadata to Neo4j.")
    apply.add_argument("--inventory", type=Path, required=True)
    apply.add_argument("--rights", type=Path, required=True)
    apply.add_argument("--secret", type=Path, default=DEFAULT_SECRET_PATH)
    apply.add_argument("--ack-reviewed-metadata-only", action="store_true")
    apply.add_argument("--ci-fixture", action="store_true")

    args = parser.parse_args()
    try:
        if args.action == "discover":
            catalog = load_catalog(args.catalog)
            if args.offline_snapshots:
                if args.live:
                    raise ValueError("Choose offline snapshots OR --live, not both.")
                snapshots = json.loads(args.offline_snapshots.read_text(encoding="utf-8"))
                if not isinstance(snapshots, dict):
                    raise ValueError("Offline snapshots must be a JSON mapping index names to version lists.")
            elif args.live:
                snapshots = {}
                for index, entry in enumerate(catalog):
                    title = entry["index_title"]
                    try:
                        snapshots[title] = request_versions(title)
                    except ValueError as exc:
                        print(f"[PENDING] {title}: {exc}")
                    if index != len(catalog) - 1:
                        time.sleep(0.3)
            else:
                raise ValueError("Discovery requires --live or --offline-snapshots.")
            inventory = build_inventory(catalog, snapshots)
            write_immutable_json(args.output, inventory)
            print(f"[OK] Metadata-only inventory: {len(inventory['editions'])} discovered editions; "
                  f"{len(inventory['unavailable'])} unresolved candidates. All rights pending.")
            return 0

        if args.action == "review-queue":
            manifest, links = load_verified_plan(args.stage, allow_fixture=args.ci_fixture)
            review = make_review_queue(
                links, sample_size=args.sample_size, fixture=manifest["fixture_only"]
            )
            write_immutable_json(args.output, review)
            print(f"[OK] Queue: {review['selected_count']} evidence items; "
                  "all still pending human review.")
            return 0

        if args.action == "audit":
            inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
            queue = json.loads(args.review_queue.read_text(encoding="utf-8"))
            _, links = load_verified_plan(args.stage, allow_fixture=args.ci_fixture)
            report = quality_report(
                inventory, read_jsonl(args.rights), queue,
                read_jsonl(args.evidence_reviews), links,
            )
            write_immutable_json(args.output, report)
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            return 0 if report["status"] == "AWAITING_HUMAN_RELEASE_SIGNOFF" else 2

        if args.action == "apply-editions":
            if not args.ack_reviewed_metadata_only:
                raise ValueError("Explicit --ack-reviewed-metadata-only required.")
            inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
            client = LocalQueryClient("http://127.0.0.1:7474", args.secret)
            total = apply_approved_editions(
                inventory, read_jsonl(args.rights), client,
                fixture=args.ci_fixture,
            )
            print(f"[OK] {total} human-reviewed metadata-only editions imported; no book text.")
            return 0
        raise ValueError("Unsupported action.")
    except (ValueError, RuntimeError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"[BLOCKED] v0.4 scholarly seed workflow: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
