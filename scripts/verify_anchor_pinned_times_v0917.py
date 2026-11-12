#!/usr/bin/env python3
"""Offline-only verification of two separately pinned timestamp signatures.

Does NOT issue production timestamp tokens, generate or distribute keys,
call an AWS/TSA endpoint, or convert operator-pinned issuers into
independently accredited timestamp authorities.
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
from services.research_api.anchor_governance_v0915 import MAX_REPORT_BYTES
from services.research_api.anchor_s3_v0914 import MAX_BINDING_BYTES
from services.research_api.anchor_governance_recheck_v0916 import (
    MAX_REPORT_BYTES as MAX_PAIR_BYTES,
)
from services.research_api.config import load_token
from services.research_api.pinned_time_attestations_v0917 import (
    MAX_REPORT_BYTES as MAX_TIME_BYTES,
    compare_pinned_times, verify_pinned_time_comparison,
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("compare", "verify"))
    for name in (
        "signed-anchor", "trusted-policy", "archive-binding",
        "local-key-file", "first-observation", "second-observation",
        "paired-comparison", "first-timestamp", "second-timestamp",
        "time-authority-policy",
    ):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--report", type=Path)
    p.add_argument("--output", type=Path)
    a = p.parse_args(argv)
    if a.action == "compare" and a.output is None:
        print("[BLOCKED] Private, create-only comparison path required.")
        return 2
    if a.action == "verify" and a.report is None:
        print("[BLOCKED] Saved time-comparison report required.")
        return 2
    try:
        signed, envelope = _signed_bytes(a.signed_anchor)
        pin = _strict_json(a.trusted_policy, 16384)
        binding = _strict_json(a.archive_binding, MAX_BINDING_BYTES)
        key = load_token(a.local_key_file)
        first = _strict_json(a.first_observation, MAX_REPORT_BYTES)
        second = _strict_json(a.second_observation, MAX_REPORT_BYTES)
        paired = _strict_json(a.paired_comparison, MAX_PAIR_BYTES)
        first_stamp = _strict_json(a.first_timestamp, 2048)
        second_stamp = _strict_json(a.second_timestamp, 2048)
        time_policy = _strict_json(a.time_authority_policy, 4096)
        params = dict(
            time_policy=time_policy, envelope=envelope, pin_policy=pin,
            signed_bytes=signed, binding=binding, local_key=key,
        )
        if a.action == "compare":
            report = compare_pinned_times(
                first, second, paired, first_stamp, second_stamp, **params,
            )
            _private_output(a.output, report)
            summary = {
                "schema_version": "0.9.17",
                "pinned_time_comparison_saved": True,
                "network_or_aws_contacted": False,
                "timestamp_issuer_independently_accredited": False,
                "research_release_status": "HOLD",
            }
        else:
            saved = _strict_json(a.report, MAX_TIME_BYTES)
            summary = verify_pinned_time_comparison(
                saved, first, second, paired, first_stamp, second_stamp,
                **params,
            )
        print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
        return 0
    except (ValueError, TypeError, KeyError, OSError, RuntimeError):
        print("[FAIL] Pinned timestamp or exact S3 receipt verification denied.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
