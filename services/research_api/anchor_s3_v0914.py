"""v0.9.14 read-only, exact-version S3 retention proof for signed audit anchors.

The operator independently pins AWS bucket/key/version/owner/region, a
minimum retention date, and the EXACT bytes of a v0.9.13 signed anchor.
Only after offline Ed25519 verification and local byte matching are
HEAD (FULL_OBJECT SHA256) and GetObjectRetention called for that
specific object version. No S3 writes, downloads or unpinned endpoints.
An observation is point-in-time evidence, not perpetual WORM assurance,
independent signer identity, source rights or graph snapshot isolation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import hmac
import re

from scripts.external_archive_attestation import (
    BUCKET, OBJECT_ID, VERSION, _date,
)
from scripts.live_s3_version_verify import (
    ACCOUNT, REGION, _datetime, _request_id, _sha256_from_s3, _utc,
)
from services.research_api.audit_export_v0911 import canonical_bytes
from services.research_api.revision_anchor_v0913 import verify_anchor

SCHEMA = "0.9.14"
DOMAIN = b"dviros/audit-anchor-s3-exact-version-observation/v0.9.14\n"
MAX_ANCHOR_FILE_BYTES = 16_384
MAX_BINDING_BYTES = 8192
MAX_OBSERVATION_BYTES = 8192
HEX = re.compile(r"^[0-9a-f]{64}$")
BINDING_KEYS = frozenset({
    "schema_version", "provider", "bucket", "object_key", "version_id",
    "expected_bucket_owner", "aws_region", "content_sha256",
    "content_length", "minimum_retain_until_utc", "evidence_origin",
})
OBS_KEYS = frozenset({
    "schema_version", "scope", "binding_sha256", "signed_anchor_sha256",
    "anchor_file_sha256", "anchor_file_size_bytes", "anchored_sequence",
    "aws_region", "expected_bucket_owner_sha256", "version_id_sha256",
    "observed_at_utc", "retention_until_utc", "head_request_id_sha256",
    "retention_request_id_sha256", "observed_full_object_sha256",
    "observed_full_object_checksum_type",
    "pinned_signature_verified", "aws_exact_version_head_observed",
    "aws_full_object_sha256_matched",
    "aws_compliance_retention_observed",
    "external_archive_continuously_immutable_verified",
    "independent_signer_identity_verified", "source_rights_verified",
    "graph_snapshot_verified", "research_release_status",
    "local_observation_hmac",
})
TRUE_FLAGS = (
    "pinned_signature_verified", "aws_exact_version_head_observed",
    "aws_full_object_sha256_matched", "aws_compliance_retention_observed",
)
FALSE_FLAGS = (
    "external_archive_continuously_immutable_verified",
    "independent_signer_identity_verified", "source_rights_verified",
    "graph_snapshot_verified",
)


class AnchorArchiveError(ValueError):
    """Sanitized error; never include private object identifiers or keys."""


def _hex(value: object) -> str:
    if type(value) is not str or not HEX.fullmatch(value):
        raise AnchorArchiveError("Invalid anchor archive digest.")
    return value


def _binding(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != BINDING_KEYS:
        raise AnchorArchiveError("Archive binding projection invalid.")
    if (value["schema_version"] != SCHEMA or
            value["provider"] != "aws_s3" or
            value["evidence_origin"] != "operator_pinned_unverified" or
            type(value["bucket"]) is not str or
            not BUCKET.fullmatch(value["bucket"]) or
            type(value["object_key"]) is not str or
            not OBJECT_ID.fullmatch(value["object_key"]) or
            value["object_key"].startswith("/") or
            ".." in value["object_key"] or
            type(value["version_id"]) is not str or
            not VERSION.fullmatch(value["version_id"]) or
            value["version_id"].startswith("/") or
            ".." in value["version_id"] or
            type(value["expected_bucket_owner"]) is not str or
            not ACCOUNT.fullmatch(value["expected_bucket_owner"]) or
            type(value["aws_region"]) is not str or
            not REGION.fullmatch(value["aws_region"]) or
            type(value["content_length"]) is not int or
            not 1 <= value["content_length"] <= MAX_ANCHOR_FILE_BYTES):
        raise AnchorArchiveError("Invalid exact-version operator binding.")
    _hex(value["content_sha256"])
    try:
        minimum = _date(value["minimum_retain_until_utc"])
    except (ValueError, TypeError):
        raise AnchorArchiveError("Invalid retention minimum.") from None
    if minimum.year > 2100 or len(canonical_bytes(value)) > MAX_BINDING_BYTES:
        raise AnchorArchiveError("Operator archive binding exceeds bounds.")
    return value


def _local_chain(envelope: object, pin_policy: object,
                 signed_bytes: bytes, binding: object) -> tuple[dict, str]:
    if (type(signed_bytes) is not bytes or
            not 1 <= len(signed_bytes) <= MAX_ANCHOR_FILE_BYTES):
        raise AnchorArchiveError("Exact signed anchor bytes unavailable.")
    b = _binding(binding)
    try:
        signature = verify_anchor(envelope, pin_policy)
    except (TypeError, ValueError, KeyError):
        raise AnchorArchiveError("Pinned anchor signature invalid.") from None
    if (signature["signature_verified_against_pinned_public_key"] is not True or
            signature["research_release_status"] != "HOLD" or
            b["content_length"] != len(signed_bytes) or
            not hmac.compare_digest(
                _hex(b["content_sha256"]), sha256(signed_bytes).hexdigest()
            )):
        raise AnchorArchiveError("Pinned signed-anchor byte binding mismatch.")
    return signature, sha256(signed_bytes).hexdigest()


def _mac(unsigned: dict, local_key: str) -> str:
    if type(local_key) is not str or not 40 <= len(local_key) <= 256:
        raise AnchorArchiveError("Local observation key unavailable.")
    return hmac.new(
        local_key.encode("utf-8"), DOMAIN + canonical_bytes(unsigned),
        sha256,
    ).hexdigest()


def observe_anchor_s3_version(
    client, *, envelope: dict, pin_policy: dict, signed_bytes: bytes,
    binding: dict, local_key: str, observed_at: datetime | None = None,
) -> dict:
    """Perform exactly two read-only, explicit-version AWS SDK operations."""
    verified, local_digest = _local_chain(
        envelope, pin_policy, signed_bytes, binding)
    now = (_datetime(observed_at) if observed_at is not None
           else datetime.now(timezone.utc))
    try:
        minimum = _date(binding["minimum_retain_until_utc"])
    except (TypeError, ValueError):
        raise AnchorArchiveError("Invalid operator retention date.") from None
    if minimum <= now:
        raise AnchorArchiveError("Required retention minimum already passed.")
    # Ensure a missing HMAC key cannot be found only after remote requests.
    _mac({"preflight": local_digest}, local_key)
    params = {
        "Bucket": binding["bucket"], "Key": binding["object_key"],
        "VersionId": binding["version_id"],
        "ExpectedBucketOwner": binding["expected_bucket_owner"],
    }
    try:
        head = client.head_object(**params, ChecksumMode="ENABLED")
        retention_response = client.get_object_retention(**params)
    except Exception:
        raise AnchorArchiveError("Read-only AWS exact-version check failed.") from None
    try:
        head_request = _request_id(head)
        retention_request = _request_id(retention_response)
        if (head.get("VersionId") != binding["version_id"] or
                head.get("DeleteMarker") is True or
                type(head.get("ContentLength")) is not int or
                head["ContentLength"] != len(signed_bytes) or
                head.get("ChecksumType") != "FULL_OBJECT" or
                head.get("ObjectLockMode") != "COMPLIANCE"):
            raise AnchorArchiveError("AWS version/content length/lock invalid.")
        observed_sha = _sha256_from_s3(head.get("ChecksumSHA256"))
        if not hmac.compare_digest(observed_sha, local_digest):
            raise AnchorArchiveError("S3 full-object hash differs from local bytes.")
        lock = retention_response.get("Retention")
        if not isinstance(lock, dict) or lock.get("Mode") != "COMPLIANCE":
            raise AnchorArchiveError("S3 COMPLIANCE Object Lock not observed.")
        retain = _datetime(lock.get("RetainUntilDate"))
        head_retain = _datetime(head.get("ObjectLockRetainUntilDate"))
        if retain != head_retain or retain < minimum or retain <= now:
            raise AnchorArchiveError("S3 retention expiry below pinned minimum.")
    except (TypeError, ValueError, KeyError):
        raise AnchorArchiveError("AWS exact-version metadata validation failed.") from None

    unsigned = {
        "schema_version": SCHEMA,
        "scope": "read_only_exact_s3_anchor_version_head_and_retention",
        "binding_sha256": sha256(canonical_bytes(binding)).hexdigest(),
        "signed_anchor_sha256": verified["anchor_sha256"],
        "anchor_file_sha256": local_digest,
        "anchor_file_size_bytes": len(signed_bytes),
        "anchored_sequence": verified["anchored_sequence"],
        "aws_region": binding["aws_region"],
        "expected_bucket_owner_sha256": sha256(
            binding["expected_bucket_owner"].encode("ascii")).hexdigest(),
        "version_id_sha256": sha256(
            binding["version_id"].encode("utf-8")).hexdigest(),
        "observed_at_utc": _utc(now),
        "retention_until_utc": _utc(retain),
        "head_request_id_sha256": head_request,
        "retention_request_id_sha256": retention_request,
        "observed_full_object_sha256": observed_sha,
        "observed_full_object_checksum_type": "FULL_OBJECT",
        "pinned_signature_verified": True,
        "aws_exact_version_head_observed": True,
        "aws_full_object_sha256_matched": True,
        "aws_compliance_retention_observed": True,
        "external_archive_continuously_immutable_verified": False,
        "independent_signer_identity_verified": False,
        "source_rights_verified": False,
        "graph_snapshot_verified": False,
        "research_release_status": "HOLD",
    }
    report = {**unsigned, "local_observation_hmac": _mac(unsigned, local_key)}
    if len(canonical_bytes(report)) > MAX_OBSERVATION_BYTES:
        raise AnchorArchiveError("S3 anchor observation too large.")
    return report


def verify_anchor_s3_observation(
    value: object, *, envelope: dict, pin_policy: dict,
    signed_bytes: bytes, binding: dict, local_key: str,
) -> dict:
    """Offline only: verifies captured observation, not *current* AWS state."""
    signature, local_digest = _local_chain(
        envelope, pin_policy, signed_bytes, binding)
    if not isinstance(value, dict) or set(value) != OBS_KEYS:
        raise AnchorArchiveError("Untrusted archived observation projection.")
    fixed = {
        "schema_version": SCHEMA,
        "scope": "read_only_exact_s3_anchor_version_head_and_retention",
        "binding_sha256": sha256(canonical_bytes(binding)).hexdigest(),
        "signed_anchor_sha256": signature["anchor_sha256"],
        "anchor_file_sha256": local_digest,
        "anchor_file_size_bytes": len(signed_bytes),
        "anchored_sequence": signature["anchored_sequence"],
        "aws_region": binding["aws_region"],
        "expected_bucket_owner_sha256": sha256(
            binding["expected_bucket_owner"].encode("ascii")).hexdigest(),
        "version_id_sha256": sha256(
            binding["version_id"].encode("utf-8")).hexdigest(),
        "observed_full_object_sha256": local_digest,
        "observed_full_object_checksum_type": "FULL_OBJECT",
        "research_release_status": "HOLD",
    }
    if (any(type(value.get(k)) is not type(v) or value.get(k) != v
            for k, v in fixed.items()) or
            any(value[k] is not True for k in TRUE_FLAGS) or
            any(value[k] is not False for k in FALSE_FLAGS)):
        raise AnchorArchiveError("Archived S3 observation scope invalid.")
    for name in ("head_request_id_sha256", "retention_request_id_sha256"):
        _hex(value[name])
    try:
        observed = _date(value["observed_at_utc"])
        retain = _date(value["retention_until_utc"])
        minimum = _date(binding["minimum_retain_until_utc"])
    except (ValueError, TypeError):
        raise AnchorArchiveError("Archived S3 timestamps invalid.") from None
    if observed >= retain or retain < minimum or minimum <= observed:
        raise AnchorArchiveError("Observed S3 retention invalid.")
    expected_mac = _mac(
        {k:v for k,v in value.items() if k != "local_observation_hmac"},
        local_key)
    mac = _hex(value["local_observation_hmac"])
    if not hmac.compare_digest(mac, expected_mac):
        raise AnchorArchiveError("S3 observation HMAC invalid.")
    if len(canonical_bytes(value)) > MAX_OBSERVATION_BYTES:
        raise AnchorArchiveError("S3 observation exceeded size budget.")
    return {
        "schema_version": SCHEMA,
        "exact_version_checksum_and_retention_report_verified": True,
        "independently_pinned_anchor_signature_verified": True,
        "offline_local_observation_hmac_verified": True,
        "aws_current_state_rechecked": False,
        "external_archive_continuously_immutable_verified": False,
        "independent_signer_identity_verified": False,
        "source_rights_verified": False,
        "graph_snapshot_verified": False,
        "research_release_status": "HOLD",
    }
