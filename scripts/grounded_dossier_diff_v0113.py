#!/usr/bin/env python3
"""Build or verify an offline v0.11.3 unsigned Evidence-dossier diff.

The two input files must be private v0.11.2 metadata-only dossiers from
the same query and Passage scope. No token, graph access, network, model
generation, source text, human approval or writes to an existing file.
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
from services.research_api.grounded_dossier_diff_v0113 import (
    build_grounded_dossier_diff,
    verify_grounded_dossier_diff,
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("build", "verify"))
    p.add_argument("--before", type=Path, required=True)
    p.add_argument("--after", type=Path, required=True)
    p.add_argument("--output", type=Path)
    p.add_argument("--report", type=Path)
    args = p.parse_args(argv)
    if (
        args.before == args.after
        or (args.action == "build" and (args.output is None or args.report))
        or (args.action == "verify" and (args.report is None or args.output))
    ):
        p.error("Require distinct private --before/--after; build --output or verify --report.")
    try:
        before, after = _read(args.before), _read(args.after)
        if args.action == "build":
            receipt = build_grounded_dossier_diff(before, after)
            summary = verify_grounded_dossier_diff(receipt, before, after)
            data = json.dumps(
                receipt, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            _save_private(args.output, data)
        else:
            summary = verify_grounded_dossier_diff(
                _read(args.report), before, after,
            )
        # Summary is intentionally aggregate: no Evidence IDs or source refs
        # are written to stdout.
        print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
        return 0
    except (ValueError, TypeError, KeyError, RuntimeError, OSError):
        print("[FAIL] Private grounded dossier comparison rejected.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
