"""v0.8.13 bounded captured SourceRecord membership, synthetic-only tests."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from research_graph.ontology import stable_id
from scripts.search_capture import collect, digest, encode
from scripts.search_quality_eval import read_evidence
from scripts.search_revision import observe_projection
from scripts.search_provenance import observe_provenance
from scripts.source_receipts import (
    MODES, issue_receipt, verify_receipt,
)
from scripts.source_membership import (
    MembershipError, collect_source_rows, issue_witness, main, verify_witness,
)
from tests.test_source_provenance import CombinedAPI
from services.research_api.provenance import provenance_page

FIX = Path(__file__).resolve().parent / "fixtures"
CSV = FIX / "sefaria_links_synthetic.csv"
CATALOG = FIX / "search_review_questions_synthetic.json"
CAPTURES = FIX / "search_quality_responses_synthetic.json"
URI = "https://storage.googleapis.com/sefaria-export/links/links0.csv"
KEY = "synthetic-membership-hmac-" + "z" * 55


def fixture_record():
    sha = hashlib.sha256(CSV.read_bytes()).hexdigest()
    return {
        "id": stable_id("source", "sefaria", URI, sha),
        "provider": "sefaria", "source_uri": URI, "version_id": sha,
        "rights_tag": "LINK_METADATA_UNREVIEWED", "checksum_sha256": sha,
    }


class CapturedMembershipTests(unittest.TestCase):
    def setUp(self):
        self.catalog, self.catalog_hash = read_evidence(CATALOG)
        search, _ = read_evidence(CAPTURES)
        self.api = CombinedAPI(search)
        self.record = fixture_record()
        self.api.store.rows["sources"] = [copy.deepcopy(self.record)]
        self.snapshot, self.capture_manifest = collect(
            self.catalog, self.api, mode="scan",
            catalog_sha=self.catalog_hash, key=KEY,
            revision_probe=lambda: observe_projection(
                self.catalog, self.api, mode="scan"),
            provenance_probe=lambda: observe_provenance(self.api),
        )
        self.receipt = issue_receipt(
            self.record, CSV, mode=MODES[0], key=KEY,
            capture_manifest=self.capture_manifest)

    def make_witness(self):
        return issue_witness(
            self.record, self.receipt, CSV, self.capture_manifest,
            self.api, key=KEY)

    def test_complete_projection_matches_capture_and_includes_source(self):
        witness = self.make_witness()
        self.assertTrue(witness["membership_in_bounded_captured_projection"])
        self.assertFalse(witness["independent_provider_signature_verified"])
        self.assertFalse(witness["cross_request_snapshot_isolation"])
        self.assertFalse(witness["legal_rights_verified"])
        self.assertEqual(witness["research_release_status"], "HOLD")
        self.assertEqual(witness["source_projection_record_count"], 1)
        self.assertEqual(witness["observed_source_rows"][0], self.record)
        self.assertEqual(
            witness["captured_source_projection_sha256"],
            next(x["visible_metadata_sha256"] for x in
                 self.capture_manifest["provenance_observation"]["observations"]
                 if x["kind"] == "sources"))
        verify_witness(witness, self.record, self.receipt, CSV,
                       self.capture_manifest, key=KEY)

    def test_changed_or_removed_row_fails_issue_after_original_capture(self):
        self.api.store.rows["sources"] = []
        with self.assertRaises(MembershipError):
            self.make_witness()
        bad = dict(self.record)
        bad["version_id"] = "changed"
        self.api.store.rows["sources"] = [bad]
        with self.assertRaises(MembershipError):
            self.make_witness()

    def test_wrong_exported_record_rejected_even_same_projected_digest(self):
        # Provenance projection is preserved, but the claimed individual
        # metadata must match EXACTLY, not just source ID/hash.
        changed = dict(self.record)
        changed["provider"] = "alternate"
        witness = self.make_witness()
        with self.assertRaises(MembershipError):
            verify_witness(witness, changed, self.receipt, CSV,
                           self.capture_manifest, key=KEY)

    def test_capture_not_bound_to_source_receipt_is_rejected(self):
        unbound = issue_receipt(self.record, CSV, mode=MODES[0], key=KEY)
        with self.assertRaises(MembershipError):
            issue_witness(self.record, unbound, CSV, self.capture_manifest,
                          self.api, key=KEY)

    def test_manifest_tampering_denied(self):
        witness = self.make_witness()
        bad = copy.deepcopy(self.capture_manifest)
        bad["request_count"] += 1
        with self.assertRaises(MembershipError):
            verify_witness(witness, self.record, self.receipt, CSV,
                           bad, key=KEY)

    def test_witness_hmac_and_rights_flags_forgery_rejected(self):
        original = self.make_witness()
        for key, value in (
            ("witness_hmac", "0" * 64),
            ("legal_rights_verified", True),
            ("independent_provider_signature_verified", True),
            ("research_release_status", "APPROVED"),
            ("source_projection_record_count", 777),
        ):
            with self.subTest(key=key):
                altered = copy.deepcopy(original)
                altered[key] = value
                with self.assertRaises(MembershipError):
                    verify_witness(altered, self.record, self.receipt, CSV,
                                   self.capture_manifest, key=KEY)
        with self.assertRaises(MembershipError):
            verify_witness(original, self.record, self.receipt, CSV,
                           self.capture_manifest, key="different-" + "x" * 60)

    def test_order_and_unsafe_projection_rejected(self):
        # A changed page with unknown text fields is rejected, even if no
        # source record is personally identified in a printed error.
        class Corrupt:
            def __init__(self, parent):
                self.parent = parent
            def __call__(self, req_target):
                page = copy.deepcopy(self.parent(req_target))
                page["items"][0]["text"] = "UNLICENSED CONTENT"
                return page
        with self.assertRaises(MembershipError):
            collect_source_rows(Corrupt(self.api))
        duplicated = [self.record, self.record]
        from scripts.source_membership import _source_summary
        with self.assertRaises(MembershipError):
            _source_summary(duplicated)

    def test_multiple_pages_complete_and_sorted(self):
        # The bounded observation can include many sources, but only one
        # locally verified file may be claimed as a member.
        rows = [
            {"id": stable_id("source", "fixture", str(i)),
             "provider": "fixture", "source_uri": None, "version_id": None,
             "rights_tag": None, "checksum_sha256": None}
            for i in range(22)
        ]
        store = self.api.store
        store.rows["sources"] = sorted(rows, key=lambda r: r["id"])
        def fetch(req_target):
            from urllib.parse import parse_qs, urlsplit
            args = parse_qs(urlsplit(req_target).query)
            return provenance_page(
                store, kind="sources", cursor=args.get("cursor", [None])[0],
                limit=int(args["limit"][0]))
        returned = collect_source_rows(fetch)
        self.assertEqual(returned, store.rows["sources"])
        self.assertEqual(len(returned), 22)

    def test_offline_cli_verification_and_private_output(self):
        witness = self.make_witness()
        with tempfile.TemporaryDirectory() as root:
            d = Path(root)
            for name, obj in (
                ("record.json", self.record),
                ("receipt.json", self.receipt),
                ("capture.json", self.capture_manifest),
                ("witness.json", witness),
            ):
                (d/name).write_text(json.dumps(obj), encoding="utf-8")
            key_file = d/"local.key"
            key_file.write_text(KEY, encoding="utf-8")
            os.chmod(key_file, 0o600)
            self.assertEqual(main([
                "verify", "--source-file", str(CSV),
                "--source-record", str(d/"record.json"),
                "--receipt", str(d/"receipt.json"),
                "--capture-manifest", str(d/"capture.json"),
                "--key-file", str(key_file),
                "--witness", str(d/"witness.json"),
            ]), 0)
            (d/"witness.json").write_text(json.dumps({
                **witness, "legal_rights_verified": True
            }), encoding="utf-8")
            self.assertEqual(main([
                "verify", "--source-file", str(CSV),
                "--source-record", str(d/"record.json"),
                "--receipt", str(d/"receipt.json"),
                "--capture-manifest", str(d/"capture.json"),
                "--key-file", str(key_file),
                "--witness", str(d/"witness.json"),
            ]), 2)


if __name__ == "__main__":
    unittest.main()
