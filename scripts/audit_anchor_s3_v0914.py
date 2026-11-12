#!/usr/bin/env python3
"""v0.9.14 opt-in, read-only S3 check of one signed audit-anchor version.

Two actions:
  inspect --ack-live-aws-read-only  (two fixed AWS metadata reads)
  verify                         (offline HMAC + pin verification)
No upload, GET object bytes, delete, policy mutation or arbitrary endpoint.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.external_archive_attestation import _strict_json
from scripts.live_s3_version_verify import live_s3_client
from scripts.audit_revision_anchor_v0913 import _private_output
from services.research_api.anchor_s3_v0914 import (
    AnchorArchiveError, MAX_ANCHOR_FILE_BYTES, MAX_BINDING_BYTES,
    MAX_OBSERVATION_BYTES, _local_chain, _mac,
    observe_anchor_s3_version, verify_anchor_s3_observation,
)
from services.research_api.config import load_token


def _signed_bytes(path: Path) -> tuple[bytes, dict]:
    p = Path(path)
    if p.is_symlink() or p.parent.is_symlink() or not p.is_file():
        raise AnchorArchiveError("Signed anchor input path invalid.")
    info = p.stat()
    if (not stat.S_ISREG(info.st_mode) or
            info.st_size == 0 or info.st_size > MAX_ANCHOR_FILE_BYTES or
            info.st_mode & 0o022):
        raise AnchorArchiveError("Signed anchor file permission or size invalid.")
    raw = p.read_bytes()
    if not 1 <= len(raw) <= MAX_ANCHOR_FILE_BYTES:
        raise AnchorArchiveError("Signed anchor byte budget invalid.")

    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError
            out[key] = value
        return out
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    except (ValueError, UnicodeError, TypeError):
        raise AnchorArchiveError("Signed anchor file encoding invalid.") from None
    if type(data) is not dict:
        raise AnchorArchiveError("Signed anchor must be a JSON object.")
    return raw, data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inspect", "verify"))
    parser.add_argument("--signed-anchor", type=Path, required=True)
    parser.add_argument("--trusted-policy", type=Path, required=True)
    parser.add_argument("--archive-binding", type=Path, required=True)
    parser.add_argument("--local-key-file", type=Path, required=True)
    parser.add_argument("--observation", type=Path)
    parser.add_argument("--aws-profile")
    parser.add_argument("--ack-live-aws-read-only", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.action == "inspect" and (
            not args.ack_live_aws_read_only or
            not args.aws_profile or args.output is None):
        print("[BLOCKED] Explicit live read-only AWS authorization required.")
        return 2
    try:
        raw, envelope = _signed_bytes(args.signed_anchor)
        policy = _strict_json(args.trusted_policy, 16384)
        binding = _strict_json(args.archive_binding, MAX_BINDING_BYTES)
        key = load_token(args.local_key_file)
        if args.action == "inspect":
            # Fail locally before even constructing an AWS SDK client.
            _local_chain(envelope, policy, raw, binding)
            _mac({"preflight": True}, key)
            client = live_s3_client(
                profile=args.aws_profile, region=binding["aws_region"],
                account=binding["expected_bucket_owner"],
            )
            report = observe_anchor_s3_version(
                client, envelope=envelope, pin_policy=policy,
                signed_bytes=raw, binding=binding, local_key=key,
            )
            _private_output(args.output, report)
            summary = {
                "schema_version": "0.9.14",
                "read_only_exact_version_s3_observation_written": True,
                "live_two_metadata_reads_completed": True,
                "signed_anchor_full_object_checksum_matched": True,
                "external_archive_continuously_immutable_verified": False,
                "research_release_status": "HOLD",
            }
        else:
            if args.observation is None:
                raise AnchorArchiveError("Missing saved S3 observation.")
            report = _strict_json(args.observation, MAX_OBSERVATION_BYTES)
            summary = verify_anchor_s3_observation(
                report, envelope=envelope, pin_policy=policy,
                signed_bytes=raw, binding=binding, local_key=key,
            )
        print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
        return 0
    except (ValueError, TypeError, KeyError, OSError, UnicodeError):
        print("[FAIL] Signed anchor, pinned binding or exact S3 version invalid.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
