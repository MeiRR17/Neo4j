"""v0.9.15 scoped AWS governance observation for a signed audit anchor.

The v0.9.14 exact-version signed-anchor check is completed before STS
and four fixed bucket-level reads. All seven AWS operations are
metadata-only and bound to the operator-pinned owner/bucket/version.
This is a point-in-time check, not IAM/SCP evaluation, continuous WORM,
immutable Neo4j source data or public research approval.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import hmac
import re

from scripts.s3_governance import (
    BUCKET_CALLS, GovernanceError, _caller, _bucket_controls,
)
from scripts.live_s3_version_verify import _datetime, _utc
from services.research_api.anchor_s3_v0914 import (
    AnchorArchiveError, _binding, _local_chain,
    observe_anchor_s3_version, verify_anchor_s3_observation,
)
from services.research_api.audit_export_v0911 import canonical_bytes

SCHEMA = "0.9.15"
DOMAIN = b"dviros/anchor-s3-governance-observation/v0.9.15\n"
MAX_REPORT_BYTES = 24_576
HEX = re.compile(r"^[0-9a-f]{64}$")
KEYS = frozenset({
    "schema_version", "scope", "exact_version_observation",
    "binding_sha256", "signed_anchor_sha256",
    "observed_at_utc", "aws_region", "expected_bucket_owner_sha256",
    "caller_arn_sha256", "caller_user_id_sha256",
    "sts_request_id_sha256", "bucket_read_request_ids_sha256",
    "aws_sts_caller_account_matches_expected_owner",
    "aws_bucket_versioning_enabled",
    "aws_bucket_public_access_block_all_four_enabled",
    "aws_bucket_policy_status_nonpublic",
    "aws_bucket_object_lock_enabled",
    "read_only_bucket_controls_checked",
    "full_iam_scp_access_points_policy_verified",
    "bucket_policy_contents_semantically_audited",
    "external_archive_continuously_immutable_verified",
    "independent_signer_identity_verified", "source_rights_verified",
    "graph_snapshot_verified", "research_release_status",
    "observation_hmac_sha256",
})
TRUE_FLAGS = (
    "aws_sts_caller_account_matches_expected_owner",
    "aws_bucket_versioning_enabled",
    "aws_bucket_public_access_block_all_four_enabled",
    "aws_bucket_policy_status_nonpublic", "aws_bucket_object_lock_enabled",
    "read_only_bucket_controls_checked",
)
FALSE_FLAGS = (
    "full_iam_scp_access_points_policy_verified",
    "bucket_policy_contents_semantically_audited",
    "external_archive_continuously_immutable_verified",
    "independent_signer_identity_verified", "source_rights_verified",
    "graph_snapshot_verified",
)


class AnchorGovernanceError(ValueError):
    """Sanitized refusal; never reveal bucket, source or AWS identifiers."""


def _hex(v: object) -> str:
    if type(v) is not str or not HEX.fullmatch(v):
        raise AnchorGovernanceError("Invalid governance hash value.")
    return v


def _mac(body: dict, key: str) -> str:
    if type(key) is not str or not 40 <= len(key) <= 256:
        raise AnchorGovernanceError("Governance observation secret unavailable.")
    data = canonical_bytes(body)
    if len(data) > MAX_REPORT_BYTES:
        raise AnchorGovernanceError("Governance report size budget exceeded.")
    return hmac.new(key.encode("utf-8"), DOMAIN + data, sha256).hexdigest()


def observe_anchor_governance(
    s3, sts, *, envelope: dict, pin_policy: dict, signed_bytes: bytes,
    binding: dict, local_key: str, observed_at: datetime | None = None,
) -> dict:
    """Two exact-version S3 reads, one STS read, four bucket S3 reads."""
    try:
        _local_chain(envelope, pin_policy, signed_bytes, binding)
        _mac({"preflight": True}, local_key)
        now = (_datetime(observed_at) if observed_at is not None
               else datetime.now(timezone.utc))
        # Verify pinned file/version and object retention BEFORE any
        # caller or broader bucket-governance metadata requests.
        version = observe_anchor_s3_version(
            s3, envelope=envelope, pin_policy=pin_policy,
            signed_bytes=signed_bytes, binding=binding,
            local_key=local_key, observed_at=now,
        )
        arn, user, sts_id = _caller(
            sts, binding["expected_bucket_owner"])
        bucket_ids = _bucket_controls(
            s3, bucket=binding["bucket"],
            account=binding["expected_bucket_owner"])
    except (ValueError, TypeError, KeyError, GovernanceError):
        raise AnchorGovernanceError(
            "Read-only signed-anchor governance check failed."
        ) from None
    unsigned = {
        "schema_version": SCHEMA,
        "scope": "signed_anchor_exact_version_plus_sts_bucket_controls",
        "exact_version_observation": version,
        "binding_sha256": version["binding_sha256"],
        "signed_anchor_sha256": version["signed_anchor_sha256"],
        "observed_at_utc": version["observed_at_utc"],
        "aws_region": binding["aws_region"],
        "expected_bucket_owner_sha256": version[
            "expected_bucket_owner_sha256"],
        "caller_arn_sha256": arn,
        "caller_user_id_sha256": user,
        "sts_request_id_sha256": sts_id,
        "bucket_read_request_ids_sha256": bucket_ids,
        "aws_sts_caller_account_matches_expected_owner": True,
        "aws_bucket_versioning_enabled": True,
        "aws_bucket_public_access_block_all_four_enabled": True,
        "aws_bucket_policy_status_nonpublic": True,
        "aws_bucket_object_lock_enabled": True,
        "read_only_bucket_controls_checked": True,
        "full_iam_scp_access_points_policy_verified": False,
        "bucket_policy_contents_semantically_audited": False,
        "external_archive_continuously_immutable_verified": False,
        "independent_signer_identity_verified": False,
        "source_rights_verified": False,
        "graph_snapshot_verified": False,
        "research_release_status": "HOLD",
    }
    result = {**unsigned, "observation_hmac_sha256":
              _mac(unsigned, local_key)}
    if len(canonical_bytes(result)) > MAX_REPORT_BYTES:
        raise AnchorGovernanceError("Governance report size budget exceeded.")
    return result


def verify_anchor_governance(
    report: object, *, envelope: dict, pin_policy: dict,
    signed_bytes: bytes, binding: dict, local_key: str,
) -> dict:
    """Offline check of a previous observation; never re-contacts AWS."""
    try:
        _, _ = _local_chain(envelope, pin_policy, signed_bytes, binding)
        _binding(binding)
        if not isinstance(report, dict) or set(report) != KEYS:
            raise AnchorGovernanceError("Governance report fields invalid.")
        version = verify_anchor_s3_observation(
            report["exact_version_observation"],
            envelope=envelope, pin_policy=pin_policy,
            signed_bytes=signed_bytes, binding=binding, local_key=local_key,
        )
        if (version["offline_local_observation_hmac_verified"] is not True or
                version["aws_current_state_rechecked"] is not False):
            raise AnchorGovernanceError("Nested version evidence invalid.")
        nested = report["exact_version_observation"]
        fixed = {
            "schema_version": SCHEMA,
            "scope": "signed_anchor_exact_version_plus_sts_bucket_controls",
            "binding_sha256": nested["binding_sha256"],
            "signed_anchor_sha256": nested["signed_anchor_sha256"],
            "observed_at_utc": nested["observed_at_utc"],
            "aws_region": binding["aws_region"],
            "expected_bucket_owner_sha256":
                nested["expected_bucket_owner_sha256"],
            "research_release_status": "HOLD",
        }
        if any(type(report.get(k)) is not type(v) or report.get(k) != v
               for k, v in fixed.items()):
            raise AnchorGovernanceError("Governance scope or timing mismatch.")
        if any(report[k] is not True for k in TRUE_FLAGS) or any(
                report[k] is not False for k in FALSE_FLAGS):
            raise AnchorGovernanceError("Governance trust flags invalid.")
        for key in ("caller_arn_sha256", "caller_user_id_sha256",
                    "sts_request_id_sha256"):
            _hex(report[key])
        requests = report["bucket_read_request_ids_sha256"]
        if (not isinstance(requests, dict) or
                set(requests) != set(BUCKET_CALLS)):
            raise AnchorGovernanceError("Governance bucket read trace invalid.")
        for val in requests.values():
            _hex(val)
        unsigned = {k: v for k, v in report.items()
                    if k != "observation_hmac_sha256"}
        claimed = _hex(report["observation_hmac_sha256"])
        if not hmac.compare_digest(_mac(unsigned, local_key), claimed):
            raise AnchorGovernanceError("Governance report HMAC mismatch.")
        if len(canonical_bytes(report)) > MAX_REPORT_BYTES:
            raise AnchorGovernanceError("Governance report oversized.")
    except (ValueError, TypeError, KeyError):
        raise AnchorGovernanceError(
            "Saved signed-anchor governance verification failed."
        ) from None
    return {
        "schema_version": SCHEMA,
        "offline_version_and_bucket_governance_hmac_verified": True,
        "exact_version_read_only_observation_verified": True,
        "s3_account_governance_read_only_observation_verified": True,
        "live_aws_state_rechecked": False,
        "full_iam_scp_access_points_policy_verified": False,
        "external_archive_continuously_immutable_verified": False,
        "source_rights_verified": False,
        "graph_snapshot_verified": False,
        "research_release_status": "HOLD",
    }
