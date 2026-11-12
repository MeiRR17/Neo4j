#!/usr/bin/env python3
"""v0.10.0 offline research study packet integrity check and safe CSV export.

Private metadata only; never infer publication rights or human approval.
DvirOS must separately store notes/review decisions in its own Postgres.
No Neo4j access, saved researcher data, public API writes or license bypass.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.research_api.config import TOKEN_PATH, load_token
from services.research_api.study_packets_v0100 import (
    CITATION_FIELDS, verify_study_packet, StudyPacketError,
)

MAX_FILE_BYTES = 300_000
MAX_CSV_BYTES = 32_768


def _read(path: Path) -> dict:
    if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
        raise StudyPacketError("Invalid private study packet path.")
    if not 1 <= path.stat().st_size <= MAX_FILE_BYTES:
        raise StudyPacketError("Study packet file size invalid.")
    raw = path.read_bytes()
    if not 1 <= len(raw) <= MAX_FILE_BYTES:
        raise StudyPacketError("Study packet byte limit exceeded.")
    def unique(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise StudyPacketError("Duplicate JSON field refused.")
            result[name] = value
        return result
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    except (ValueError, UnicodeError):
        raise StudyPacketError("Study packet JSON invalid.") from None
    if not isinstance(value, dict):
        raise StudyPacketError("Study packet root must be object.")
    return value


def _safe_csv_cell(value: object) -> str:
    if value is None:
        return ""
    if type(value) is not str:
        raise StudyPacketError("Unsafe CSV citation value.")
    # Spreadsheet formula injection mitigation for external references.
    # This prefix is export formatting, NOT provenance alteration.
    if value.startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
        return "'" + value
    return value


def citation_csv(packet: dict) -> bytes:
    writer = io.StringIO(newline="")
    fields = (*CITATION_FIELDS, "claim_kind", "citation_scope")
    csv_writer = csv.DictWriter(
        writer, fieldnames=fields, extrasaction="raise",
        lineterminator="\n",
    )
    csv_writer.writeheader()
    for row in packet["citations"]:
        csv_writer.writerow({key: _safe_csv_cell(row[key]) for key in fields})
    value = writer.getvalue().encode("utf-8")
    if len(value) > MAX_CSV_BYTES:
        raise StudyPacketError("CSV citation export exceeds size limit.")
    return value


def _save_private(path: Path, contents: bytes) -> None:
    if (path.is_symlink() or path.exists() or
            path.parent.is_symlink() or
            not 1 <= len(contents) <= MAX_CSV_BYTES):
        raise StudyPacketError("Unsafe CSV output path or size.")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt" and stat.S_IMODE(path.parent.stat().st_mode) & 0o022:
        raise StudyPacketError("CSV output parent permissions unsafe.")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(contents)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("verify", "csv"))
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--token-path", type=Path, default=TOKEN_PATH)
    p.add_argument("--output", type=Path)
    args = p.parse_args(argv)
    if args.action == "csv" and args.output is None:
        print("[BLOCKED] Private, new CSV output path required.", file=sys.stderr)
        return 2
    try:
        envelope = _read(args.input)
        verified = verify_study_packet(
            envelope, secret=load_token(args.token_path))
        if args.action == "csv":
            data = citation_csv(envelope["packet"])
            _save_private(args.output, data)
            verified = {
                **verified, "metadata_only_csv_created": True,
                "human_approval_recorded": False,
                "licensed_source_rights_verified": False,
                "research_release_status": "HOLD",
            }
        print(json.dumps(verified, ensure_ascii=False,
                         sort_keys=True, separators=(",", ":")))
        return 0
    except (ValueError, TypeError, KeyError, OSError, RuntimeError):
        print("[FAIL] Private study packet invalid or output refused.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
