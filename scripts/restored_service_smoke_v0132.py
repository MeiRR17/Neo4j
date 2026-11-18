#!/usr/bin/env python3
"""Plan or opt in to an isolated authenticated Neo4j restore read smoke.

Requires a valid preexisting v0.13.0 private dump+manifest, pinned Docker
images and a private host directory. No interaction with live Compose state.
Reports only non-sensitive aggregate counts; no graph text or secrets.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.research_api.restored_service_smoke_v0132 import (
    execute_restored_service_smoke, plan_restored_service_smoke,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "execute"))
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--minimum-nodes", type=int, default=1)
    parser.add_argument("--minimum-relationships", type=int, default=0)
    parser.add_argument("--minimum-passages", type=int, default=1)
    parser.add_argument("--minimum-source-records", type=int, default=0)
    parser.add_argument("--minimum-constraints", type=int, default=0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--ack-private-restored-smoke", action="store_true")
    args = parser.parse_args(argv)
    if (
        args.action == "plan" and
        (args.output is not None or args.ack_private_restored_smoke)
        or args.action == "execute" and
        (args.output is None or not args.ack_private_restored_smoke)
    ):
        parser.error(
            "Plan forbids execution options; execute needs an output and explicit acknowledgment."
        )
    minimum_counts = {
        "nodes": args.minimum_nodes,
        "relationships": args.minimum_relationships,
        "passages": args.minimum_passages,
        "source_records": args.minimum_source_records,
        "constraints": args.minimum_constraints,
    }
    try:
        if args.action == "plan":
            result = plan_restored_service_smoke(
                args.archive.absolute(), args.manifest.absolute(),
                minimum_counts=minimum_counts,
            )
        else:
            result = execute_restored_service_smoke(
                args.archive.absolute(), args.manifest.absolute(),
                args.output.absolute(), minimum_counts=minimum_counts,
                acknowledged=True,
            )
        # No source excerpts, credentials, private paths or graph records.
        print(json.dumps(result, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")))
        return 0
    except (OSError, ValueError, RuntimeError, TimeoutError):
        print(
            "[FAIL] Private restored-service smoke refused or incomplete.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
