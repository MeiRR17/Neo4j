#!/usr/bin/env python3
"""v0.8.14 independently keyed Ed25519 archive-claim verification.

The operator supplies a pinned trust policy, a separately signed statement,
and a provider-report-shaped JSON claim. No archive API is contacted; a valid
signature proves only that the pinned key signed the exact claim. It does NOT
establish provider identity, object-lock configuration, storage immutability,
source rights, Neo4j snapshot isolation, or permission to release research.
"""
from __future__ import annotations

import argparse
import base64
import binascii
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from scripts.search_capture import digest, encode
from scripts.search_review_workflow import _write_private
from scripts.source_membership import MAX_WITNESS_BYTES, verify_witness
from scripts.source_receipts import (
    MAX_CAPTURE_BYTES, MAX_RECORD_BYTES, MAX_RECEIPT_BYTES, _load_json,
)
from services.research_api.config import load_token
from services.research_api.signature import signature_key_path

SCHEMA = "0.8.14"
DOMAIN = b"neo4j-external-archive-attestation-v0.8.14\n"
MAX_POLICY_BYTES = 16_384
MAX_ARCHIVE_BYTES = 16_384
MAX_ATTESTATION_BYTES = 16_384
MAX_OBJECT_BYTES = 512 * 1024 * 1024
HEX = re.compile(r"^[0-9a-f]{64}$")
SIGNER = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")
OBJECT_ID = re.compile(r"^[A-Za-z0-9_.+/-]{1,180}$")
BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{2,62}$")
VERSION = re.compile(r"^[A-Za-z0-9!._~+/-]{1,180}$")
UTC_TIME = re.compile(r"^20[2-9][0-9]-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z$")
REPORT_KEYS = frozenset({
    "schema_version", "provider", "bucket", "object_key", "version_id",
    "content_sha256", "content_length", "object_lock_mode",
    "retain_until_utc", "evidence_origin",
})
STATEMENT_KEYS = frozenset({
    "schema_version", "purpose", "signer_id", "archive_namespace",
    "source_record_id", "source_receipt_sha256", "source_witness_sha256",
    "capture_manifest_sha256", "archive_report_sha256", "issued_at_utc",
    "provider_identity_independently_verified", "source_rights_verified",
    "research_release_status",
})


class AttestationError(ValueError):
    """Do not print private file paths, source IDs, archive paths, or secrets."""


def _strict_json(path: Path, budget: int) -> dict:
    p = Path(path)
    if p.is_symlink() or p.parent.is_symlink():
        raise AttestationError("Symlinked attestation input rejected.")
    try:
        s = p.stat()
        if (not stat.S_ISREG(s.st_mode) or s.st_size > budget or
            s.st_size == 0 or s.st_mode & 0o022):
            raise AttestationError("Attestation input permissions/bounds invalid.")
        with p.open("rb") as f:
            raw = f.read(budget + 1)
        if len(raw) > budget:
            raise AttestationError("Attestation input exceeds file budget.")

        def unique(pairs):
            obj = {}
            for k, v in pairs:
                if k in obj:
                    raise ValueError("Duplicate JSON property.")
                obj[k] = v
            return obj

        data = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    except (OSError, UnicodeError, ValueError):
        raise AttestationError("Private attestation JSON invalid.") from None
    if not isinstance(data, dict):
        raise AttestationError("Private attestation must be an object.")
    return data


def _b64(value: object, size: int) -> bytes:
    if not isinstance(value, str) or len(value) > 100:
        raise AttestationError("Signature/key encoding invalid.")
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise AttestationError("Signature/key base64 invalid.") from None
    if len(raw) != size or base64.b64encode(raw).decode("ascii") != value:
        raise AttestationError("Signature/key size or encoding invalid.")
    return raw


def _date(value: object) -> datetime:
    if not isinstance(value, str) or not UTC_TIME.fullmatch(value):
        raise AttestationError("Attestation timestamp not strict UTC.")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise AttestationError("Attestation timestamp invalid.") from None


def _trust(policy: object, signer_id: str, namespace: str) -> bytes:
    if (not isinstance(policy, dict) or set(policy) != {
        "schema_version", "trust_status", "signers"
    } or policy["schema_version"] != SCHEMA or
        policy["trust_status"] != "OPERATOR_PINNED_IDENTITY_NOT_ATTESTED"):
        raise AttestationError("Unpinned trust policy or unknown schema.")
    entries = policy["signers"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= 8:
        raise AttestationError("Trusted signer count invalid.")
    seen = set()
    found = None
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) != {
            "signer_id", "role", "archive_namespace", "ed25519_public_key_b64"
        }):
            raise AttestationError("Trusted signer entry malformed.")
        name, role, scope = (
            entry["signer_id"], entry["role"], entry["archive_namespace"])
        if (not isinstance(name, str) or not SIGNER.fullmatch(name) or
            name in seen or role != "archive_operator" or
            not isinstance(scope, str) or not SIGNER.fullmatch(scope)):
            raise AttestationError("Duplicate or invalid trust signer/scope.")
        seen.add(name)
        pub = _b64(entry["ed25519_public_key_b64"], 32)
        if name == signer_id and scope == namespace:
            found = pub
    if found is None:
        raise AttestationError("No pinned signer for claimed archive namespace.")
    return found


def _archive(report: object, source_receipt: dict) -> None:
    if not isinstance(report, dict) or set(report) != REPORT_KEYS or (
        report["schema_version"] != SCHEMA or
        report["provider"] != "s3_object_lock" or
        report["evidence_origin"] != "operator_supplied_unverified"
    ):
        raise AttestationError("Archive report scope or schema invalid.")
    for value, pat in ((report["bucket"], BUCKET),
                       (report["object_key"], OBJECT_ID),
                       (report["version_id"], VERSION)):
        if not isinstance(value, str) or not pat.fullmatch(value) or (
            ".." in value or value.startswith("/")
        ):
            raise AttestationError("Archive object identity invalid.")
    if (report["object_lock_mode"] not in ("COMPLIANCE", "GOVERNANCE") or
        not isinstance(report["content_sha256"], str) or
        not HEX.fullmatch(report["content_sha256"]) or
        report["content_sha256"] != source_receipt["observed_raw_file_sha256"] or
        type(report["content_length"]) is not int or
        not 1 <= report["content_length"] <= MAX_OBJECT_BYTES or
        report["content_length"] != source_receipt["observed_file_size_bytes"]):
        raise AttestationError("Archive claim does not bind retained source bytes.")
    _date(report["retain_until_utc"])


def verify_attestation(
    policy: dict, report: dict, envelope: dict, *,
    source_record: dict, receipt: dict, witness: dict,
    capture: dict, source_file: Path, local_key: str,
) -> dict:
    # The existing v0.8.13 witness, v0.8.12 receipt, v0.8.11 capture
    # and exact local file bytes MUST already agree before public-key trust.
    try:
        verify_witness(witness, source_record, receipt, source_file,
                       capture, key=local_key)
    except (ValueError, TypeError, KeyError, OSError):
        raise AttestationError("Local witness/file/capture chain invalid.") from None
    if not isinstance(envelope, dict) or set(envelope) != {
        "statement", "signature_b64"
    }:
        raise AttestationError("Signed statement envelope invalid.")
    s = envelope["statement"]
    if not isinstance(s, dict) or set(s) != STATEMENT_KEYS or (
        s["schema_version"] != SCHEMA or
        s["purpose"] != "archival_operator_attests_report_claim" or
        s["provider_identity_independently_verified"] is not False or
        s["source_rights_verified"] is not False or
        s["research_release_status"] != "HOLD"):
        raise AttestationError("Signed statement claims unauthorized approval.")
    pub = _trust(policy, s["signer_id"], s["archive_namespace"])
    _archive(report, receipt)
    issued, retained = _date(s["issued_at_utc"]), _date(report["retain_until_utc"])
    if retained <= issued:
        raise AttestationError("Claimed archive retention ends before issuance.")
    for claim, actual in (
        ("source_record_id", witness["source_record_id"]),
        ("source_receipt_sha256", digest(encode(receipt))),
        ("source_witness_sha256", digest(encode(witness))),
        ("capture_manifest_sha256", digest(encode(capture))),
        ("archive_report_sha256", digest(encode(report))),
    ):
        if s[claim] != actual:
            raise AttestationError("Attestation refers to a different source chain.")
    try:
        Ed25519PublicKey.from_public_bytes(pub).verify(
            _b64(envelope["signature_b64"], 64),
            DOMAIN + encode(s))
    except (InvalidSignature, ValueError):
        raise AttestationError("Pinned Ed25519 signature verification failed.") from None
    # Strong only about cryptographic signature and the locally verified
    # source evidence. This does NOT independently check an S3 response.
    return {
        "schema_version": SCHEMA,
        "verification_scope": "operator_pinned_ed25519_signature_on_archive_claim",
        "signed_statement_sha256": digest(encode(s)),
        "archive_report_sha256": digest(encode(report)),
        "trust_policy_sha256": digest(encode(policy)),
        "pinned_public_key_sha256": digest(pub),
        "source_record_id": witness["source_record_id"],
        "source_witness_sha256": digest(encode(witness)),
        "pinned_key_signature_valid": True,
        "operator_key_possession_proven": True,
        "signer_organization_identity_independently_verified": False,
        "remote_object_existence_independently_verified": False,
        "s3_object_lock_configuration_independently_verified": False,
        "external_archive_immutability_verified": False,
        "source_provider_identity_verified": False,
        "source_rights_verified": False,
        "neo4j_snapshot_isolation_verified": False,
        "research_release_status": "HOLD",
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-file", type=Path, required=True)
    p.add_argument("--source-record", type=Path, required=True)
    p.add_argument("--receipt", type=Path, required=True)
    p.add_argument("--witness", type=Path, required=True)
    p.add_argument("--capture-manifest", type=Path, required=True)
    p.add_argument("--trusted-policy", type=Path, required=True)
    p.add_argument("--archive-report", type=Path, required=True)
    p.add_argument("--signed-statement", type=Path, required=True)
    p.add_argument("--local-key-file", type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)
    try:
        result = verify_attestation(
            _strict_json(args.trusted_policy, MAX_POLICY_BYTES),
            _strict_json(args.archive_report, MAX_ARCHIVE_BYTES),
            _strict_json(args.signed_statement, MAX_ATTESTATION_BYTES),
            source_record=_load_json(args.source_record, MAX_RECORD_BYTES),
            receipt=_load_json(args.receipt, MAX_RECEIPT_BYTES),
            witness=_load_json(args.witness, MAX_WITNESS_BYTES),
            capture=_load_json(args.capture_manifest, MAX_CAPTURE_BYTES),
            source_file=args.source_file,
            local_key=load_token(args.local_key_file or signature_key_path()),
        )
        _write_private(args.output, result)
        print("[OK] Pinned Ed25519 archive-claim signature verified; "
              "external immutability=NOT VERIFIED; research_release=HOLD.")
        return 0
    except (AttestationError, ValueError, TypeError, KeyError, OSError):
        print("[FAIL] Archive attestation, trust policy or source chain rejected.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
