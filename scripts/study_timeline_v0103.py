#!/usr/bin/env python3
"""Create or verify a private multi-capture signed study timeline.

Example:
  python scripts/study_timeline_v0103.py build \
    --packet old.json --packet middle.json --packet latest.json \
    --token-path /private/token --output /private/study-timeline.json

  python scripts/study_timeline_v0103.py verify \
    --packet old.json --packet middle.json --packet latest.json \
    --token-path /private/token --report /private/study-timeline.json

The order of --packet arguments is meaningful. Each original v0.10.0
packet must remain owner-readable only. No Neo4j, DvirOS or AWS calls.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_study_packet_v0100 import _read
from services.research_api.config import TOKEN_PATH, load_token
from services.research_api.study_timeline_v0103 import (
    MAX_CAPTURES, MIN_CAPTURES, build_study_timeline,
    verify_study_timeline,
)

MAX_FILE_BYTES = 250_000


def _create_private(path: Path, content: bytes) -> None:
    if (
        not 1 <= len(content) <= MAX_FILE_BYTES
        or path.is_symlink() or path.exists()
        or path.parent.is_symlink()
    ):
        raise ValueError("Unsafe timeline output path or size.")
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if os.name != "nt" and stat.S_IMODE(path.parent.stat().st_mode) & 0o022:
        raise ValueError("Unsafe timeline output parent permissions.")
    fd = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0), 0o600,
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "verify"))
    parser.add_argument("--packet", type=Path, action="append", required=True)
    parser.add_argument("--token-path", type=Path, default=TOKEN_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if (
        not MIN_CAPTURES <= len(args.packet) <= MAX_CAPTURES
        or (args.action == "build" and (args.output is None or args.report))
        or (args.action == "verify" and (args.report is None or args.output))
    ):
        parser.error("Need 2–6 ordered --packet files and action-specific output/report.")
    try:
        packets = [_read(path) for path in args.packet]
        token = load_token(args.token_path)
        if args.action == "build":
            receipt = build_study_timeline(packets, secret=token)
            status = verify_study_timeline(receipt, packets, secret=token)
            data = json.dumps(
                receipt, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            _create_private(args.output, data)
        else:
            receipt = _read(args.report)
            status = verify_study_timeline(receipt, packets, secret=token)
        print(json.dumps(status, sort_keys=True, separators=(",", ":")))
        return 0
    except (ValueError, TypeError, KeyError, OSError, RuntimeError):
        print(
            "[FAIL] Study observation timeline invalid or private output refused.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
