#!/usr/bin/env python3
"""v0.8.15: read-only, version-pinned AWS S3 metadata evidence check.

Requires a separately verified v0.8.14 signed archive claim and v0.8.11-13
local evidence. Never uploads/downloads an object or modifies retention.
An AWS metadata observation is not proof of immutable archival history,
license, signer identity, or scholarly approval.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hmac
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.external_archive_attestation import (
    AttestationError, MAX_ARCHIVE_BYTES, MAX_ATTESTATION_BYTES,
    MAX_POLICY_BYTES, _b64, _date, _strict_json, verify_attestation,
)
from scripts.search_review_workflow import _write_private
from scripts.source_membership import MAX_WITNESS_BYTES
from scripts.source_receipts import (
    MAX_CAPTURE_BYTES, MAX_RECORD_BYTES, MAX_RECEIPT_BYTES, _load_json,
)
from services.research_api.config import load_token
from services.research_api.signature import signature_key_path

SCHEMA = "0.8.15"
ACCOUNT = re.compile(r"^[0-9]{12}$")
AWS_REGION = re.compile(r"^[a-z]{2}-(?:[a-z]+-)+[0-9]{1,2}$")


class S3ProbeError(AttestationError):
    """Generic, redacted failure: do not print source names or credentials."""


def _utc(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise S3ProbeError("S3 retention timestamp missing or lacks timezone.")
    return value.astimezone(timezone.utc)


def _successful(response: object) -> dict:
    if not isinstance(response, dict):
        raise S3ProbeError("S3 response has invalid structure.")
    metadata = response.get("ResponseMetadata")
    if not isinstance(metadata, dict) or type(metadata.get("HTTPStatusCode")) is not int or metadata["HTTPStatusCode"] != 200:
        raise S3ProbeError("S3 response did not confirm a successful request.")
    return response


def verify_s3_metadata(
    client: object, report: dict, receipt: dict, *,
    expected_bucket_owner: str, now_utc: datetime | None = None,
) -> dict:
    """Compare signed claim to two version-scoped AWS API responses.

    `client` is injectable for synthetic tests; only the CLI creates a real
    SigV4 AWS client. This function cannot authenticate the client itself.
    """
    if not isinstance(expected_bucket_owner, str) or not ACCOUNT.fullmatch(expected_bucket_owner):
        raise S3ProbeError("An explicit twelve-digit expected AWS bucket owner is required.")
    if not isinstance(report, dict) or not isinstance(receipt, dict):
        raise S3ProbeError("Archive claim and retained receipt are required.")
    now = _utc(now_utc if now_utc is not None else datetime.now(timezone.utc))
    # The caller MUST verify the exact 0.8.14 signature + local evidence chain
    # before reaching this function. No bucket/key names enter the output.
    request = {
        "Bucket": report["bucket"], "Key": report["object_key"],
        "VersionId": report["version_id"],
        "ExpectedBucketOwner": expected_bucket_owner,
    }
    head = _successful(client.head_object(**request, ChecksumMode="ENABLED"))
    if (head.get("DeleteMarker") is True or
        head.get("VersionId") != report["version_id"] or
        type(head.get("ContentLength")) is not int or
        head["ContentLength"] != report["content_length"] or
        head["ContentLength"] != receipt["observed_file_size_bytes"]):
        raise S3ProbeError("S3 object version or length differs from retained bytes.")
    if head.get("ChecksumType") != "FULL_OBJECT":
        raise S3ProbeError("S3 SHA-256 is missing a FULL_OBJECT checksum type.")
    actual_sha256 = _b64(head.get("ChecksumSHA256"), 32).hex()
    if not (hmac.compare_digest(actual_sha256, report["content_sha256"]) and
            hmac.compare_digest(actual_sha256, receipt["observed_raw_file_sha256"])):
        raise S3ProbeError("S3 full-object SHA-256 differs from locally retained bytes.")
    if head.get("ObjectLockMode") != report["object_lock_mode"]:
        raise S3ProbeError("S3 HEAD lock mode differs from signed archive claim.")
    head_until = _utc(head.get("ObjectLockRetainUntilDate"))
    claimed_until = _date(report["retain_until_utc"])
    if head_until != claimed_until or head_until <= now:
        raise S3ProbeError("S3 HEAD retention date differs or is expired.")

    retention = _successful(client.get_object_retention(**request))
    retention_fields = retention.get("Retention")
    if (not isinstance(retention_fields, dict) or
        retention_fields.get("Mode") != report["object_lock_mode"] or
        _utc(retention_fields.get("RetainUntilDate")) != head_until):
        raise S3ProbeError("S3 retention API differs from HEAD or signed claim.")

    return {
        "schema_version": SCHEMA,
        "verification_scope": "s3_versioned_metadata_consistency_not_immutable_history",
        "s3_head_version_id_matched": True,
        "s3_full_object_sha256_matched": True,
        "s3_independent_retention_api_matched": True,
        "s3_retention_active_at_observation": True,
        "s3_expected_bucket_owner_request_enforced": True,
        "external_archive_immutability_verified": False,
        "signer_organization_identity_independently_verified": False,
        "source_provider_identity_verified": False,
        "source_rights_verified": False,
        "neo4j_snapshot_isolation_verified": False,
        "research_release_status": "HOLD",
    }


def _aws_client(region: str):
    if not isinstance(region, str) or not AWS_REGION.fullmatch(region):
        raise S3ProbeError("Explicit AWS commercial region required.")
    # A custom endpoint could impersonate S3. Ignore env/profile endpoint
    # overrides and reject nonstandard endpoints even if SDK accepts them.
    import boto3
    from botocore.config import Config
    client = boto3.client(
        "s3", region_name=region,
        config=Config(signature_version="s3v4", connect_timeout=5,
                      read_timeout=10, retries={"max_attempts": 2, "mode": "standard"},
                      ignore_configured_endpoint_urls=True,
                      s3={"addressing_style": "path"}),
    )
    url = urlsplit(client.meta.endpoint_url)
    host = url.hostname
    if (url.scheme != "https" or url.username is not None or url.password is not None or
        url.port is not None or url.path not in ("", "/") or url.query or url.fragment or
        host not in {"s3.amazonaws.com", f"s3.{region}.amazonaws.com"}):
        raise S3ProbeError("Nonstandard S3 endpoint rejected.")
    return client


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("source-file", "source-record", "receipt", "witness",
                 "capture-manifest", "trusted-policy", "archive-report",
                 "signed-statement", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--local-key-file", type=Path)
    p.add_argument("--aws-region", required=True)
    p.add_argument("--expected-bucket-owner", required=True)
    args = p.parse_args(argv)
    try:
        policy = _strict_json(args.trusted_policy, MAX_POLICY_BYTES)
        report = _strict_json(args.archive_report, MAX_ARCHIVE_BYTES)
        envelope = _strict_json(args.signed_statement, MAX_ATTESTATION_BYTES)
        record = _load_json(args.source_record, MAX_RECORD_BYTES)
        receipt = _load_json(args.receipt, MAX_RECEIPT_BYTES)
        witness = _load_json(args.witness, MAX_WITNESS_BYTES)
        capture = _load_json(args.capture_manifest, MAX_CAPTURE_BYTES)
        local = verify_attestation(
            policy, report, envelope,
            source_record=record, receipt=receipt, witness=witness,
            capture=capture, source_file=args.source_file,
            local_key=load_token(args.local_key_file or signature_key_path()),
        )
        client = _aws_client(args.aws_region)
        remote = verify_s3_metadata(
            client, report, receipt, expected_bucket_owner=args.expected_bucket_owner)
        result = {**local, **remote, "previous_signed_attestation_sha256":
                  local["signed_statement_sha256"]}
        _write_private(args.output, result)
        print("[OK] S3 version/checksum/retention metadata consistent; "
              "immutable history=NOT VERIFIED; research_release=HOLD.")
        return 0
    except Exception:
        # SDK exceptions may include sensitive resource details. Deliberately
        # do not print them. No report is emitted on any failed check.
        print("[FAIL] Signed chain, AWS metadata or S3 retention verification rejected.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
