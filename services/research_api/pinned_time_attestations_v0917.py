"""v0.9.17 externally pinned Ed25519 time attestations over two AWS receipts.

This verifies separately issued, domain-separated signatures over the
EXACT hashes of v0.9.15 governance receipts. The timestamp authority
key is a separately pinned public key, *not* the signed anchor's key.
Only keys/signatures and strict chronology are verified: the software
does not mint production attestations, contact a timestamp service,
validate RFC3161, certify authority identity, or guarantee 24/7 WORM.
"""
from __future__ import annotations

import base64
import binascii
from hashlib import sha256
import hmac
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from scripts.external_archive_attestation import _date
from services.research_api.audit_export_v0911 import canonical_bytes
from services.research_api.anchor_governance_recheck_v0916 import (
    verify_anchor_governance_comparison,
)

SCHEMA = "0.9.17"
STAMP_DOMAIN = b"dviros/third-party-audit-observation-time/v0.9.17\n"
PAIR_DOMAIN = b"dviros/pinned-observation-time-pair/v0.9.17\n"
MAX_REPORT_BYTES = 8192
MAX_ATTESTATION_BYTES = 2048
MAX_LAG_SECONDS = 900
MIN_INTERVAL_SECONDS = 86400
HEX = re.compile(r"^[a-f0-9]{64}$")
NAME = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")
POLICY_KEYS = frozenset({"schema_version", "trust_status", "authorities"})
AUTH_KEYS = frozenset({"authority_id", "role", "ed25519_public_key_b64"})
TOKEN_KEYS = frozenset({"statement", "signature_b64"})
STATEMENT_KEYS = frozenset({
    "schema_version", "scope", "authority_id", "signed_anchor_sha256",
    "binding_sha256", "subject_observation_sha256", "issued_at_utc",
    "request_nonce_sha256",
})
RESULT_KEYS = frozenset({
    "schema_version", "scope", "paired_comparison_sha256",
    "first_observation_sha256", "second_observation_sha256",
    "first_timestamp_attestation_sha256",
    "second_timestamp_attestation_sha256",
    "first_attested_at_utc", "second_attested_at_utc",
    "signed_interval_seconds", "maximum_stamp_delay_seconds",
    "pinned_authority_id", "pinned_ed25519_time_signatures_verified",
    "two_governance_receipts_verified", "independent_timestamp_service_contacted",
    "authority_identity_independently_accredited", "rfc3161_token_verified",
    "continuous_object_lock_verified", "source_rights_verified",
    "graph_snapshot_verified", "research_release_status",
    "local_comparison_hmac_sha256",
})


class PinnedTimeError(ValueError):
    """Sanitized errors: never echo AWS identifiers, private data or keys."""


def _hex(value: object) -> str:
    if type(value) is not str or HEX.fullmatch(value) is None:
        raise PinnedTimeError("Malformed timestamp digest.")
    return value


def _b64(value: object, length: int) -> bytes:
    if type(value) is not str or not 1 <= len(value) <= 120:
        raise PinnedTimeError("Invalid time-signature encoding.")
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise PinnedTimeError("Invalid time-signature encoding.") from None
    if (len(raw) != length or
            base64.b64encode(raw).decode("ascii") != value):
        raise PinnedTimeError("Invalid time-signature length.")
    return raw


def _policy_keys(policy: object, anchor_policy: object) -> dict[str, bytes]:
    if (not isinstance(policy, dict) or set(policy) != POLICY_KEYS or
            policy["schema_version"] != SCHEMA or
            policy["trust_status"] !=
                "OPERATOR_PINNED_EXTERNAL_TIME_ISSUER_NOT_ACCREDITED"):
        raise PinnedTimeError("Unapproved time-authority pin policy.")
    entries = policy["authorities"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= 4:
        raise PinnedTimeError("Invalid number of time-authority pins.")
    if not isinstance(anchor_policy, dict) or not isinstance(
            anchor_policy.get("signers"), list):
        raise PinnedTimeError("Missing separately pinned anchor signers.")
    try:
        anchor_keys = {
            _b64(entry["ed25519_public_key_b64"], 32)
            for entry in anchor_policy["signers"]
        }
    except (KeyError, ValueError, TypeError, PinnedTimeError):
        raise PinnedTimeError("Malformed anchor signer public key.") from None
    result = {}
    used = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != AUTH_KEYS:
            raise PinnedTimeError("Time-authority policy entry invalid.")
        name, role = entry["authority_id"], entry["role"]
        if type(name) is not str or not NAME.fullmatch(name) or (
                role != "external_receipt_timestamp_signer"):
            raise PinnedTimeError("Unrecognized time-authority role.")
        key = _b64(entry["ed25519_public_key_b64"], 32)
        if name in result or key in used or key in anchor_keys:
            raise PinnedTimeError("Time signer duplicates anchor/operator key.")
        result[name] = key
        used.add(key)
    return result


def _verify_one(token: object, *, trusted: dict[str, bytes],
                receipt: dict, paired: dict) -> tuple[str, str, str]:
    if not isinstance(token, dict) or set(token) != TOKEN_KEYS:
        raise PinnedTimeError("Time attestation envelope invalid.")
    statement = token["statement"]
    if not isinstance(statement, dict) or set(statement) != STATEMENT_KEYS:
        raise PinnedTimeError("Time attestation statement invalid.")
    if (statement["schema_version"] != SCHEMA or
            statement["scope"] != "signed_governance_receipt_sha256" or
            type(statement["authority_id"]) is not str or
            statement["authority_id"] not in trusted or
            statement["signed_anchor_sha256"] != paired["signed_anchor_sha256"] or
            statement["binding_sha256"] != paired["binding_sha256"] or
            statement["subject_observation_sha256"] !=
                sha256(canonical_bytes(receipt)).hexdigest()):
        raise PinnedTimeError("Timestamp subject/scope does not match.")
    nonce = _hex(statement["request_nonce_sha256"])
    try:
        issued = _date(statement["issued_at_utc"])
        observed = _date(receipt["observed_at_utc"])
    except (ValueError, TypeError, OverflowError):
        raise PinnedTimeError("Time attestation timestamp malformed.") from None
    delay = (issued - observed).total_seconds()
    if not 0 <= delay <= MAX_LAG_SECONDS:
        raise PinnedTimeError("Timestamp does not promptly follow receipt.")
    raw = canonical_bytes(statement)
    if len(raw) > MAX_ATTESTATION_BYTES:
        raise PinnedTimeError("Timestamp statement size exceeded.")
    try:
        Ed25519PublicKey.from_public_bytes(
            trusted[statement["authority_id"]]).verify(
                _b64(token["signature_b64"], 64), STAMP_DOMAIN + raw,
            )
    except (InvalidSignature, ValueError):
        raise PinnedTimeError("Time-attestation signature invalid.") from None
    return statement["authority_id"], statement["issued_at_utc"], nonce


def _mac(unsigned: dict, key: str) -> str:
    if type(key) is not str or not 40 <= len(key) <= 256:
        raise PinnedTimeError("Protected comparison key invalid.")
    data = canonical_bytes(unsigned)
    if len(data) > MAX_REPORT_BYTES:
        raise PinnedTimeError("Time attestation comparison oversized.")
    return hmac.new(
        key.encode("utf-8"), PAIR_DOMAIN + data, sha256,
    ).hexdigest()


def compare_pinned_times(
    first: dict, second: dict, paired: dict,
    first_timestamp: dict, second_timestamp: dict, *,
    time_policy: dict, envelope: dict, pin_policy: dict,
    signed_bytes: bytes, binding: dict, local_key: str,
) -> dict:
    """Offline-only: issuer-signed times bind to fully verified AWS receipts."""
    try:
        proof = verify_anchor_governance_comparison(
            paired, first, second, envelope=envelope, pin_policy=pin_policy,
            signed_bytes=signed_bytes, binding=binding, local_key=local_key,
        )
        if proof["two_local_observation_hmacs_verified"] is not True:
            raise PinnedTimeError("Unverified governance receipt comparison.")
        trusted = _policy_keys(time_policy, pin_policy)
        first_id, first_time, first_nonce = _verify_one(
            first_timestamp, trusted=trusted, receipt=first, paired=paired)
        second_id, second_time, second_nonce = _verify_one(
            second_timestamp, trusted=trusted, receipt=second, paired=paired)
        if first_id != second_id or first_nonce == second_nonce:
            raise PinnedTimeError("Time authority changed or replayed nonce.")
        delta = (_date(second_time) - _date(first_time)).total_seconds()
        if not MIN_INTERVAL_SECONDS <= delta <= 31 * 86400:
            raise PinnedTimeError("Signed timestamps violate interval bound.")
        report = {
            "schema_version": SCHEMA,
            "scope": "two_pinned_external_signatures_over_governance_receipts",
            "paired_comparison_sha256":
                sha256(canonical_bytes(paired)).hexdigest(),
            "first_observation_sha256":
                sha256(canonical_bytes(first)).hexdigest(),
            "second_observation_sha256":
                sha256(canonical_bytes(second)).hexdigest(),
            "first_timestamp_attestation_sha256":
                sha256(canonical_bytes(first_timestamp)).hexdigest(),
            "second_timestamp_attestation_sha256":
                sha256(canonical_bytes(second_timestamp)).hexdigest(),
            "first_attested_at_utc": first_time,
            "second_attested_at_utc": second_time,
            "signed_interval_seconds": int(delta),
            "maximum_stamp_delay_seconds": MAX_LAG_SECONDS,
            "pinned_authority_id": first_id,
            "pinned_ed25519_time_signatures_verified": True,
            "two_governance_receipts_verified": True,
            "independent_timestamp_service_contacted": False,
            "authority_identity_independently_accredited": False,
            "rfc3161_token_verified": False,
            "continuous_object_lock_verified": False,
            "source_rights_verified": False,
            "graph_snapshot_verified": False,
            "research_release_status": "HOLD",
        }
        result = {
            **report, "local_comparison_hmac_sha256": _mac(report, local_key),
        }
        if len(canonical_bytes(result)) > MAX_REPORT_BYTES:
            raise PinnedTimeError("Time comparison report size exceeded.")
        return result
    except (ValueError, TypeError, KeyError, OverflowError):
        raise PinnedTimeError("Time-attested governance comparison refused.") from None


def verify_pinned_time_comparison(
    value: object, first: dict, second: dict, paired: dict,
    first_timestamp: dict, second_timestamp: dict, *,
    time_policy: dict, envelope: dict, pin_policy: dict,
    signed_bytes: bytes, binding: dict, local_key: str,
) -> dict:
    """Recalculate every signature, receipt and exact comparison offline."""
    if not isinstance(value, dict) or set(value) != RESULT_KEYS:
        raise PinnedTimeError("Time comparison report shape invalid.")
    expected = compare_pinned_times(
        first, second, paired, first_timestamp, second_timestamp,
        time_policy=time_policy, envelope=envelope, pin_policy=pin_policy,
        signed_bytes=signed_bytes, binding=binding, local_key=local_key,
    )
    claimed = _hex(value["local_comparison_hmac_sha256"])
    if (not hmac.compare_digest(
            claimed, expected["local_comparison_hmac_sha256"]) or
            value != expected):
        raise PinnedTimeError("Time comparison was altered.")
    return {
        "schema_version": SCHEMA,
        "two_pinned_ed25519_time_attestations_verified": True,
        "two_source_governance_receipts_verified": True,
        "signed_time_interval_verified": True,
        "real_timestamp_service_contacted": False,
        "issuer_independently_accredited": False,
        "rfc3161_token_verified": False,
        "continuous_object_lock_verified": False,
        "research_release_status": "HOLD",
    }
