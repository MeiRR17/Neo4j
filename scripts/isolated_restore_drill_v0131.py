#!/usr/bin/env python3
"""Plan or explicitly execute a private isolated Neo4j offline restore drill.

Execution requires an existing verified v0.13.0 dump/manifest, pre-pulled
pinned neo4j-admin image, Docker and --ack-isolated-volume. Never uses the
live Compose volume or starts a network-reachable database. On success the
new temporary Docker volume is removed and a 0600 private report is written.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.research_api.isolated_restore_v0131 import (
    execute_isolated_restore_drill, plan_isolated_restore_drill,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "execute"))
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--ack-isolated-volume", action="store_true")
    args = parser.parse_args(argv)
    if (args.action == "plan" and (args.output or args.ack_isolated_volume)
            or args.action == "execute" and
            (not args.output or not args.ack_isolated_volume)):
        parser.error("Plan must not execute; execution requires --output and --ack-isolated-volume.")
    try:
        if args.action == "plan":
            result = plan_isolated_restore_drill(
                args.archive.absolute(), args.manifest.absolute(),
            )
            # Plan is metadata only; never print absolute private path.
            result = {k: v for k, v in result.items() if k != "archive_filename"}
        else:
            result = execute_isolated_restore_drill(
                args.archive.absolute(), args.manifest.absolute(),
                args.output.absolute(), acknowledged=True,
            )
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (OSError, ValueError, RuntimeError):
        print(
            "[FAIL] Isolated offline restore drill refused or incomplete.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
