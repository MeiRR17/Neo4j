"""v0.9.16 offline time-separated S3 anchor-governance observations.

Compares two independently collected and locally HMAC-verified v0.9.15
reports on the *same pinned signed anchor and exact S3 object version*.
Requires >=24 hours according to untrusted local observation clocks,
distinct metadata request IDs, and non-decreasing COMPLIANCE retention.
This is NOT an externally trusted timestamp, continuous Object Lock
proof, complete IAM/SCP review or scholarly/source-rights approval.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import hmac
import re

from scripts.external_archive_attestation import _date
from scripts.s3_governance import BUCKET_CALLS
from services.research_api.anchor_governance_v0915 import (
    AnchorGovernanceError, verify_anchor_governance,
)
from services.research_api.anchor_s3_v0914 import (
    _binding, _local_chain,
)
from services.research_api.audit_export_v0911 import canonical_bytes

SCHEMA = "0.9.16"
MIN_INTERVAL_SECONDS = 86_400
MAX_REPORT_BYTES = 16_384
DOMAIN = b"dviros/audit-anchor-two-governance-observations/v0.9.16\n"
HEX = re.compile(r"^[0-9a-f]{64}$")
REPORT_KEYS = frozenset({
    "schema_version", "scope", "first_observation_sha256",
    "second_observation_sha256", "binding_sha256",
    "signed_anchor_sha256", "exact_version_id_sha256",
    "full_object_sha256", "first_observed_at_utc",
    "second_observed_at_utc", "first_retention_until_utc",
    "second_retention_until_utc", "minimum_interval_seconds",
    "observed_interval_seconds", "same_exact_object_version",
    "same_signed_anchor_bytes", "distinct_provider_request_ids",
    "two_compliance_retention_reads_observed",
    "nondecreasing_retention_observed",
    "aws_real_time_continuity_proven", "external_timestamp_verified",
    "full_iam_scp_access_points_policy_verified",
    "source_rights_verified", "graph_snapshot_verified",
    "research_release_status", "comparison_hmac_sha256",
})
TRUE_FLAGS = (
    "same_exact_object_version",
    "same_signed_anchor_bytes",
    "distinct_provider_request_ids",
    "two_compliance_retention_reads_observed",
    "nondecreasing_retention_observed",
)
FALSE_FLAGS = (
    "aws_real_time_continuity_proven",
    "external_timestamp_verified",
    "full_iam_scp_access_points_policy_verified",
    "source_rights_verified",
    "graph_snapshot_verified",
)
NESTED_FIXED = (
    "binding_sha256", "signed_anchor_sha256",
    "anchor_file_sha256", "anchor_file_size_bytes",
    "anchored_sequence", "aws_region",
    "expected_bucket_owner_sha256", "version_id_sha256",
    "observed_full_object_sha256", "observed_full_object_checksum_type",
)


class AnchorRecheckError(ValueError):
    """Sanitized refusal without bucket, signer or source details."""


def _sha(value: object) -> str:
    if type(value) is not str or HEX.fullmatch(value) is None:
        raise AnchorRecheckError("Malformed anchor comparison digest.")
    return value


def _mac(body: dict, key: str) -> str:
    if type(key) is not str or not 40 <= len(key) <= 256:
        raise AnchorRecheckError("Protected comparison key unavailable.")
    encoded = canonical_bytes(body)
    if len(encoded) > MAX_REPORT_BYTES:
        raise AnchorRecheckError("Anchor comparison exceeded size budget.")
    return hmac.new(
        key.encode("utf-8"), DOMAIN + encoded, sha256,
    ).hexdigest()


def _ids(report: dict) -> set[str]:
    nested = report["exact_version_observation"]
    ids = [
        nested["head_request_id_sha256"],
        nested["retention_request_id_sha256"],
        report["sts_request_id_sha256"],
    ]
    bucket = report["bucket_read_request_ids_sha256"]
    if not isinstance(bucket, dict) or set(bucket) != set(BUCKET_CALLS):
        raise AnchorRecheckError("Bucket request set malformed.")
    ids.extend(bucket[name] for name in BUCKET_CALLS)
    for value in ids:
        _sha(value)
    if len(ids) != 7 or len(set(ids)) != 7:
        raise AnchorRecheckError("Provider request identities repeated.")
    return set(ids)


def _reconcile(
    first: object, second: object, *, envelope: dict, pin_policy: dict,
    signed_bytes: bytes, binding: dict, local_key: str,
) -> dict:
    """Only signed offline materials. No AWS or Neo4j access."""
    try:
        _local_chain(envelope, pin_policy, signed_bytes, binding)
        _binding(binding)
        common = dict(
            envelope=envelope, pin_policy=pin_policy,
            signed_bytes=signed_bytes, binding=binding, local_key=local_key,
        )
        a = verify_anchor_governance(first, **common)
        b = verify_anchor_governance(second, **common)
        if (a["offline_version_and_bucket_governance_hmac_verified"] is not True
                or b["offline_version_and_bucket_governance_hmac_verified"] is not True):
            raise AnchorRecheckError("Governance receipts unverified.")
        one = first["exact_version_observation"]
        two = second["exact_version_observation"]
        for key in NESTED_FIXED:
            if one[key] != two[key]:
                raise AnchorRecheckError("Pinned anchor/version identity changed.")
        for key in ("binding_sha256", "signed_anchor_sha256",
                    "aws_region", "expected_bucket_owner_sha256"):
            if first[key] != second[key]:
                raise AnchorRecheckError("Operator-pinned scope changed.")
        previous_at = _date(first["observed_at_utc"])
        current_at = _date(second["observed_at_utc"])
        previous_retention = _date(one["retention_until_utc"])
        current_retention = _date(two["retention_until_utc"])
        if (not isinstance(previous_at, datetime) or
                not isinstance(current_at, datetime) or
                current_at <= previous_at):
            raise AnchorRecheckError("Observation order invalid.")
        interval = (current_at - previous_at).total_seconds()
        if interval < MIN_INTERVAL_SECONDS:
            raise AnchorRecheckError("Independent observations too close.")
        if current_retention < previous_retention:
            raise AnchorRecheckError("COMPLIANCE retention decreased.")
        if _ids(first) & _ids(second):
            raise AnchorRecheckError("Reused provider request identity.")
        # Two intact HMAC reports are evidence of two observations, not a
        # trusted independent clock nor a guarantee about intervening time.
        result = {
            "schema_version": SCHEMA,
            "scope": "two_time_separated_signed_anchor_s3_governance_reads",
            "first_observation_sha256":
                sha256(canonical_bytes(first)).hexdigest(),
            "second_observation_sha256":
                sha256(canonical_bytes(second)).hexdigest(),
            "binding_sha256": first["binding_sha256"],
            "signed_anchor_sha256": first["signed_anchor_sha256"],
            "exact_version_id_sha256": one["version_id_sha256"],
            "full_object_sha256": one["observed_full_object_sha256"],
            "first_observed_at_utc": first["observed_at_utc"],
            "second_observed_at_utc": second["observed_at_utc"],
            "first_retention_until_utc": one["retention_until_utc"],
            "second_retention_until_utc": two["retention_until_utc"],
            "minimum_interval_seconds": MIN_INTERVAL_SECONDS,
            "observed_interval_seconds": int(interval),
            "same_exact_object_version": True,
            "same_signed_anchor_bytes": True,
            "distinct_provider_request_ids": True,
            "two_compliance_retention_reads_observed": True,
            "nondecreasing_retention_observed": True,
            "aws_real_time_continuity_proven": False,
            "external_timestamp_verified": False,
            "full_iam_scp_access_points_policy_verified": False,
            "source_rights_verified": False,
            "graph_snapshot_verified": False,
            "research_release_status": "HOLD",
        }
        return result
    except (ValueError, TypeError, KeyError, OverflowError):
        raise AnchorRecheckError(
            "Signed anchor observations are incompatible or invalid."
        ) from None


def compare_anchor_governance(
    first: dict, second: dict, *, envelope: dict, pin_policy: dict,
    signed_bytes: bytes, binding: dict, local_key: str,
) -> dict:
    """Issue domain-separated HMAC over a strictly verified comparison."""
    body = _reconcile(
        first, second, envelope=envelope, pin_policy=pin_policy,
        signed_bytes=signed_bytes, binding=binding, local_key=local_key,
    )
    result = {**body, "comparison_hmac_sha256": _mac(body, local_key)}
    if len(canonical_bytes(result)) > MAX_REPORT_BYTES:
        raise AnchorRecheckError("Comparison output over budget.")
    return result


def verify_anchor_governance_comparison(
    value: object, first: dict, second: dict, *,
    envelope: dict, pin_policy: dict, signed_bytes: bytes,
    binding: dict, local_key: str,
) -> dict:
    """Offline deterministic replay of the complete comparison contract."""
    if not isinstance(value, dict) or set(value) != REPORT_KEYS:
        raise AnchorRecheckError("Comparison report fields invalid.")
    expected = compare_anchor_governance(
        first, second, envelope=envelope, pin_policy=pin_policy,
        signed_bytes=signed_bytes, binding=binding, local_key=local_key,
    )
    claimed = _sha(value["comparison_hmac_sha256"])
    if not hmac.compare_digest(
        claimed, expected["comparison_hmac_sha256"],
    ):
        raise AnchorRecheckError("Comparison MAC invalid.")
    if value != expected:
        raise AnchorRecheckError("Comparison content changed.")
    return {
        "schema_version": SCHEMA,
        "two_local_observation_hmacs_verified": True,
        "same_exact_signed_anchor_version_verified": True,
        "time_separation_and_request_uniqueness_checked": True,
        "nondecreasing_compliance_retention_observed": True,
        "aws_current_state_rechecked": False,
        "continuous_archive_immutability_verified": False,
        "trusted_external_timestamp_verified": False,
        "research_release_status": "HOLD",
    }
