"""v0.8.12 retained-byte receipts, tamper resistance and provenance binding.

The fixtures are synthetic and no real provider rights are approved.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from ingestion.seed_catalog import compact_json, versions_url
from ingestion.sefaria_links import RIGHTS_TAG
from research_graph.ontology import stable_id
from scripts.search_capture import CaptureError, collect, digest, encode
from scripts.search_quality_eval import read_evidence
from scripts.search_revision import observe_projection
from scripts.search_provenance import observe_provenance
from scripts.source_receipts import (
    MODES, ReceiptError, issue_receipt, verify_receipt, main,
)
from tests.test_source_provenance import CombinedAPI

FIXTURE = (Path(__file__).resolve().parent / "fixtures" /
           "sefaria_links_synthetic.csv")
CATALOG = (Path(__file__).resolve().parent / "fixtures" /
           "search_review_questions_synthetic.json")
RESPONSES = (Path(__file__).resolve().parent / "fixtures" /
             "search_quality_responses_synthetic.json")
KEY = "synthetic-only-test-key-" + "x" * 48
CSV_URI = "https://storage.googleapis.com/sefaria-export/links/links0.csv"


def record(uri, snapshot_hash, *, rights_tag):
    return {
        "id": stable_id("source", "sefaria", uri, snapshot_hash),
        "provider": "sefaria",
        "source_uri": uri,
        "version_id": snapshot_hash,
        "rights_tag": rights_tag,
        "checksum_sha256": snapshot_hash,
    }


class SourceReceiptTests(unittest.TestCase):
    def setUp(self):
        self.csv_hash = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
        self.csv_record = record(CSV_URI, self.csv_hash, rights_tag=RIGHTS_TAG)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = Path(self.tmp.name)
        self.metadata = [{
            "title": "Synthetic Philosophy Work",
            "versionTitle": "SYNTHETIC METADATA ONLY",
            "language": "en", "license": "CC0",
            "versionSource": "https://example.invalid/fixture",
        }]
        self.versions = self.p / "versions.json"
        self.versions.write_text(json.dumps(self.metadata, indent=2), encoding="utf-8")
        self.json_digest = hashlib.sha256(compact_json(self.metadata)).hexdigest()
        self.json_record = record(
            versions_url("Synthetic Philosophy Work"), self.json_digest,
            rights_tag="EDITION_METADATA_ONLY",
        )

    def test_csv_snapshot_receipt_matches_known_raw_bytes(self):
        receipt = issue_receipt(
            self.csv_record, FIXTURE, mode=MODES[0], key=KEY)
        self.assertEqual(receipt["source_record_id"], self.csv_record["id"])
        self.assertEqual(receipt["observed_raw_file_sha256"], self.csv_hash)
        self.assertEqual(receipt["observed_local_snapshot_sha256"], self.csv_hash)
        self.assertTrue(receipt["locally_recomputed_checksum_matches_record"])
        self.assertFalse(receipt["original_provider_response_authenticated"])
        self.assertFalse(receipt["source_redistribution_rights_verified"])
        self.assertFalse(receipt["external_immutable_storage_verified"])
        self.assertEqual(receipt["research_release_status"], "HOLD")
        self.assertNotIn("Guide for the Perplexed", json.dumps(receipt))
        self.assertNotIn("links0.csv", json.dumps(receipt))
        verify_receipt(receipt, self.csv_record, FIXTURE, key=KEY)

    def test_version_metadata_canonical_json_hash_not_raw_file_hash(self):
        receipt = issue_receipt(
            self.json_record, self.versions, mode=MODES[1], key=KEY)
        self.assertEqual(receipt["stored_snapshot_sha256"], self.json_digest)
        self.assertNotEqual(receipt["observed_raw_file_sha256"], self.json_digest)
        verify_receipt(receipt, self.json_record, self.versions, key=KEY)
        # Presentation-only whitespace changes preserve canonical JSON
        self.versions.write_text(json.dumps(self.metadata, separators=(",", ":")),
                                 encoding="utf-8")
        with self.assertRaises(ReceiptError):
            verify_receipt(receipt, self.json_record, self.versions, key=KEY)

    def test_changed_bytes_stored_checksum_or_wrong_mode_rejected(self):
        path = self.p / "links.csv"
        path.write_bytes(FIXTURE.read_bytes())
        prior = issue_receipt(self.csv_record, path, mode=MODES[0], key=KEY)
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaises(ReceiptError):
            verify_receipt(prior, self.csv_record, path, key=KEY)
        other = copy.deepcopy(self.csv_record)
        other["checksum_sha256"] = "0" * 64
        with self.assertRaises(ReceiptError):
            issue_receipt(other, FIXTURE, mode=MODES[0], key=KEY)
        with self.assertRaises(ReceiptError):
            issue_receipt(self.csv_record, FIXTURE, mode=MODES[1], key=KEY)

    def test_changed_signature_and_claims_rejected(self):
        receipt = issue_receipt(
            self.csv_record, FIXTURE, mode=MODES[0], key=KEY)
        variants = [
            {"external_immutable_storage_verified": True},
            {"source_redistribution_rights_verified": True},
            {"research_release_status": "APPROVED"},
            {"checksum_mode": MODES[1]},
            {"receipt_hmac": "0" * 64},
            {"unsafe_raw_text": "copyrighted"},
        ]
        for variant in variants:
            with self.subTest(variant=list(variant)):
                changed = copy.deepcopy(receipt)
                changed.update(variant)
                with self.assertRaises(ReceiptError):
                    verify_receipt(changed, self.csv_record, FIXTURE, key=KEY)

    def test_refuses_symlink_and_unsupported_source_uri(self):
        symlink = self.p / "alias.csv"
        symlink.symlink_to(FIXTURE)
        with self.assertRaises(ReceiptError):
            issue_receipt(self.csv_record, symlink, mode=MODES[0], key=KEY)
        for uri in ("https://evil.example/links0.csv",
                    "http://storage.googleapis.com/sefaria-export/links/links0.csv",
                    "https://storage.googleapis.com/sefaria-export/links/links101.csv"):
            changed = record(uri, self.csv_hash, rights_tag=RIGHTS_TAG)
            with self.assertRaises(ReceiptError):
                issue_receipt(changed, FIXTURE, mode=MODES[0], key=KEY)

    def test_refuses_hidden_text_and_rights_elevation(self):
        self.versions.write_text(json.dumps([{
            **self.metadata[0], "text": ["SYNTHETIC CONTENT"]
        }]), encoding="utf-8")
        changed_digest = hashlib.sha256(
            compact_json([{**self.metadata[0], "text": ["SYNTHETIC CONTENT"]}])
        ).hexdigest()
        changed_record = record(
            versions_url("Synthetic Philosophy Work"), changed_digest,
            rights_tag="EDITION_METADATA_ONLY")
        with self.assertRaises(ReceiptError):
            issue_receipt(changed_record, self.versions, mode=MODES[1], key=KEY)
        bad = copy.deepcopy(self.csv_record)
        bad["rights_tag"] = "CLEARED_FOR_TEXT"
        with self.assertRaises(ReceiptError):
            issue_receipt(bad, FIXTURE, mode=MODES[0], key=KEY)

    def test_receipt_may_bind_authentic_local_capture_manifest(self):
        catalog, catalog_sha = read_evidence(CATALOG)
        captures, _ = read_evidence(RESPONSES)
        api = CombinedAPI(captures)
        _, capture_manifest = collect(
            catalog, api, mode="scan", catalog_sha=catalog_sha, key=KEY,
            revision_probe=lambda: observe_projection(
                catalog, api, mode="scan"),
            provenance_probe=lambda: observe_provenance(api))
        receipt = issue_receipt(
            self.csv_record, FIXTURE, mode=MODES[0], key=KEY,
            capture_manifest=capture_manifest)
        self.assertIsNotNone(receipt["capture_binding"])
        self.assertFalse(receipt["capture_binding"][
            "source_record_membership_independently_verified"])
        verify_receipt(
            receipt, self.csv_record, FIXTURE, key=KEY,
            capture_manifest=capture_manifest)
        altered = copy.deepcopy(capture_manifest)
        altered["request_count"] += 1
        with self.assertRaises(ReceiptError):
            issue_receipt(self.csv_record, FIXTURE, mode=MODES[0], key=KEY,
                          capture_manifest=altered)
        with self.assertRaises(ReceiptError):
            verify_receipt(receipt, self.csv_record, FIXTURE, key=KEY)

    def test_cli_creates_private_exclusive_file_and_verifies(self):
        record_file = self.p / "record.json"
        receipt_file = self.p / "receipt.json"
        secret_file = self.p / "hmac.secret"
        record_file.write_text(json.dumps(self.csv_record), encoding="utf-8")
        secret_file.write_text(KEY, encoding="utf-8")
        os.chmod(secret_file, 0o600)
        flags = [
            "--source-file", str(FIXTURE),
            "--source-record", str(record_file),
            "--key-file", str(secret_file),
        ]
        self.assertEqual(main(["issue", *flags, "--mode", MODES[0],
                               "--output", str(receipt_file)]), 0)
        self.assertEqual(receipt_file.stat().st_mode & 0o777, 0o600)
        original = receipt_file.read_bytes()
        self.assertEqual(main(["verify", *flags,
                               "--receipt", str(receipt_file)]), 0)
        self.assertEqual(main(["issue", *flags, "--mode", MODES[0],
                               "--output", str(receipt_file)]), 2)
        self.assertEqual(receipt_file.read_bytes(), original)
