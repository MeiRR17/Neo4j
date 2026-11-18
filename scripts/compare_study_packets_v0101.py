#!/usr/bin/env python3
"""Compare two private signed study previews; verify a saved replay receipt.

No Neo4j queries, graph mutations, user notes or rights publication.
Example:
  python scripts/compare_study_packets_v0101.py compare \\
    --baseline old.json --current new.json --output replay.json
  python scripts/compare_study_packets_v0101.py verify \\
    --baseline old.json --current new.json --report replay.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_study_packet_v0100 import _read, _save_private
from services.research_api.config import TOKEN_PATH, load_token
from services.research_api.study_replay_v0101 import (
    compare_study_packets, verify_study_comparison,
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("compare", "verify"))
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--current", type=Path, required=True)
    p.add_argument("--report", type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--token-path", type=Path, default=TOKEN_PATH)
    args = p.parse_args(argv)
    if (
        (args.action == "compare" and (args.output is None or args.report))
        or (args.action == "verify" and (args.report is None or args.output))
    ):
        p.error("compare requires --output; verify requires --report")
    try:
        old = _read(args.baseline)
        new = _read(args.current)
        secret = load_token(args.token_path)
        if args.action == "compare":
            receipt = compare_study_packets(old, new, secret=secret)
            result = verify_study_comparison(
                receipt, old, new, secret=secret,
            )
            raw = json.dumps(
                receipt, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            _save_private(args.output, raw)
        else:
            receipt = _read(args.report)
            result = verify_study_comparison(
                receipt, old, new, secret=secret,
            )
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (ValueError, TypeError, KeyError, OSError, RuntimeError):
        print(
            "[FAIL] Signed study replay invalid or private output refused.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
