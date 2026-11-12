#!/usr/bin/env python3
"""v0.9.15 opt-in read-only STS/bucket governance check for signed anchor S3.

inspect: requires explicit AWS profile/acknowledgment; does 7 reads only.
verify: checks pinned signature, exact-byte observation and HMAC offline.
No uploads, deletes, source downloads or IAM mutations.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.audit_anchor_s3_v0914 import _signed_bytes
from scripts.audit_revision_anchor_v0913 import _private_output
from scripts.external_archive_attestation import _strict_json
from scripts.s3_governance import live_clients
from services.research_api.anchor_s3_v0914 import (
    MAX_BINDING_BYTES, _local_chain,
)
from services.research_api.anchor_governance_v0915 import (
    MAX_REPORT_BYTES, _mac, observe_anchor_governance,
    verify_anchor_governance,
)
from services.research_api.config import load_token


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("inspect", "verify"))
    p.add_argument("--signed-anchor", required=True, type=Path)
    p.add_argument("--trusted-policy", required=True, type=Path)
    p.add_argument("--archive-binding", required=True, type=Path)
    p.add_argument("--local-key-file", required=True, type=Path)
    p.add_argument("--aws-profile")
    p.add_argument("--ack-live-aws-read-only", action="store_true")
    p.add_argument("--observation", type=Path)
    p.add_argument("--output", type=Path)
    args = p.parse_args(argv)

    if args.action == "inspect" and (
        not args.aws_profile or not args.ack_live_aws_read_only or
        args.output is None
    ):
        print("[BLOCKED] Explicit authorized AWS read-only inspection required.")
        return 2
    try:
        raw, envelope = _signed_bytes(args.signed_anchor)
        policy = _strict_json(args.trusted_policy, 16384)
        binding = _strict_json(args.archive_binding, MAX_BINDING_BYTES)
        secret = load_token(args.local_key_file)
        common = {
            "envelope": envelope, "pin_policy": policy,
            "signed_bytes": raw, "binding": binding, "local_key": secret,
        }
        if args.action == "inspect":
            # Authentication and full local signed-byte binding precede
            # creation of any S3/STS SDK client or remote calls.
            _local_chain(envelope, policy, raw, binding)
            _mac({"preflight": True}, secret)
            s3, sts = live_clients(
                profile=args.aws_profile, region=binding["aws_region"],
                account=binding["expected_bucket_owner"])
            report = observe_anchor_governance(s3, sts, **common)
            _private_output(args.output, report)
            summary = {
                "schema_version": "0.9.15",
                "governance_observation_written": True,
                "read_only_s3_metadata_operations": 6,
                "read_only_sts_identity_operations": 1,
                "aws_bucket_controls_observed_at_one_instant": True,
                "continuous_archive_immutability_verified": False,
                "research_release_status": "HOLD",
            }
        else:
            if args.observation is None:
                raise ValueError("Offline observation input required.")
            report = _strict_json(args.observation, MAX_REPORT_BYTES)
            summary = verify_anchor_governance(report, **common)
        print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
        return 0
    except (ValueError, TypeError, KeyError, RuntimeError, OSError):
        print("[FAIL] Signed-anchor governance, binding or saved report rejected.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
