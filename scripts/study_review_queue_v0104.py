#!/usr/bin/env python3
"""Build or verify a signed, metadata-only Neo review queue offline.

Inputs are 2–6 complete private v0.10.0 packet JSON files in increasing
reported-time order. No reviewer decisions or DvirOS workspace writes.
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
from services.research_api.study_review_queue_v0104 import (
    build_evidence_review_queue,
    verify_evidence_review_queue,
)
from services.research_api.study_timeline_v0103 import (
    MAX_CAPTURES, MIN_CAPTURES,
)

MAX_OUTPUT_BYTES = 250_000


def _save_private(path: Path, content: bytes) -> None:
    """Create once with restrictive permissions; refuse symlinks/overwrites."""
    if (
        not 1 <= len(content) <= MAX_OUTPUT_BYTES
        or path.is_symlink() or path.exists() or path.parent.is_symlink()
    ):
        raise ValueError("Unsafe private review queue path.")
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if os.name != "nt" and stat.S_IMODE(path.parent.stat().st_mode) & 0o022:
        raise ValueError("Private review queue parent is group/world writable.")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
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
        parser.error(
            "Need 2–6 ordered --packet files and an action-specific --output/--report."
        )
    try:
        previews = [_read(path) for path in args.packet]
        secret = load_token(args.token_path)
        if args.action == "build":
            report = build_evidence_review_queue(previews, secret=secret)
            result = verify_evidence_review_queue(
                report, previews, secret=secret,
            )
            payload = json.dumps(
                report, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            _save_private(args.output, payload)
        else:
            report = _read(args.report)
            result = verify_evidence_review_queue(
                report, previews, secret=secret,
            )
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (ValueError, TypeError, KeyError, RuntimeError, OSError):
        print(
            "[FAIL] Signed review queue invalid or private write refused.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
