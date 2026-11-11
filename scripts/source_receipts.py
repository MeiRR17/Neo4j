#!/usr/bin/env python3
"""v0.8.12: tamper-evident receipts for *retained local* metadata snapshots.

No network reads or writes, no source excerpts or remote downloads. A receipt
verifies actual local file content against an exported SourceRecord assertion.
It is not independent provider attestation, a license, an immutable archive
or an assertion that the captured research graph contains the record.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingestion.seed_catalog import (
    MAX_METADATA_BYTES, compact_json, safe_title, versions_url,
)
from ingestion.sefaria_links import CSV_URL_RE, FIELDS
from research_graph.ontology import stable_id
from scripts.search_capture import CaptureError, digest, encode, manifest_mac
from scripts.search_quality_eval import read_evidence
from scripts.search_review_workflow import _write_private
from services.research_api.config import load_token
from services.research_api.provenance import safe_provenance_item
from services.research_api.signature import signature_key_path

SCHEMA = "0.8.12"
MODES = ("sefaria_links_csv_raw_sha256", "sefaria_versions_json_canonical_sha256")
MAX_LINK_BYTES = 512 * 1024 * 1024
MAX_RECORD_BYTES = 16_384
MAX_RECEIPT_BYTES = 16_384
MAX_CAPTURE_BYTES = 512_000
CHUNK = 1024 * 1024
DOMAIN = b"neo4j-local-source-receipt-v0.8.12\n"
HEX = re.compile(r"^[a-f0-9]{64}$")
RECEIPT_FIELDS = frozenset({
    "schema_version", "verification_scope", "source_record_id",
    "source_uri_sha256", "source_record_sha256", "checksum_mode",
    "stored_snapshot_sha256", "observed_local_snapshot_sha256",
    "observed_raw_file_sha256", "observed_file_size_bytes",
    "locally_recomputed_checksum_matches_record",
    "source_record_is_authenticated_server_attestation",
    "original_provider_response_authenticated",
    "external_immutable_storage_verified",
    "source_redistribution_rights_verified",
    "source_text_exported", "research_release_status",
    "capture_binding", "receipt_hmac",
})


class ReceiptError(ValueError):
    """Sanitized local verification rejection."""


def _load_json(path: Path, max_bytes: int) -> dict:
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
        raise ReceiptError("Receipt input must be a bounded regular file.")
    with path.open("rb") as f:
        raw = f.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ReceiptError("Receipt input exceeded byte limit.")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise ReceiptError("Receipt input must be valid UTF-8 JSON.") from None
    if not isinstance(data, dict):
        raise ReceiptError("Receipt JSON object required.")
    return data


def _source_record(record: object, mode: str) -> dict:
    if mode not in MODES:
        raise ReceiptError("Unknown local checksum mode.")
    try:
        safe = safe_provenance_item(record, "sources")
    except (ValueError, TypeError, RuntimeError):
        raise ReceiptError("Exported SourceRecord projection invalid.") from None
    uri = safe["source_uri"]
    if safe["provider"] != "sefaria" or not isinstance(uri, str):
        raise ReceiptError("Only the known Sefaria metadata provider is supported.")
    if mode == MODES[0]:
        if not CSV_URL_RE.fullmatch(uri) or (
            safe["rights_tag"] != "LINK_METADATA_UNREVIEWED"
        ):
            raise ReceiptError("CSV source URL or rights status invalid.")
    else:
        parsed = urlsplit(uri)
        if (parsed.scheme != "https" or parsed.netloc != "www.sefaria.org" or
            not parsed.path.startswith("/api/texts/versions/") or
            parsed.query or parsed.fragment):
            raise ReceiptError("Version-metadata URI invalid.")
        try:
            title = safe_title(unquote(
                parsed.path[len("/api/texts/versions/"):]))
        except (TypeError, ValueError):
            raise ReceiptError("Version-metadata title invalid.") from None
        if uri != versions_url(title) or safe["rights_tag"] != "EDITION_METADATA_ONLY":
            raise ReceiptError("Version-metadata canonical URL/rights status invalid.")
    checksum = safe["checksum_sha256"]
    if not isinstance(checksum, str) or not HEX.fullmatch(checksum):
        raise ReceiptError("Stored provider checksum missing or malformed.")
    if safe["version_id"] != checksum:
        raise ReceiptError("Source version differs from stored snapshot checksum.")
    if safe["id"] != stable_id("source", "sefaria", uri, checksum):
        raise ReceiptError("Source ID is inconsistent with URI and digest.")
    return safe


def _stable_file(path: Path, max_bytes: int) -> tuple[bytes | None, str, int]:
    """Read a bounded local regular file with checks before and after reading.

    CSV is streamed and never materialized. JSON is <=2MB by contract.
    """
    path = Path(path)
    if path.is_symlink() or path.parent.is_symlink():
        raise ReceiptError("Snapshot symlinks are not permitted.")
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as src:
            before = os.fstat(src.fileno())
            if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= max_bytes:
                raise ReceiptError("Snapshot must be bounded nonempty regular file.")
            raw = bytearray() if max_bytes == MAX_METADATA_BYTES else None
            sha = hashlib.sha256()
            observed = 0
            while True:
                piece = src.read(min(CHUNK, max_bytes - observed + 1))
                if not piece:
                    break
                observed += len(piece)
                if observed > max_bytes:
                    raise ReceiptError("Source exceeds local snapshot byte budget.")
                sha.update(piece)
                if raw is not None:
                    raw.extend(piece)
            after = os.fstat(src.fileno())
        if (observed != before.st_size or
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
             before.st_ctime_ns) !=
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
             after.st_ctime_ns)):
            raise ReceiptError("Source changed while being hashed.")
        return bytes(raw) if raw is not None else None, sha.hexdigest(), observed
    except (OSError, PermissionError):
        raise ReceiptError("Source snapshot read rejected.") from None


def _file_checksum(path: Path, mode: str) -> tuple[str, str, int]:
    if mode == MODES[0]:
        _, raw_sha, size = _stable_file(path, MAX_LINK_BYTES)
        # Check only the CSV *header*, never print records or process text
        # columns; no source material is exported into the receipt.
        try:
            with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
                header = next(csv.reader(f), None)
        except (OSError, UnicodeError, csv.Error):
            raise ReceiptError("CSV metadata header invalid.") from None
        if header != list(FIELDS):
            raise ReceiptError("Only Sefaria metadata-only link CSV accepted.")
        return raw_sha, raw_sha, size
    if mode == MODES[1]:
        data, raw_sha, size = _stable_file(path, MAX_METADATA_BYTES)
        try:
            metadata = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeError):
            raise ReceiptError("Version snapshot is not valid JSON.") from None
        if not isinstance(metadata, list) or not 0 < len(metadata) <= 500 or (
            not all(isinstance(item, dict) for item in metadata)
        ):
            raise ReceiptError("Version snapshot is not a metadata list.")
        for item in metadata:
            if any(k in item for k in ("text", "he", "en", "content", "chapters",
                                       "text_body", "fullText")):
                raise ReceiptError("Source text fields not allowed in metadata receipt.")
        return digest(compact_json(metadata)), raw_sha, size
    raise ReceiptError("Unsupported source checksum mode.")


def _capture_binding(manifest: dict | None, key: str) -> dict | None:
    if manifest is None:
        return None
    if manifest.get("schema_version") != "0.8.11" or (
        manifest.get("source_rights_verified") is not False
    ) or manifest.get("release_status") != "HOLD":
        raise ReceiptError("Only an unapproved v0.8.11 capture can be attached.")
    import copy
    unsigned = copy.deepcopy(manifest)
    signature = unsigned.pop("manifest_hmac", None)
    if (not isinstance(signature, str) or not HEX.fullmatch(signature) or
        not hmac.compare_digest(signature, manifest_mac(unsigned, key))):
        raise ReceiptError("Capture manifest integrity cannot be verified.")
    from scripts.search_provenance import validate_provenance_observation
    try:
        validate_provenance_observation(manifest["provenance_observation"])
    except (KeyError, ValueError, TypeError):
        raise ReceiptError("Capture provenance observation invalid.") from None
    # This binds to a capture *event*. The v0.8.11 observation stores an
    # aggregate hash, not individual SourceRecord membership evidence.
    return {
        "capture_manifest_sha256": digest(encode(manifest)),
        "provenance_observation_sha256":
            manifest["provenance_observation"]["observation_sha256"],
        "source_record_membership_independently_verified": False,
    }


def _sign(payload: dict, key: str) -> str:
    if not isinstance(key, str) or len(key) < 40:
        raise ReceiptError("Local HMAC signing key unavailable.")
    return hmac.new(key.encode("utf-8"), DOMAIN + encode(payload),
                    hashlib.sha256).hexdigest()


def issue_receipt(record: dict, source_file: Path, *, mode: str, key: str,
                  capture_manifest: dict | None = None) -> dict:
    safe = _source_record(record, mode)
    computed, raw_sha, size = _file_checksum(source_file, mode)
    if not hmac.compare_digest(computed, safe["checksum_sha256"]):
        raise ReceiptError("Retained snapshot differs from SourceRecord checksum.")
    unsigned = {
        "schema_version": SCHEMA,
        "verification_scope": "retained_local_source_metadata_bytes_only",
        "source_record_id": safe["id"],
        "source_uri_sha256": digest(safe["source_uri"].encode("utf-8")),
        "source_record_sha256": digest(encode(safe)),
        "checksum_mode": mode,
        "stored_snapshot_sha256": safe["checksum_sha256"],
        "observed_local_snapshot_sha256": computed,
        "observed_raw_file_sha256": raw_sha,
        "observed_file_size_bytes": size,
        "locally_recomputed_checksum_matches_record": True,
        "source_record_is_authenticated_server_attestation": False,
        "original_provider_response_authenticated": False,
        "external_immutable_storage_verified": False,
        "source_redistribution_rights_verified": False,
        "source_text_exported": False,
        "research_release_status": "HOLD",
        "capture_binding": _capture_binding(capture_manifest, key),
    }
    return {**unsigned, "receipt_hmac": _sign(unsigned, key)}


def verify_receipt(receipt: object, record: dict, source_file: Path, *,
                   key: str, capture_manifest: dict | None = None) -> None:
    if not isinstance(receipt, dict) or set(receipt) != RECEIPT_FIELDS:
        raise ReceiptError("Receipt schema/fields invalid.")
    if receipt.get("schema_version") != SCHEMA or (
        receipt.get("checksum_mode") not in MODES
    ):
        raise ReceiptError("Receipt checksum type/version invalid.")
    expected = issue_receipt(
        record, source_file, mode=receipt["checksum_mode"], key=key,
        capture_manifest=capture_manifest)
    if receipt != expected:
        raise ReceiptError("Receipt does not match retained bytes or source metadata.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    issue = sub.add_parser("issue")
    issue.add_argument("--source-file", type=Path, required=True)
    issue.add_argument("--source-record", type=Path, required=True)
    issue.add_argument("--mode", choices=MODES, required=True)
    issue.add_argument("--capture-manifest", type=Path)
    issue.add_argument("--key-file", type=Path)
    issue.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--receipt", type=Path, required=True)
    verify.add_argument("--source-file", type=Path, required=True)
    verify.add_argument("--source-record", type=Path, required=True)
    verify.add_argument("--capture-manifest", type=Path)
    verify.add_argument("--key-file", type=Path)
    args = p.parse_args(argv)
    try:
        record = _load_json(args.source_record, MAX_RECORD_BYTES)
        captured = (_load_json(args.capture_manifest, MAX_CAPTURE_BYTES)
                    if args.capture_manifest else None)
        key = load_token(args.key_file or signature_key_path())
        if args.action == "issue":
            receipt = issue_receipt(
                record, args.source_file, mode=args.mode, key=key,
                capture_manifest=captured)
            _write_private(args.output, receipt)
        else:
            receipt = _load_json(args.receipt, MAX_RECEIPT_BYTES)
            verify_receipt(
                receipt, record, args.source_file, key=key,
                capture_manifest=captured)
        print("[OK] Retained local metadata snapshot matches SourceRecord; "
              "rights=UNVERIFIED; research_release=HOLD.")
        return 0
    except (ValueError, TypeError, KeyError, OSError, CaptureError):
        print("[FAIL] Local source receipt invalid, unavailable or unverified.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
