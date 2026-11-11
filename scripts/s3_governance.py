#!/usr/bin/env python3
"""v0.8.16: observe S3 bucket governance and repeat version audits over time.

An opt-in read-only audit over the v0.8.11-15 signed local source chain:
(1) exact-version S3 HEAD/checksum/ObjectLock retention (v0.8.15);
(2) STS caller account; (3) four bucket-level S3 control reads.

Separate HMAC observations may be compared at least 24h apart. Repeated
point-in-time observations do NOT prove continuous WORM protection,
organizational identity, full IAM/SCP/AccessPoint policy, source rights
or scientific production readiness. Every report preserves HOLD.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import hmac
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.external_archive_attestation import (
    MAX_POLICY_BYTES, MAX_ARCHIVE_BYTES, MAX_ATTESTATION_BYTES,
    _strict_json, _date,
)
from scripts.live_s3_version_verify import (
    _identity, _request_id, _chain, observe_s3_version,
    verify_observation, REGION, ACCOUNT,
)
from scripts.search_capture import digest, encode
from scripts.search_review_workflow import _write_private
from scripts.source_membership import MAX_WITNESS_BYTES
from scripts.source_receipts import (
    MAX_CAPTURE_BYTES, MAX_RECORD_BYTES, MAX_RECEIPT_BYTES, _load_json,
)
from services.research_api.config import load_token
from services.research_api.signature import signature_key_path

SCHEMA = "0.8.16"
DOMAIN = b"neo4j-s3-governance-observation-v0.8.16\n"
CONTINUITY_DOMAIN = b"neo4j-s3-governance-two-observations-v0.8.16\n"
MIN_INTERVAL_SECONDS = 24 * 3600
MAX_OBSERVATION_BYTES = 32_768
HEX = re.compile(r"^[a-f0-9]{64}$")
SCOPE = "read_only_s3_bucket_controls_plus_exact_version_metadata"
CONTROL_KEYS = frozenset({
    "schema_version", "scope", "live_version_observation",
    "observed_at_utc", "aws_region", "expected_bucket_owner_sha256",
    "caller_arn_sha256", "caller_user_id_sha256",
    "sts_request_id_sha256", "bucket_read_request_ids_sha256",
    "aws_sts_caller_account_matches_expected_owner",
    "aws_bucket_versioning_enabled",
    "aws_bucket_public_access_block_all_four_enabled",
    "aws_bucket_policy_status_nonpublic",
    "aws_bucket_object_lock_enabled",
    "read_only_bucket_control_checks_completed",
    "full_iam_scp_access_points_policy_verified",
    "bucket_policy_contents_semantically_audited",
    "archive_continuously_immutable_verified",
    "signer_organization_independently_verified",
    "legal_source_rights_verified", "research_release_status",
    "observation_hmac",
})
BUCKET_CALLS = (
    "get_bucket_versioning",
    "get_public_access_block",
    "get_bucket_policy_status",
    "get_object_lock_configuration",
)
BLOCK_KEYS = frozenset({
    "BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy",
    "RestrictPublicBuckets",
})
FALSE_FLAGS = (
    "full_iam_scp_access_points_policy_verified",
    "bucket_policy_contents_semantically_audited",
    "archive_continuously_immutable_verified",
    "signer_organization_independently_verified",
    "legal_source_rights_verified",
)
TRUE_FLAGS = (
    "aws_sts_caller_account_matches_expected_owner",
    "aws_bucket_versioning_enabled",
    "aws_bucket_public_access_block_all_four_enabled",
    "aws_bucket_policy_status_nonpublic",
    "aws_bucket_object_lock_enabled",
    "read_only_bucket_control_checks_completed",
)
CONTINUITY_KEYS = frozenset({
    "schema_version", "scope", "first_observation_sha256",
    "second_observation_sha256", "same_exact_source_and_object_version",
    "distinct_aws_read_request_ids", "minimum_interval_seconds",
    "observed_interval_seconds", "repeated_compliance_checks_observed",
    "continuous_retention_independently_proven",
    "trusted_external_timestamp_verified",
    "research_release_status", "comparison_hmac",
})


class GovernanceError(ValueError):
    """Fixed messages prevent source, bucket and credential disclosure."""


def _sign(body: dict, key: str, domain: bytes = DOMAIN) -> str:
    if not isinstance(key, str) or len(key) < 40:
        raise GovernanceError("Private observation key unavailable.")
    return hmac.new(
        key.encode("utf-8"), domain + encode(body), hashlib.sha256
    ).hexdigest()


def _hex(value: object) -> bool:
    return isinstance(value, str) and HEX.fullmatch(value) is not None


def _status(response: object) -> str:
    try:
        return _request_id(response)
    except (ValueError, TypeError, KeyError):
        raise GovernanceError("AWS control request not authenticated as success.") from None


def _caller(sts: object, account: str) -> tuple[str, str, str]:
    try:
        response = sts.get_caller_identity()
    except Exception:
        raise GovernanceError("AWS STS identity request failed.") from None
    request_id = _status(response)
    if not isinstance(response, dict) or response.get("Account") != account:
        raise GovernanceError("AWS caller account does not match pinned bucket owner.")
    arn = response.get("Arn")
    user = response.get("UserId")
    permitted = (
        "arn:aws:sts::" + account + ":assumed-role/",
        "arn:aws:iam::" + account + ":user/",
    )
    if (not isinstance(arn, str) or not 30 <= len(arn) <= 350 or
        not arn.startswith(permitted) or
        not isinstance(user, str) or not 1 <= len(user) <= 350):
        raise GovernanceError("AWS caller role/user identity is malformed.")
    return digest(arn.encode()), digest(user.encode()), request_id


def live_clients(*, profile: str, region: str, account: str):
    """One explicitly configured AWS credential session; fixed TLS endpoints."""
    try:
        _identity(profile, region, account)
        import boto3
        from botocore.config import Config
        session = boto3.Session(profile_name=profile, region_name=region)
        kwargs = dict(
            region_name=region,
            config=Config(
                retries={"max_attempts": 1, "mode": "standard"},
                connect_timeout=5, read_timeout=10,
            ),
        )
        sts = session.client(
            "sts", endpoint_url="https://sts." + region + ".amazonaws.com",
            **kwargs)
        s3 = session.client(
            "s3", endpoint_url="https://s3." + region + ".amazonaws.com",
            region_name=region,
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 1, "mode": "standard"},
                connect_timeout=5, read_timeout=10,
                s3={"addressing_style": "virtual"},
            ))
    except Exception:
        raise GovernanceError("Explicit AWS SDK profile/region unavailable.") from None
    return s3, sts


def _bucket_controls(s3, *, bucket: str, account: str) -> dict:
    args = {"Bucket": bucket, "ExpectedBucketOwner": account}
    values = {}
    requests = {}
    try:
        for method in BUCKET_CALLS:
            response = getattr(s3, method)(**args)
            requests[method] = _status(response)
            values[method] = response
    except Exception:
        raise GovernanceError("Read-only S3 bucket governance request failed.") from None
    v = values["get_bucket_versioning"]
    public = values["get_public_access_block"]
    status = values["get_bucket_policy_status"]
    locked = values["get_object_lock_configuration"]
    if not isinstance(v, dict) or v.get("Status") != "Enabled":
        raise GovernanceError("S3 bucket versioning not enabled.")
    blocks = public.get("PublicAccessBlockConfiguration") if isinstance(public, dict) else None
    if not isinstance(blocks, dict) or not BLOCK_KEYS.issubset(blocks) or (
        any(blocks[k] is not True for k in BLOCK_KEYS)
    ):
        raise GovernanceError("S3 bucket public access block not fully enabled.")
    policy = status.get("PolicyStatus") if isinstance(status, dict) else None
    if not isinstance(policy, dict) or policy.get("IsPublic") is not False:
        raise GovernanceError("S3 reports public or indeterminate bucket policy.")
    cfg = locked.get("ObjectLockConfiguration") if isinstance(locked, dict) else None
    if not isinstance(cfg, dict) or cfg.get("ObjectLockEnabled") != "Enabled":
        raise GovernanceError("S3 bucket Object Lock not enabled.")
    return requests


def observe_governance(
    s3, sts, *, policy: dict, report: dict, statement: dict,
    record: dict, receipt: dict, witness: dict, capture: dict,
    source_file: Path, local_key: str, account: str, region: str,
    observed_at: datetime | None = None,
) -> dict:
    """No request runs until v0.8.11–14 source/statement chain passes."""
    if not isinstance(account, str) or not ACCOUNT.fullmatch(account) or (
        not isinstance(region, str) or not REGION.fullmatch(region)
    ):
        raise GovernanceError("Expected S3 owner/region not pinned.")
    try:
        _chain(policy, report, statement, record, receipt, witness,
               capture, source_file, local_key)
    except (ValueError, TypeError, KeyError, OSError):
        raise GovernanceError("Upstream source/Ed25519 evidence invalid.") from None
    version = observe_s3_version(
        s3, policy=policy, report=report, statement=statement,
        record=record, receipt=receipt, witness=witness, capture=capture,
        source_file=source_file, local_key=local_key,
        account=account, region=region, observed_at=observed_at)
    caller_arn, caller_user, sts_req = _caller(sts, account)
    bucket_ids = _bucket_controls(
        s3, bucket=report["bucket"], account=account)
    unsigned = {
        "schema_version": SCHEMA, "scope": SCOPE,
        "live_version_observation": version,
        "observed_at_utc": version["observed_at_utc"],
        "aws_region": region,
        "expected_bucket_owner_sha256": digest(account.encode("ascii")),
        "caller_arn_sha256": caller_arn,
        "caller_user_id_sha256": caller_user,
        "sts_request_id_sha256": sts_req,
        "bucket_read_request_ids_sha256": bucket_ids,
        "aws_sts_caller_account_matches_expected_owner": True,
        "aws_bucket_versioning_enabled": True,
        "aws_bucket_public_access_block_all_four_enabled": True,
        "aws_bucket_policy_status_nonpublic": True,
        "aws_bucket_object_lock_enabled": True,
        "read_only_bucket_control_checks_completed": True,
        "full_iam_scp_access_points_policy_verified": False,
        "bucket_policy_contents_semantically_audited": False,
        "archive_continuously_immutable_verified": False,
        "signer_organization_independently_verified": False,
        "legal_source_rights_verified": False,
        "research_release_status": "HOLD",
    }
    return {**unsigned, "observation_hmac": _sign(unsigned, local_key)}


def verify_governance(
    value: object, *, policy: dict, report: dict, statement: dict,
    record: dict, receipt: dict, witness: dict, capture: dict,
    source_file: Path, local_key: str, account: str, region: str,
) -> None:
    """Offline validation; does not make AWS requests or assert current state."""
    if not isinstance(value, dict) or set(value) != CONTROL_KEYS:
        raise GovernanceError("Governance observation envelope invalid.")
    if (value["schema_version"] != SCHEMA or value["scope"] != SCOPE or
        value["research_release_status"] != "HOLD" or
        any(value[k] is not False for k in FALSE_FLAGS) or
        any(value[k] is not True for k in TRUE_FLAGS)):
        raise GovernanceError("Governance trust flags altered.")
    if (value["aws_region"] != region or
        value["expected_bucket_owner_sha256"] != digest(account.encode("ascii"))):
        raise GovernanceError("Governance observation owner/region differs.")
    for key in ("caller_arn_sha256", "caller_user_id_sha256",
                "sts_request_id_sha256"):
        if not _hex(value[key]):
            raise GovernanceError("Governance caller evidence malformed.")
    requests = value["bucket_read_request_ids_sha256"]
    if (not isinstance(requests, dict) or set(requests) != set(BUCKET_CALLS)
        or any(not _hex(v) for v in requests.values())):
        raise GovernanceError("Governance request trace malformed.")
    try:
        verify_observation(
            value["live_version_observation"],
            policy=policy, report=report, statement=statement,
            record=record, receipt=receipt, witness=witness,
            capture=capture, source_file=source_file, local_key=local_key,
            account=account, region=region)
    except (ValueError, TypeError, KeyError, OSError):
        raise GovernanceError("Nested S3 version evidence invalid.") from None
    if value["observed_at_utc"] != (
        value["live_version_observation"]["observed_at_utc"]
    ):
        raise GovernanceError("Governance observation timestamp mismatch.")
    unsigned = {k: v for k, v in value.items() if k != "observation_hmac"}
    mac = value["observation_hmac"]
    if (not _hex(mac) or not hmac.compare_digest(
        mac, _sign(unsigned, local_key)
    )):
        raise GovernanceError("Governance observation HMAC invalid.")


def compare_governance(
    previous: dict, current: dict, *, policy: dict, report: dict,
    statement: dict, record: dict, receipt: dict, witness: dict,
    capture: dict, source_file: Path, local_key: str,
    account: str, region: str,
) -> dict:
    """At least two separated point-in-time reads; never claim 24/7 proof."""
    common = dict(
        policy=policy, report=report, statement=statement,
        record=record, receipt=receipt, witness=witness,
        capture=capture, source_file=source_file, local_key=local_key,
        account=account, region=region)
    verify_governance(previous, **common)
    verify_governance(current, **common)
    a = _date(previous["observed_at_utc"])
    b = _date(current["observed_at_utc"])
    seconds = int((b - a).total_seconds())
    if seconds < MIN_INTERVAL_SECONDS:
        raise GovernanceError("Independent governance observations less than 24h apart.")
    first, second = (
        previous["live_version_observation"],
        current["live_version_observation"])
    if (first["observed_version_id_sha256"] != second["observed_version_id_sha256"] or
        first["source_witness_sha256"] != second["source_witness_sha256"] or
        first["attested_claim_sha256"] != second["attested_claim_sha256"] or
        first["head_request_id_sha256"] == second["head_request_id_sha256"] or
        first["retention_request_id_sha256"] == second["retention_request_id_sha256"] or
        previous["sts_request_id_sha256"] == current["sts_request_id_sha256"]):
        raise GovernanceError("Governance recheck source or request identity invalid.")
    unsigned = {
        "schema_version": SCHEMA,
        "scope": "two_signed_point_in_time_s3_governance_observations",
        "first_observation_sha256": digest(encode(previous)),
        "second_observation_sha256": digest(encode(current)),
        "same_exact_source_and_object_version": True,
        "distinct_aws_read_request_ids": True,
        "minimum_interval_seconds": MIN_INTERVAL_SECONDS,
        "observed_interval_seconds": seconds,
        "repeated_compliance_checks_observed": True,
        "continuous_retention_independently_proven": False,
        "trusted_external_timestamp_verified": False,
        "research_release_status": "HOLD",
    }
    return {**unsigned, "comparison_hmac":
            _sign(unsigned, local_key, CONTINUITY_DOMAIN)}


def verify_comparison(
    result: object, previous: dict, current: dict, **kwargs,
) -> None:
    if (not isinstance(result, dict) or set(result) != CONTINUITY_KEYS):
        raise GovernanceError("Continuity comparison schema invalid.")
    expected = compare_governance(previous, current, **kwargs)
    if result != expected:
        raise GovernanceError("Continuity comparison signature/data mismatch.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for mode in ("inspect", "verify", "compare"):
        p = sub.add_parser(mode)
        for name in (
            "source-file", "source-record", "receipt", "witness",
            "capture-manifest", "trusted-policy", "archive-report",
            "signed-statement",
        ):
            p.add_argument("--" + name, type=Path, required=True)
        p.add_argument("--aws-region", required=True)
        p.add_argument("--expected-bucket-owner", required=True)
        p.add_argument("--local-key-file", type=Path)
        if mode == "inspect":
            p.add_argument("--aws-profile", required=True)
            p.add_argument("--ack-live-aws-read-only", action="store_true")
            p.add_argument("--output", type=Path, required=True)
        elif mode == "verify":
            p.add_argument("--observation", type=Path, required=True)
        else:
            p.add_argument("--previous", type=Path, required=True)
            p.add_argument("--current", type=Path, required=True)
            p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action == "inspect" and not args.ack_live_aws_read_only:
        print("[BLOCKED] Explicit authorized read-only AWS governance audit required.")
        return 2
    try:
        key = load_token(args.local_key_file or signature_key_path())
        record = _load_json(args.source_record, MAX_RECORD_BYTES)
        receipt = _load_json(args.receipt, MAX_RECEIPT_BYTES)
        witness = _load_json(args.witness, MAX_WITNESS_BYTES)
        capture = _load_json(args.capture_manifest, MAX_CAPTURE_BYTES)
        policy = _strict_json(args.trusted_policy, MAX_POLICY_BYTES)
        report = _strict_json(args.archive_report, MAX_ARCHIVE_BYTES)
        statement = _strict_json(args.signed_statement, MAX_ATTESTATION_BYTES)
        common = dict(
            policy=policy, report=report, statement=statement,
            record=record, receipt=receipt, witness=witness, capture=capture,
            source_file=args.source_file, local_key=key,
            account=args.expected_bucket_owner, region=args.aws_region)
        if args.action == "inspect":
            # Authenticate local evidence before even constructing the
            # AWS SDK clients or reading any remote bucket configuration.
            _chain(policy, report, statement, record, receipt,
                   witness, capture, args.source_file, key)
            s3, sts = live_clients(
                profile=args.aws_profile, region=args.aws_region,
                account=args.expected_bucket_owner)
            result = observe_governance(s3, sts, **common)
            _write_private(args.output, result)
        elif args.action == "verify":
            verify_governance(
                _strict_json(args.observation, MAX_OBSERVATION_BYTES),
                **common)
        else:
            result = compare_governance(
                _strict_json(args.previous, MAX_OBSERVATION_BYTES),
                _strict_json(args.current, MAX_OBSERVATION_BYTES), **common)
            _write_private(args.output, result)
        print("[OK] Read-only S3 governance metadata validated; "
              "continuous external immutability NOT VERIFIED; HOLD.")
        return 0
    except (GovernanceError, ValueError, TypeError, KeyError, OSError):
        print("[FAIL] S3 governance observation rejected or unavailable.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
