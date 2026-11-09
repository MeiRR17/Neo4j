#!/usr/bin/env python3
"""Sefaria metadata v0.3: explicit bounded acquisition -> staging -> graph.

Offline plan:
  python scripts/ingest_sefaria.py plan-csv --input <csv> --source-uri <gcs-link> --output <dir>
Live opt-in:
  python scripts/ingest_sefaria.py fetch-shard --shard links0.csv --output <csv>
  python scripts/ingest_sefaria.py plan-api --title "..." --live --output <dir>
Apply (unreviewed metadata only, requires reviewed quarantines = 0):
  python scripts/ingest_sefaria.py apply --input <stage-dir> --ack-unreviewed
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingestion.acquire import api_url, fetch_api_links, fetch_gcs_shard  # noqa: E402
from ingestion.graph_apply import apply_metadata  # noqa: E402
from ingestion.sefaria_links import (  # noqa: E402
    api_links, csv_links, file_sha256, process_links,
)
from scripts.migrate import LocalQueryClient  # noqa: E402
from scripts.bootstrap import DEFAULT_SECRET_PATH  # noqa: E402


def curated_titles(path: Path) -> set[str]:
    content = json.loads(Path(path).read_text(encoding="utf-8"))
    titles = content["titles"]
    if not isinstance(titles, list) or not titles or any(not isinstance(t, str) for t in titles):
        raise ValueError("Title allowlist must be a nonempty array of strings.")
    if len(titles) > 50:
        raise ValueError("Too many curated titles.")
    return set(titles)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    csv_parser = sub.add_parser("plan-csv", help="Offline streaming CSV staging; default never writes DB.")
    csv_parser.add_argument("--input", type=Path, required=True)
    csv_parser.add_argument("--source-uri", required=True)
    csv_parser.add_argument("--output", type=Path, required=True)
    csv_parser.add_argument("--titles", type=Path, default=ROOT / "config/sefaria-philosophy-titles.json")
    csv_parser.add_argument("--max-quarantine", type=int, default=0)
    csv_parser.add_argument("--fixture", action="store_true", help="Synthetic test data; cannot be published.")

    api_parser = sub.add_parser("plan-api", help="Explicit live API metadata-only request.")
    api_parser.add_argument("--title", required=True)
    api_parser.add_argument("--output", type=Path, required=True)
    api_parser.add_argument("--titles", type=Path, default=ROOT / "config/sefaria-philosophy-titles.json")
    api_parser.add_argument("--max-quarantine", type=int, default=0)
    api_parser.add_argument("--live", action="store_true", help="Required opt-in for network access.")

    file_parser = sub.add_parser("plan-api-file", help="Replay previously acquired metadata JSON without network.")
    file_parser.add_argument("--input", type=Path, required=True)
    file_parser.add_argument("--title", required=True)
    file_parser.add_argument("--output", type=Path, required=True)
    file_parser.add_argument("--titles", type=Path, default=ROOT / "config/sefaria-philosophy-titles.json")
    file_parser.add_argument("--fixture", action="store_true")
    file_parser.add_argument("--max-quarantine", type=int, default=0)

    dl_parser = sub.add_parser("fetch-shard", help="Explicit bounded GCS link CSV download with ETag resume.")
    dl_parser.add_argument("--shard", required=True)
    dl_parser.add_argument("--output", type=Path, required=True)
    dl_parser.add_argument("--max-bytes", type=int, default=300_000_000)
    dl_parser.add_argument("--live", action="store_true")

    apply_parser = sub.add_parser("apply", help="Explicit local Neo4j metadata-only import.")
    apply_parser.add_argument("--input", type=Path, required=True)
    apply_parser.add_argument("--ack-unreviewed", action="store_true")
    apply_parser.add_argument("--ci-fixture", action="store_true",
                              help="Only for isolated CI with CI=true.")
    apply_parser.add_argument("--secret", type=Path, default=DEFAULT_SECRET_PATH)
    args = parser.parse_args()
    try:
        if args.command == "fetch-shard":
            if not args.live:
                raise ValueError("Live GCS fetch requires --live.")
            print(json.dumps(fetch_gcs_shard(args.shard, args.output, max_bytes=args.max_bytes), sort_keys=True))
            return 0
        if args.command == "apply":
            if not args.ack_unreviewed:
                raise ValueError("Apply requires explicit --ack-unreviewed; no source text/rights promoted.")
            count = apply_metadata(args.input,
                                   LocalQueryClient("http://127.0.0.1:7474", args.secret),
                                   allow_fixture=args.ci_fixture)
            print(f"[OK] {count} metadata-only edges processed.")
            return 0
        titles = curated_titles(args.titles)
        if args.command == "plan-csv":
            report = process_links(
                csv_links(args.input), source_uri=args.source_uri,
                snapshot_sha256=file_sha256(args.input), allowed_titles=titles,
                destination=args.output, max_quarantine=args.max_quarantine,
                fixture_only=args.fixture,
            )
        elif args.command in ("plan-api", "plan-api-file"):
            if args.title not in titles:
                raise ValueError("API title must match a curated exact index title.")
            source_uri = api_url(args.title)
            if args.command == "plan-api":
                if not args.live:
                    raise ValueError("Live API requires explicit --live.")
                source_uri, data = fetch_api_links(args.title)
            else:
                data = json.loads(args.input.read_text(encoding="utf-8"))
            canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            digest = hashlib.sha256(canonical).hexdigest()
            report = process_links(
                api_links(data, args.title), source_uri=source_uri,
                snapshot_sha256=digest, allowed_titles=titles,
                destination=args.output, max_quarantine=args.max_quarantine,
                fixture_only=args.command == "plan-api-file" and args.fixture,
            )
        else:
            raise ValueError("Unsupported command.")
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"[FAIL] Sefaria metadata ingestion: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
