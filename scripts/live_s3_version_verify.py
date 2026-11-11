#!/usr/bin/env python3
"""v0.8.15: read-only live S3 object-version and Object Lock validation.

Requires a valid v0.8.14 pinned Ed25519 archive claim and the complete
v0.8.11-13 local source chain BEFORE issuing two fixed AWS read calls.
Validates a FULL_OBJECT SHA256, exact S3 version, expected bucket-owner
account, and COMPLIANCE retention using independently requested S3 metadata.
No object downloads, S3 write calls, production credentials or source
texts are added to the repository. An API observation is NOT a timeless
WORM guarantee or independent license/provider signoff.
"""
from __future__ import annotations

import argparse
import base64
import binascii
from datetime import datetime, timezone
import hashlib
import hmac
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.external_archive_attestation import (
    AttestationError, MAX_POLICY_BYTES, MAX_ARCHIVE_BYTES,
    MAX_ATTESTATION_BYTES, _strict_json, _date, verify_attestation,
)
from scripts.search_capture import digest, encode
from scripts.search_review_workflow import _write_private
from scripts.source_membership import MAX_WITNESS_BYTES
from scripts.source_receipts import (
    MAX_CAPTURE_BYTES, MAX_RECORD_BYTES, MAX_RECEIPT_BYTES, _load_json,
)
from services.research_api.config import load_token
from services.research_api.signature import signature_key_path

SCHEMA = "0.8.15"
DOMAIN = b"neo4j-live-s3-object-metadata-v0.8.15\n"
PROFILE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$")
REGION = re.compile(
    r"^(?:us|eu|ap|ca|sa|af|me|il)-(?:north|south|east|west|"
    r"central|northeast|southeast|southwest)-[1-9]$")
ACCOUNT = re.compile(r"^[0-9]{12}$")
HEX = re.compile(r"^[0-9a-f]{64}$")
RESULT_FIELDS = frozenset({
    "schema_version", "scope", "attested_claim_sha256",
    "source_witness_sha256", "s3_report_sha256",
    "expected_bucket_owner_sha256", "aws_region",
    "observed_at_utc", "observed_version_id_sha256",
    "head_request_id_sha256", "retention_request_id_sha256",
    "head_checksum_type", "head_sha256",
    "head_content_length", "retention_until_utc",
    "head_and_retention_version_explicit",
    "aws_versioned_head_observed", "aws_full_object_sha256_matched",
    "aws_compliance_retention_read_observed",
    "signed_provider_identity_independently_verified",
    "aws_bucket_ownership_independently_audited",
    "external_archive_immutability_end_to_end_verified",
    "external_write_freeze_achieved", "legal_source_rights_verified",
    "research_release_status", "observation_hmac",
})


class S3VerificationError(ValueError):
    """Never echo a request, bucket, object name, credentials or response."""


def _datetime(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise S3VerificationError("AWS retention date is not timezone-aware.")
    return value.astimezone(timezone.utc)


def _utc(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _request_id(response: object) -> str:
    if not isinstance(response, dict):
        raise S3VerificationError("AWS response envelope invalid.")
    meta = response.get("ResponseMetadata")
    if (not isinstance(meta, dict) or
        type(meta.get("HTTPStatusCode")) is not int or
        meta["HTTPStatusCode"] != 200 or
        not isinstance(meta.get("RequestId"), str) or
        not 1 <= len(meta["RequestId"]) <= 150):
        raise S3VerificationError("AWS SDK read request not confirmed.")
    return digest(meta["RequestId"].encode("utf-8"))


def _sha256_from_s3(value: object) -> str:
    if not isinstance(value, str) or len(value) > 100:
        raise S3VerificationError("S3 full-object checksum absent.")
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise S3VerificationError("S3 checksum encoding invalid.") from None
    if len(raw) != 32 or base64.b64encode(raw).decode("ascii") != value:
        raise S3VerificationError("S3 checksum length/encoding invalid.")
    return raw.hex()


def _identity(profile: str, region: str, account: str) -> None:
    if (not isinstance(profile, str) or not PROFILE.fullmatch(profile) or
        not isinstance(region, str) or not REGION.fullmatch(region) or
        not isinstance(account, str) or not ACCOUNT.fullmatch(account)):
        raise S3VerificationError("Explicit AWS profile, region and owner required.")


def live_s3_client(*, profile: str, region: str, account: str):
    """Construct a fixed AWS TLS endpoint. No arbitrary custom endpoints."""
    _identity(profile, region, account)
    try:
        import boto3
        from botocore.config import Config
        session = boto3.Session(profile_name=profile, region_name=region)
        return session.client(
            "s3", region_name=region,
            endpoint_url="https://s3." + region + ".amazonaws.com",
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 1, "mode": "standard"},
                connect_timeout=5, read_timeout=10,
                s3={"addressing_style": "virtual"},
            ))
    except Exception:
        raise S3VerificationError("Pinned AWS SDK client unavailable.") from None


def _sign(unsigned: dict, key: str) -> str:
    if not isinstance(key, str) or len(key) < 40:
        raise S3VerificationError("Local HMAC key unavailable.")
    return hmac.new(key.encode("utf-8"), DOMAIN + encode(unsigned),
                    hashlib.sha256).hexdigest()


def _chain(policy: dict, report: dict, statement: dict,
           record: dict, receipt: dict, witness: dict, capture: dict,
           file: Path, key: str) -> dict:
    try:
        return verify_attestation(
            policy, report, statement, source_record=record,
            receipt=receipt, witness=witness, capture=capture,
            source_file=file, local_key=key)
    except (ValueError, TypeError, KeyError, OSError):
        raise S3VerificationError("Pinned signer or source chain invalid.") from None


def observe_s3_version(
    client, *, policy: dict, report: dict, statement: dict,
    record: dict, receipt: dict, witness: dict, capture: dict,
    source_file: Path, local_key: str, account: str, region: str,
    observed_at: datetime | None = None,
) -> dict:
    """Two read-only S3 operations for one explicit bucket/key/version.

    client is injected in tests; production CLI only uses AWS SDK.
    """
    if (not isinstance(region, str) or not REGION.fullmatch(region) or
        not isinstance(account, str) or not ACCOUNT.fullmatch(account)):
        raise S3VerificationError("Unpinned region or expected account.")
    claim = _chain(policy, report, statement, record, receipt, witness,
                   capture, source_file, local_key)
    if report["object_lock_mode"] != "COMPLIANCE":
        raise S3VerificationError("Only non-bypassable COMPLIANCE mode accepted.")
    now = (_datetime(observed_at) if observed_at is not None
           else datetime.now(timezone.utc))
    expected_expiry = _date(report["retain_until_utc"])
    if expected_expiry <= now:
        raise S3VerificationError("Reported retention has already expired.")

    # Crucially: no HEAD on latest version or unpinned object name. Both
    # calls pass AWS ExpectedBucketOwner and the exact recorded VersionId.
    params = {
        "Bucket": report["bucket"], "Key": report["object_key"],
        "VersionId": report["version_id"], "ExpectedBucketOwner": account,
    }
    try:
        head = client.head_object(**params, ChecksumMode="ENABLED")
        lock = client.get_object_retention(**params)
    except Exception:
        raise S3VerificationError("Read-only versioned S3 verification failed.") from None

    head_req = _request_id(head)
    lock_req = _request_id(lock)
    if (head.get("VersionId") != report["version_id"] or
        head.get("DeleteMarker") is True or
        type(head.get("ContentLength")) is not int or
        head["ContentLength"] != report["content_length"] or
        head["ContentLength"] != receipt["observed_file_size_bytes"] or
        head.get("ChecksumType") != "FULL_OBJECT"):
        raise S3VerificationError("Version/size or FULL_OBJECT checksum contract failed.")
    sha = _sha256_from_s3(head.get("ChecksumSHA256"))
    if (sha != report["content_sha256"] or
        sha != receipt["observed_raw_file_sha256"]):
        raise S3VerificationError("AWS full-object SHA256 differs from local bytes.")

    detail = lock.get("Retention")
    if not isinstance(detail, dict) or (
        detail.get("Mode") != "COMPLIANCE" or
        head.get("ObjectLockMode") != "COMPLIANCE"):
        raise S3VerificationError("S3 COMPLIANCE Object Lock not observed.")
    retention = _datetime(detail.get("RetainUntilDate"))
    head_retention = _datetime(head.get("ObjectLockRetainUntilDate"))
    if (retention != head_retention or
        _utc(retention) != report["retain_until_utc"] or
        retention <= now):
        raise S3VerificationError("Independent Object Lock expiration differs.")

    unsigned = {
        "schema_version": SCHEMA,
        "scope": "read_only_exact_s3_object_version_head_and_retention",
        "attested_claim_sha256": claim["signed_statement_sha256"],
        "source_witness_sha256": digest(encode(witness)),
        "s3_report_sha256": digest(encode(report)),
        "expected_bucket_owner_sha256": digest(account.encode("ascii")),
        "aws_region": region,
        "observed_at_utc": _utc(now),
        "observed_version_id_sha256": digest(report["version_id"].encode("utf-8")),
        "head_request_id_sha256": head_req,
        "retention_request_id_sha256": lock_req,
        "head_checksum_type": "FULL_OBJECT",
        "head_sha256": sha,
        "head_content_length": head["ContentLength"],
        "retention_until_utc": _utc(retention),
        "head_and_retention_version_explicit": True,
        "aws_versioned_head_observed": True,
        "aws_full_object_sha256_matched": True,
        "aws_compliance_retention_read_observed": True,
        "signed_provider_identity_independently_verified": False,
        "aws_bucket_ownership_independently_audited": False,
        "external_archive_immutability_end_to_end_verified": False,
        "external_write_freeze_achieved": False,
        "legal_source_rights_verified": False,
        "research_release_status": "HOLD",
    }
    return {**unsigned, "observation_hmac": _sign(unsigned, local_key)}


def verify_observation(
    observation: object, *, policy: dict, report: dict, statement: dict,
    record: dict, receipt: dict, witness: dict, capture: dict,
    source_file: Path, local_key: str, account: str, region: str,
) -> None:
    """Offline integrity check; never claims live AWS state is still current."""
    if not isinstance(observation, dict) or set(observation) != RESULT_FIELDS:
        raise S3VerificationError("Offline observation envelope invalid.")
    if (not isinstance(account, str) or not ACCOUNT.fullmatch(account) or
        not isinstance(region, str) or not REGION.fullmatch(region)):
        raise S3VerificationError("Offline account/region constraints invalid.")
    claim = _chain(policy, report, statement, record, receipt, witness,
                   capture, source_file, local_key)
    expected_fixed = {
        "schema_version": SCHEMA,
        "scope": "read_only_exact_s3_object_version_head_and_retention",
        "attested_claim_sha256": claim["signed_statement_sha256"],
        "source_witness_sha256": digest(encode(witness)),
        "s3_report_sha256": digest(encode(report)),
        "expected_bucket_owner_sha256": digest(account.encode("ascii")),
        "aws_region": region,
        "observed_version_id_sha256": digest(report["version_id"].encode()),
        "head_checksum_type": "FULL_OBJECT",
        "head_sha256": receipt["observed_raw_file_sha256"],
        "head_content_length": receipt["observed_file_size_bytes"],
        "retention_until_utc": report["retain_until_utc"],
        "head_and_retention_version_explicit": True,
        "aws_versioned_head_observed": True,
        "aws_full_object_sha256_matched": True,
        "aws_compliance_retention_read_observed": True,
        "signed_provider_identity_independently_verified": False,
        "aws_bucket_ownership_independently_audited": False,
        "external_archive_immutability_end_to_end_verified": False,
        "external_write_freeze_achieved": False,
        "legal_source_rights_verified": False,
        "research_release_status": "HOLD",
    }
    if (report["object_lock_mode"] != "COMPLIANCE" or
        any(observation.get(k) != v for k, v in expected_fixed.items()) or
        not isinstance(observation.get("head_request_id_sha256"), str) or
        not HEX.fullmatch(observation["head_request_id_sha256"]) or
        not isinstance(observation.get("retention_request_id_sha256"), str) or
        not HEX.fullmatch(observation["retention_request_id_sha256"])):
        raise S3VerificationError("Offline observed S3 contract invalid.")
    issued = _date(observation.get("observed_at_utc"))
    retain = _date(observation["retention_until_utc"])
    if retain <= issued:
        raise S3VerificationError("Observed retention not active.")
    mac = observation.get("observation_hmac")
    unsigned = {k: v for k, v in observation.items()
                if k != "observation_hmac"}
    if (not isinstance(mac, str) or not HEX.fullmatch(mac) or
        not hmac.compare_digest(mac, _sign(unsigned, local_key))):
        raise S3VerificationError("Offline observation integrity failed.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    for name in ("inspect", "verify"):
        op = sub.add_parser(name)
        for arg in ("source-file", "source-record", "receipt", "witness",
                    "capture-manifest", "trusted-policy", "archive-report",
                    "signed-statement"):
            op.add_argument("--" + arg, type=Path, required=True)
        op.add_argument("--aws-region", required=True)
        op.add_argument("--expected-bucket-owner", required=True)
        op.add_argument("--local-key-file", type=Path)
        if name == "inspect":
            op.add_argument("--aws-profile", required=True)
            op.add_argument("--ack-live-aws-read-only", action="store_true")
            op.add_argument("--output", type=Path, required=True)
        else:
            op.add_argument("--observation", type=Path, required=True)
    args = p.parse_args(argv)
    if args.action == "inspect" and not args.ack_live_aws_read_only:
        print("[BLOCKED] Explicit live read-only AWS authorization required.")
        return 2
    try:
        record = _load_json(args.source_record, MAX_RECORD_BYTES)
        receipt = _load_json(args.receipt, MAX_RECEIPT_BYTES)
        witness = _load_json(args.witness, MAX_WITNESS_BYTES)
        capture = _load_json(args.capture_manifest, MAX_CAPTURE_BYTES)
        policy = _strict_json(args.trusted_policy, MAX_POLICY_BYTES)
        report = _strict_json(args.archive_report, MAX_ARCHIVE_BYTES)
        statement = _strict_json(args.signed_statement, MAX_ATTESTATION_BYTES)
        key = load_token(args.local_key_file or signature_key_path())
        common = dict(
            policy=policy, report=report, statement=statement,
            record=record, receipt=receipt, witness=witness, capture=capture,
            source_file=args.source_file, local_key=key,
            account=args.expected_bucket_owner, region=args.aws_region,
        )
        if args.action == "inspect":
            # Do not even create an SDK client until the full local
            # chain has been cryptographically checked.
            _chain(policy, report, statement, record, receipt, witness,
                   capture, args.source_file, key)
            client = live_s3_client(
                profile=args.aws_profile, region=args.aws_region,
                account=args.expected_bucket_owner)
            output = observe_s3_version(client, **common)
            _write_private(args.output, output)
        else:
            output = _strict_json(args.observation, 16_384)
            verify_observation(output, **common)
        print("[OK] Versioned S3 metadata evidence validated; "
              "external immutable archive not independently certified; HOLD.")
        return 0
    except (S3VerificationError, AttestationError, ValueError, TypeError,
            KeyError, OSError):
        print("[FAIL] S3 versioned archive evidence rejected or unavailable.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
