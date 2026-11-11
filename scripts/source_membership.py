#!/usr/bin/env python3
"""v0.8.13: private source-membership witness for a captured metadata projection.

Rechecks all bounded SourceRecord metadata pages against the complete SHA256
projection stored in a signed v0.8.11 capture manifest. A particular locally
verified v0.8.12 source receipt must appear as an EXACT row in this projection.

The proof is local and operator-HMAC-authenticated. It does not prove a
transactionally frozen Neo4j graph, original provider identity, source rights,
external immutability or an independent public-key attestation.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.search_capture import (
    CaptureError, SignedLoopbackClient, digest, encode,
)
from scripts.search_provenance import (
    MAX_PAGES, MAX_ROWS, checked_page, target,
)
from scripts.search_review_workflow import _write_private
from scripts.source_receipts import (
    ReceiptError, _capture_binding, _load_json, verify_receipt,
    MAX_RECORD_BYTES, MAX_RECEIPT_BYTES, MAX_CAPTURE_BYTES,
)
from services.research_api.config import load_token
from services.research_api.provenance import safe_provenance_item
from services.research_api.signature import signature_key_path

SCHEMA = "0.8.13"
MAX_WITNESS_BYTES = 512_000
DOMAIN = b"neo4j-bounded-source-membership-v0.8.13\n"
UNSIGNED_KEYS = frozenset({
    "schema_version", "scope", "source_record_id", "source_record_sha256",
    "source_receipt_sha256", "capture_manifest_sha256",
    "captured_source_projection_sha256", "source_projection_record_count",
    "source_projection_missing_checksums", "observed_source_rows",
    "membership_in_bounded_captured_projection",
    "independent_provider_signature_verified",
    "external_immutable_archive_verified", "cross_request_snapshot_isolation",
    "legal_rights_verified", "graph_relationships_covered",
    "research_release_status",
})


class MembershipError(ValueError):
    """Do not include source metadata, file names or credentials in errors."""


def _source_summary(rows: object) -> tuple[str, int, int]:
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise MembershipError("Invalid bounded source projection.")
    sha = hashlib.sha256()
    last = ""
    missing = 0
    for raw in rows:
        try:
            item = safe_provenance_item(raw, "sources")
        except (ValueError, TypeError, RuntimeError):
            raise MembershipError("Source projection metadata invalid.") from None
        if last and item["id"] <= last:
            raise MembershipError("Source projection is not strictly ordered.")
        last = item["id"]
        b = encode(item)
        sha.update(len(b).to_bytes(4, "big"))
        sha.update(b)
        if item["checksum_sha256"] is None:
            missing += 1
    return sha.hexdigest(), len(rows), missing


def collect_source_rows(fetch) -> list[dict]:
    """All visible SourceRecord pages, exactly the v0.8.11 projection stream."""
    cursor = ""
    last = ""
    rows: list[dict] = []
    for _ in range(MAX_PAGES):
        page = fetch(target("sources", cursor))
        try:
            following, safe_rows = checked_page(page, "sources", last)
        except (CaptureError, ValueError, TypeError):
            raise MembershipError("Incomplete or unsafe SourceRecord page.") from None
        if len(rows) + len(safe_rows) > MAX_ROWS:
            raise MembershipError("Source projection exceeds pilot bound.")
        rows.extend(safe_rows)
        if page["search_complete"]:
            return rows
        if not safe_rows or not following or (
            cursor and following <= cursor
        ):
            raise MembershipError("Non-advancing source page cursor.")
        last = safe_rows[-1]["id"]
        cursor = following
    raise MembershipError("Source projection exceeds page budget.")


def _signed_capture_source(capture: object, key: str) -> tuple[dict, str]:
    if not isinstance(capture, dict):
        raise MembershipError("Capture envelope invalid.")
    try:
        binding = _capture_binding(capture, key)
        if binding is None:
            raise ValueError("No bound capture.")
        observation = capture["provenance_observation"]["observations"]
        source = next(x for x in observation if x["kind"] == "sources")
        source_sha = source["visible_metadata_sha256"]
        return source, binding["capture_manifest_sha256"]
    except (KeyError, StopIteration, ValueError, TypeError):
        raise MembershipError("Capture source observation invalid.") from None


def _sign(unsigned: dict, key: str) -> str:
    if not isinstance(key, str) or len(key) < 40:
        raise MembershipError("Local witness signing key invalid.")
    return hmac.new(key.encode("utf-8"), DOMAIN + encode(unsigned),
                    hashlib.sha256).hexdigest()


def _verified_witness(
    rows: object, record: object, receipt: object, file: Path,
    capture: object, key: str,
) -> dict:
    """Validate complete projection and bind one retained local source file."""
    if not isinstance(record, dict) or not isinstance(receipt, dict):
        raise MembershipError("Source record and receipt must be objects.")
    source, capture_hash = _signed_capture_source(capture, key)
    if receipt.get("capture_binding") is None:
        raise MembershipError("Membership requires a capture-bound source receipt.")
    try:
        verify_receipt(
            receipt, record, file, key=key, capture_manifest=capture)
        safe_record = safe_provenance_item(record, "sources")
    except (ReceiptError, CaptureError, ValueError, TypeError, RuntimeError):
        raise MembershipError("Bound local source receipt invalid.") from None
    stream_sha, count, missing = _source_summary(rows)
    if (count != source["records"] or
        missing != source["missing_checksum_or_version"] or
        not hmac.compare_digest(stream_sha, source["visible_metadata_sha256"])):
        raise MembershipError("Observed source projection differs from capture.")
    matches = [r for r in rows if r["id"] == safe_record["id"]]
    if len(matches) != 1 or matches[0] != safe_record:
        raise MembershipError("SourceRecord is not an exact captured member.")
    unsigned = {
        "schema_version": SCHEMA,
        "scope": "complete_bounded_observed_source_metadata_projection",
        "source_record_id": safe_record["id"],
        "source_record_sha256": digest(encode(safe_record)),
        "source_receipt_sha256": digest(encode(receipt)),
        "capture_manifest_sha256": capture_hash,
        "captured_source_projection_sha256": stream_sha,
        "source_projection_record_count": count,
        "source_projection_missing_checksums": missing,
        # Private metadata-only evidence is retained so the exact 0.8.11
        # ordered/framed SHA can be recomputed without network access.
        "observed_source_rows": rows,
        "membership_in_bounded_captured_projection": True,
        "independent_provider_signature_verified": False,
        "external_immutable_archive_verified": False,
        "cross_request_snapshot_isolation": False,
        "legal_rights_verified": False,
        "graph_relationships_covered": False,
        "research_release_status": "HOLD",
    }
    return {**unsigned, "witness_hmac": _sign(unsigned, key)}


def issue_witness(
    record: dict, receipt: dict, source_file: Path, capture: dict,
    fetch, *, key: str,
) -> dict:
    return _verified_witness(
        collect_source_rows(fetch), record, receipt, source_file, capture, key)


def verify_witness(
    witness: object, record: dict, receipt: dict, source_file: Path,
    capture: dict, *, key: str,
) -> None:
    if (not isinstance(witness, dict) or
        set(witness) != UNSIGNED_KEYS | {"witness_hmac"}):
        raise MembershipError("Witness envelope invalid.")
    original = witness["witness_hmac"]
    if (not isinstance(original, str) or len(original) != 64 or
        any(ch not in "0123456789abcdef" for ch in original)):
        raise MembershipError("Witness HMAC malformed.")
    # Independently reconstruct the complete visible projection digest and
    # all trust-boundary flags from source-file bytes and trusted manifest.
    expected = _verified_witness(
        witness["observed_source_rows"], record, receipt, source_file,
        capture, key)
    if not hmac.compare_digest(original, expected["witness_hmac"]) or (
        witness != expected
    ):
        raise MembershipError("Witness data or signature differs.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    for name in ("issue", "verify"):
        op = sub.add_parser(name)
        op.add_argument("--source-file", type=Path, required=True)
        op.add_argument("--source-record", type=Path, required=True)
        op.add_argument("--receipt", type=Path, required=True)
        op.add_argument("--capture-manifest", type=Path, required=True)
        op.add_argument("--key-file", type=Path)
        if name == "issue":
            op.add_argument("--url", default="http://127.0.0.1:8000")
            op.add_argument("--token-file", type=Path)
            op.add_argument("--output", type=Path, required=True)
        else:
            op.add_argument("--witness", type=Path, required=True)
    args = p.parse_args(argv)
    try:
        record = _load_json(args.source_record, MAX_RECORD_BYTES)
        receipt = _load_json(args.receipt, MAX_RECEIPT_BYTES)
        capture = _load_json(args.capture_manifest, MAX_CAPTURE_BYTES)
        if args.action == "issue":
            client = SignedLoopbackClient(
                args.url, token_path=args.token_file, key_path=args.key_file)
            result = issue_witness(
                record, receipt, args.source_file, capture, client.fetch,
                key=client.key)
            _write_private(args.output, result)
        else:
            secret = load_token(args.key_file or signature_key_path())
            witness = _load_json(args.witness, MAX_WITNESS_BYTES)
            verify_witness(
                witness, record, receipt, args.source_file, capture,
                key=secret)
        print("[OK] Private bounded SourceRecord membership verified; "
              "independent_source_attestation=FALSE; release=HOLD.")
        return 0
    except (OSError, ValueError, TypeError, KeyError, CaptureError):
        print("[FAIL] Private source membership verification rejected.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
