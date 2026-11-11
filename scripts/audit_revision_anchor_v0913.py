#!/usr/bin/env python3
"""v0.9.13 read-only checkpoint capture, offline Ed25519 signing/verification.

No cloud uploads, key generation or public API writes. A local signing
key is supplied explicitly as 32 raw bytes in a 0600 regular file.
The separately pinned public-key policy must come from a trusted path;
this tool cannot establish independent signer identity or Object Lock.
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

from scripts.bootstrap import DEFAULT_SECRET_PATH
from scripts.migrate import LocalQueryClient
from services.research_api.revision_anchor_v0913 import (
    AnchorError, capture_anchor, compare_anchor_to_live,
    sign_anchor, verify_anchor, _anchor,
)

MAX_INPUT_BYTES = 16384


def _read(path: Path, *, raw: bool = False):
    p = Path(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_size == 0:
        raise AnchorError("Anchor input path invalid.")
    size = p.stat().st_size
    if size > (32 if raw else MAX_INPUT_BYTES):
        raise AnchorError("Anchor input exceeded size budget.")
    if raw:
        if (os.name != "nt" and
                stat.S_IMODE(p.stat().st_mode) != 0o600):
            raise AnchorError("Signing key file must have 0600 permissions.")
        value = p.read_bytes()
        if len(value) != 32:
            raise AnchorError("Raw Ed25519 signing key must be 32 bytes.")
        return value
    try:
        data = p.read_bytes()
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Duplicate JSON key.")
                result[key] = value
            return result
        value = json.loads(data.decode("utf-8"), object_pairs_hook=unique)
    except (ValueError, UnicodeError):
        raise AnchorError("Anchor input JSON invalid.") from None
    if type(value) is not dict:
        raise AnchorError("Anchor input must be a JSON object.")
    return value


def _private_output(path: Path, content: dict) -> None:
    p = Path(path)
    if p.is_symlink() or p.exists() or p.parent.is_symlink():
        raise AnchorError("Refusing to overwrite or follow an anchor output.")
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt" and stat.S_IMODE(p.parent.stat().st_mode) & 0o022:
        raise AnchorError("Output directory is group/world writable.")
    data = (json.dumps(
        content, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False,
    ) + "\n").encode("utf-8")
    if len(data) > MAX_INPUT_BYTES:
        raise AnchorError("Anchor output too large.")
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as fp:
            fp.write(data)
    except BaseException:
        p.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("capture", "sign", "verify", "compare"))
    parser.add_argument("--source-work-id")
    parser.add_argument("--target-work-id")
    parser.add_argument("--anchor", type=Path)
    parser.add_argument("--signed", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--signer-id")
    parser.add_argument("--private-key", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:7474")
    parser.add_argument("--db-secret", type=Path, default=DEFAULT_SECRET_PATH)
    args = parser.parse_args(argv)
    try:
        if args.action == "capture":
            if not (args.source_work_id and args.target_work_id and
                    args.output):
                raise AnchorError("Capture requires Works and private output.")
            client = LocalQueryClient(args.url, args.db_secret)
            result = capture_anchor(
                client, args.source_work_id, args.target_work_id)
            _private_output(args.output, result)
            summary = {
                "schema_version": "0.9.13",
                "anchored_sequence": result["anchored_sequence"],
                "anchor_captured": True, "archive_immutability_verified": False,
                "research_release_status": "HOLD",
            }
        elif args.action == "sign":
            if not (args.anchor and args.signer_id and args.private_key and
                    args.output):
                raise AnchorError("Sign requires anchor, signer, key and output.")
            statement = _read(args.anchor)
            key = _read(args.private_key, raw=True)
            envelope = sign_anchor(
                statement, signer_id=args.signer_id, private_key_bytes=key)
            _private_output(args.output, envelope)
            summary = {
                "schema_version": "0.9.13",
                "anchor_signed": True, "signer_identity_verified": False,
                "research_release_status": "HOLD",
            }
        else:
            if not args.signed or not args.policy:
                raise AnchorError("Verification requires signed anchor and policy.")
            signed, policy = _read(args.signed), _read(args.policy)
            if args.action == "verify":
                summary = verify_anchor(signed, policy)
            else:
                db = LocalQueryClient(args.url, args.db_secret)
                summary = compare_anchor_to_live(db, signed, policy)
        print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
        return 0
    except (AnchorError, ValueError, TypeError, OSError, RuntimeError):
        print("[FAIL] Audit revision anchor, trust policy or live prefix invalid.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
