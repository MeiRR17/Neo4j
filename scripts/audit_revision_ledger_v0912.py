#!/usr/bin/env python3
"""Explicitly governed local v0.9.12 audit revision writer and chain verifier.

No production write is enabled by default. In CI, *both* CI=true and
--ack-disposable-fixture are needed. Outside CI, the operator must enable
DVIROS_AUDIT_REVISION_WRITE_ENABLE=1 and pass --ack-metadata-write. This
writes ONLY AuditRevisionHead/AuditRevision metadata, never Work/Evidence.
No write is automatically performed by the public Research API.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.bootstrap import DEFAULT_SECRET_PATH
from scripts.migrate import LocalQueryClient
from services.research_api.audit_export_v0911 import MAX_BYTES
from services.research_api.config import TOKEN_PATH, load_token
from services.research_api.revision_ledger_v0912 import (
    RevisionLedgerError, _verified_export, append_revision,
    bootstrap_head, head_for, verify_revision_chain,
)


def _load_export(path: Path) -> dict:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise RevisionLedgerError("Invalid local export file.")
    if path.stat().st_size > MAX_BYTES + 2048:
        raise RevisionLedgerError("Export file exceeded metadata budget.")
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES + 2048:
        raise RevisionLedgerError("Export file exceeded metadata budget.")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise RevisionLedgerError("Invalid export encoding.") from None
    if not isinstance(data, dict):
        raise RevisionLedgerError("Signed export must be a JSON object.")
    return data


def _write_authorized(args) -> bool:
    if not args.ack_metadata_write:
        return False
    if args.ack_disposable_fixture:
        return os.getenv("CI") == "true"
    return os.getenv("DVIROS_AUDIT_REVISION_WRITE_ENABLE") == "1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "bootstrap", "append", "verify"))
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--token-path", type=Path, default=TOKEN_PATH)
    parser.add_argument("--db-secret", type=Path, default=DEFAULT_SECRET_PATH)
    parser.add_argument("--url", default="http://127.0.0.1:7474")
    parser.add_argument("--expected-sequence", type=int)
    parser.add_argument("--expected-chain")
    parser.add_argument("--ack-metadata-write", action="store_true")
    parser.add_argument("--ack-disposable-fixture", action="store_true")
    args = parser.parse_args(argv)
    if args.action in ("bootstrap", "append") and not _write_authorized(args):
        print("[BLOCKED] Explicit governed metadata-write approval required.",
              file=sys.stderr)
        return 2
    try:
        export = _load_export(args.input)
        secret = load_token(args.token_path)
        manifest, scope = _verified_export(export, secret)
        if args.action == "plan":
            result = {
                "schema_version": "0.9.12", "scope_id": scope,
                "observed_link_count": manifest["observed_link_count"],
                "signed_export_verified_locally": True,
                "database_contacted": False, "database_written": False,
                "research_release_status": "HOLD",
            }
        else:
            db = LocalQueryClient(args.url, args.db_secret)
            source = manifest["source_work_id"]
            target = manifest["target_work_id"]
            if args.action == "bootstrap":
                result = bootstrap_head(db, export, secret=secret)
                # Existing head is never reset by bootstrap.
                result = {
                    "schema_version": "0.9.12",
                    "scope_id": result["id"], "sequence": result["sequence"],
                    "chain_sha256": result["chain_sha256"],
                    "research_release_status": "HOLD",
                }
            elif args.action == "append":
                if args.expected_sequence is None or args.expected_chain is None:
                    raise RevisionLedgerError("Expected revision head required.")
                result = append_revision(
                    db, export, secret=secret,
                    expected_sequence=args.expected_sequence,
                    expected_chain_sha256=args.expected_chain,
                )
            else:
                result = verify_revision_chain(db, source, target)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (RevisionLedgerError, ValueError, TypeError, RuntimeError,
            OSError, UnicodeError):
        # Do not echo remote DB errors, secrets, file contents or Work names.
        print("[FAIL] Revision ledger authorization, integrity or CAS check failed.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
