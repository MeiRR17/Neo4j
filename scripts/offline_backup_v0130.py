#!/usr/bin/env python3
"""Produce/verify a strict local offline Neo4j Community dump integrity manifest.

This does NOT stop, dump or restore a database. Use an existing private
operator-generated offline .dump after the database has been safely stopped.
No credentials, network, Docker subprocesses, graph reads or writes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.research_api.offline_backup_v0130 import (
    PINNED_IMAGE, create_offline_dump_manifest, create_private_manifest_file,
    read_private_manifest, verify_offline_dump_manifest,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)

    create = sub.add_parser("manifest", help="Bind an existing private offline dump to a SHA256 manifest.")
    create.add_argument("--archive", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument(
        "--operator-stopped-db", action="store_true", required=True,
        help="Operator attests to stopping Neo4j before producing the dump; not independently verified.",
    )

    verify = sub.add_parser("verify", help="Verify bytes against a private, canonical manifest.")
    verify.add_argument("--archive", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--expected-image", default=PINNED_IMAGE)

    args = parser.parse_args(argv)
    try:
        archive = args.archive.absolute()
        if args.action == "manifest":
            record = create_offline_dump_manifest(
                archive, operator_stopped_database=args.operator_stopped_db,
            )
            create_private_manifest_file(args.output.absolute(), record)
            report = verify_offline_dump_manifest(record, archive)
        else:
            record = read_private_manifest(args.manifest.absolute())
            report = verify_offline_dump_manifest(
                record, archive, expected_image=args.expected_image,
            )
        # No archive paths or potential usernames from paths are printed.
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        return 0
    except (ValueError, OSError, RuntimeError):
        print(
            "[FAIL] Private Neo4j dump integrity preflight rejected.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
