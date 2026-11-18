#!/usr/bin/env python3
"""Create or verify a private offline v0.10.2 full audit-window diff.

Uses two independently signed v0.10.0 study preview envelopes. Does not
connect to Neo4j or write to DvirOS. The output is a bounded metadata-only
receipt, not a snapshot or a scholarly reviewer decision.
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
from services.research_api.study_audit_window_v0102 import (
    compare_study_audit_windows, verify_study_audit_window_diff,
)

MAX_OUTPUT_BYTES = 100_000


def _save_new_private(path: Path, content: bytes) -> None:
    if (
        not 1 <= len(content) <= MAX_OUTPUT_BYTES
        or path.is_symlink() or path.exists()
        or path.parent.is_symlink()
    ):
        raise ValueError("Unsafe private comparison output.")
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if os.name != "nt" and stat.S_IMODE(path.parent.stat().st_mode) & 0o022:
        raise ValueError("Unsafe output parent permissions.")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(content)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("compare", "verify"))
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--token-path", type=Path, default=TOKEN_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if (
        (args.action == "compare" and (args.output is None or args.report))
        or (args.action == "verify" and (args.report is None or args.output))
    ):
        parser.error("compare needs --output; verify needs --report")
    try:
        before = _read(args.baseline)
        current = _read(args.current)
        token = load_token(args.token_path)
        if args.action == "compare":
            comparison = compare_study_audit_windows(
                before, current, secret=token,
            )
            status = verify_study_audit_window_diff(
                comparison, before, current, secret=token,
            )
            content = json.dumps(
                comparison, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            _save_new_private(args.output, content)
        else:
            comparison = _read(args.report)
            status = verify_study_audit_window_diff(
                comparison, before, current, secret=token,
            )
        print(json.dumps(status, sort_keys=True, separators=(",", ":")))
        return 0
    except (ValueError, TypeError, KeyError, RuntimeError, OSError):
        print(
            "[FAIL] Signed audit-window comparison invalid or output refused.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
