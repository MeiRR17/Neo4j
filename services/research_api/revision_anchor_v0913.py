"""v0.9.13 independently keyed, pinned Ed25519 audit-ledger checkpoint.

A checkpoint records one *verified observation-ledger chain prefix*, not a
snapshot of Work/Evidence or an S3 Object Lock guarantee. Its signature
binds the checkpoint to a separately pinned public key. Comparison against
live Neo4j detects loss/rewrite of the anchored prefix, but cannot prove
continuous storage immutability, issuer identity, source rights or chronology.
"""
from __future__ import annotations

import base64
import binascii
from hashlib import sha256
import hmac
import re
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat,
)

from services.research_api.audit_export_v0911 import canonical_bytes
from services.research_api.revision_ledger_v0912 import (
    HISTORY_READ, MAX_REVISIONS, RECORD_COLUMNS, RevisionLedgerError,
    ZERO_CHAIN, scope_id, verify_revision_chain,
)

SCHEMA = "0.9.13"
DOMAIN = b"dviros/audit-revision-pinned-anchor/v0.9.13\n"
MAX_ANCHOR_BYTES = 8192
MAX_POLICY_SIGNERS = 8
HEX = re.compile(r"^[a-f0-9]{64}$")
SIGNER = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")
ANCHOR_KEYS = frozenset({
    "schema_version", "scope_id", "source_work_id", "target_work_id",
    "anchored_sequence", "anchored_revision_id", "anchored_chain_sha256",
    "captured_at_unix", "evidence_scope", "ledger_chain_verified_at_capture",
    "graph_snapshot_verified", "source_graph_immutable",
    "external_object_lock_verified", "signer_identity_independently_verified",
    "source_rights_verified", "research_release_status",
})
ENVELOPE_KEYS = frozenset({
    "anchor", "anchor_sha256", "signer_id", "signature_b64",
})
POLICY_KEYS = frozenset({"schema_version", "trust_status", "signers"})
POLICY_ENTRY_KEYS = frozenset({
    "signer_id", "role", "scope_id", "ed25519_public_key_b64",
})


class AnchorError(ValueError):
    """Deliberately sanitized: never include source metadata or key data."""


def _hex(value: object) -> str:
    if type(value) is not str or not HEX.fullmatch(value):
        raise AnchorError("Invalid anchored chain digest.")
    return value


def _b64(value: object, n: int) -> bytes:
    if type(value) is not str or not 1 <= len(value) <= 120:
        raise AnchorError("Invalid anchor key/signature encoding.")
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise AnchorError("Invalid anchor key/signature encoding.") from None
    if (len(raw) != n or
            base64.b64encode(raw).decode("ascii") != value):
        raise AnchorError("Invalid anchor key/signature length.")
    return raw


def _anchor(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != ANCHOR_KEYS:
        raise AnchorError("Invalid anchor statement projection.")
    try:
        expected_scope = scope_id(
            value["source_work_id"], value["target_work_id"])
    except (RevisionLedgerError, ValueError, TypeError):
        raise AnchorError("Invalid anchor Work scope.") from None
    sequence = value["anchored_sequence"]
    at = value["captured_at_unix"]
    if (value["schema_version"] != SCHEMA or
            value["scope_id"] != expected_scope or
            type(sequence) is not int or not 0 <= sequence <= MAX_REVISIONS or
            type(at) is not int or not 0 <= at <= 4102444800 or
            value["evidence_scope"] != "observed_metadata_revision_prefix_only" or
            value["ledger_chain_verified_at_capture"] is not True or
            any(value[k] is not False for k in (
                "graph_snapshot_verified", "source_graph_immutable",
                "external_object_lock_verified",
                "signer_identity_independently_verified",
                "source_rights_verified",
            )) or
            value["research_release_status"] != "HOLD"):
        raise AnchorError("Anchor scope or research claims invalid.")
    digest = _hex(value["anchored_chain_sha256"])
    revision_id = value["anchored_revision_id"]
    if (sequence == 0 and
            (revision_id != "" or digest != ZERO_CHAIN)):
        raise AnchorError("Empty anchor head invalid.")
    if (sequence > 0 and
            (type(revision_id) is not str or
             revision_id != "audit-rev:" + digest)):
        raise AnchorError("Nonempty anchor revision ID invalid.")
    if len(canonical_bytes(value)) > MAX_ANCHOR_BYTES:
        raise AnchorError("Anchor statement too large.")
    return value


def capture_anchor(client, source: str, target: str, *,
                   now: int | None = None) -> dict:
    """Read an entire bounded chain and capture the verified head."""
    report = verify_revision_chain(client, source, target)
    at = int(time.time()) if now is None else now
    item = {
        "schema_version": SCHEMA,
        "scope_id": report["scope_id"],
        "source_work_id": source,
        "target_work_id": target,
        "anchored_sequence": report["current_sequence"],
        "anchored_revision_id": report["latest_revision_id"],
        "anchored_chain_sha256": report["chain_sha256"],
        "captured_at_unix": at,
        "evidence_scope": "observed_metadata_revision_prefix_only",
        "ledger_chain_verified_at_capture": True,
        "graph_snapshot_verified": False,
        "source_graph_immutable": False,
        "external_object_lock_verified": False,
        "signer_identity_independently_verified": False,
        "source_rights_verified": False,
        "research_release_status": "HOLD",
    }
    return _anchor(item)


def sign_anchor(anchor: dict, *, signer_id: str,
                private_key_bytes: bytes) -> dict:
    """Sign with a separate 32-byte Ed25519 raw private key, never export it."""
    _anchor(anchor)
    if type(signer_id) is not str or not SIGNER.fullmatch(signer_id):
        raise AnchorError("Invalid anchor signer ID.")
    if type(private_key_bytes) is not bytes or len(private_key_bytes) != 32:
        raise AnchorError("Protected anchor signing key must be raw Ed25519.")
    try:
        signer = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
        raw = canonical_bytes(anchor)
        signature = signer.sign(DOMAIN + raw)
    except (ValueError, TypeError):
        raise AnchorError("Invalid protected Ed25519 signing key.") from None
    return {
        "anchor": anchor,
        "anchor_sha256": sha256(raw).hexdigest(),
        "signer_id": signer_id,
        "signature_b64": base64.b64encode(signature).decode("ascii"),
    }


def _pinned_key(policy: object, signer_id: str, scope: str) -> bytes:
    if (not isinstance(policy, dict) or set(policy) != POLICY_KEYS or
            policy["schema_version"] != SCHEMA or
            policy["trust_status"] != "OPERATOR_PINNED_IDENTITY_NOT_ATTESTED"):
        raise AnchorError("Untrusted anchor verification policy.")
    entries = policy["signers"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_POLICY_SIGNERS:
        raise AnchorError("Invalid number of pinned anchor signers.")
    seen = set()
    selected = None
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != POLICY_ENTRY_KEYS:
            raise AnchorError("Pinned signer entry invalid.")
        name, sid, role = entry["signer_id"], entry["scope_id"], entry["role"]
        if (type(name) is not str or not SIGNER.fullmatch(name) or
                name in seen or role != "audit_revision_operator" or
                type(sid) is not str or
                not re.fullmatch(r"audit-scope:[a-f0-9]{64}", sid)):
            raise AnchorError("Pinned signer identity or scope invalid.")
        seen.add(name)
        pub = _b64(entry["ed25519_public_key_b64"], 32)
        if name == signer_id and sid == scope:
            selected = pub
    if selected is None:
        raise AnchorError("Signer not pinned for this Work scope.")
    return selected


def verify_anchor(envelope: object, policy: object) -> dict:
    """Validate only cryptographic key possession and exact anchor scope."""
    if not isinstance(envelope, dict) or set(envelope) != ENVELOPE_KEYS:
        raise AnchorError("Signed anchor envelope invalid.")
    anchor = _anchor(envelope["anchor"])
    signer_id = envelope["signer_id"]
    if type(signer_id) is not str or not SIGNER.fullmatch(signer_id):
        raise AnchorError("Anchor signer ID invalid.")
    raw = canonical_bytes(anchor)
    digest = sha256(raw).hexdigest()
    provided = _hex(envelope["anchor_sha256"])
    if not hmac.compare_digest(digest, provided):
        raise AnchorError("Anchor content SHA-256 mismatch.")
    pub = _pinned_key(policy, signer_id, anchor["scope_id"])
    try:
        Ed25519PublicKey.from_public_bytes(pub).verify(
            _b64(envelope["signature_b64"], 64), DOMAIN + raw)
    except (ValueError, InvalidSignature):
        raise AnchorError("Pinned anchor signature mismatch.") from None
    return {
        "schema_version": SCHEMA,
        "anchor_sha256": digest,
        "signature_verified_against_pinned_public_key": True,
        "anchored_sequence": anchor["anchored_sequence"],
        "signer_identity_independently_verified": False,
        "graph_snapshot_verified": False,
        "source_graph_immutable": False,
        "external_object_lock_verified": False,
        "source_rights_verified": False,
        "research_release_status": "HOLD",
    }


def compare_anchor_to_live(client, envelope: object, policy: object) -> dict:
    """Detect loss/change of an independently signed ledger *prefix*.

    New revisions after the anchor are allowed only if the anchored
    revision/digest is still at the same index in the verified chain.
    """
    proof = verify_anchor(envelope, policy)
    anchor = envelope["anchor"]
    try:
        live = verify_revision_chain(
            client, anchor["source_work_id"], anchor["target_work_id"])
    except (RevisionLedgerError, ValueError, TypeError):
        raise AnchorError("Live audit ledger integrity verification failed.") from None
    seq = anchor["anchored_sequence"]
    if (live["scope_id"] != anchor["scope_id"] or
            live["current_sequence"] < seq):
        raise AnchorError("Anchored ledger prefix was truncated or replaced.")
    if seq == 0:
        if anchor["anchored_chain_sha256"] != ZERO_CHAIN:
            raise AnchorError("Anchor zero-root invalid.")
    elif seq == live["current_sequence"]:
        if (not hmac.compare_digest(
                live["chain_sha256"], anchor["anchored_chain_sha256"]) or
                live["latest_revision_id"] != anchor["anchored_revision_id"]):
            raise AnchorError("Anchored ledger head changed.")
    else:
        rows = client.query(
            HISTORY_READ, {
                "scope_id": anchor["scope_id"],
                "fetch_limit": MAX_REVISIONS + 1,
            })
        if (not isinstance(rows, list) or
                len(rows) != live["current_sequence"]):
            raise AnchorError("Anchored ledger history changed during reread.")
        record = rows[seq-1]
        if (not isinstance(record, list) or len(record) != len(RECORD_COLUMNS)):
            raise AnchorError("Anchored ledger projection invalid.")
        item = dict(zip(RECORD_COLUMNS, record))
        if (item["sequence"] != seq or
                item["id"] != anchor["anchored_revision_id"] or
                not hmac.compare_digest(
                    str(item["chain_sha256"]), anchor["anchored_chain_sha256"])):
            raise AnchorError("Anchored revision was rewritten.")
        # Detect a concurrent head change between the two reads.
        recheck = verify_revision_chain(
            client, anchor["source_work_id"], anchor["target_work_id"])
        if (recheck["current_sequence"] != live["current_sequence"] or
                recheck["chain_sha256"] != live["chain_sha256"]):
            raise AnchorError("Ledger changed during anchor verification.")
    return {
        **proof,
        "live_prefix_matches_pinned_anchor": True,
        "current_sequence": live["current_sequence"],
        "revisions_after_anchor": live["current_sequence"] - seq,
        "database_integrity_checked_at_observation": True,
        "continuous_storage_immutability_verified": False,
        "research_release_status": "HOLD",
    }
