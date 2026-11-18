"""v0.10.1 offline, signed study replay delta and create-only CLI checks."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.compare_study_packets_v0101 import main as cli
from services.research_api.study_packets_v0100 import StudyPacketError
from services.research_api.study_replay_v0101 import (
    compare_study_packets, verify_study_comparison,
)
from tests.test_study_packets_v0100 import StudyPacketTests


class StudyReplayTests(unittest.TestCase):
    def setUp(self):
        self.fixture = StudyPacketTests(
            "test_two_citations_and_exact_audit_provenance"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.secret = self.fixture.secret

    def original(self):
        response = self.fixture.get()
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_identical_signed_preview_has_no_citation_changes(self):
        before = self.original()
        receipt = compare_study_packets(before, before, secret=self.secret)
        report = receipt["comparison"]
        self.assertEqual(report["changes"], [])
        self.assertFalse(report["metadata_changed"])
        self.assertFalse(report["audit_receipt_changed"])
        self.assertFalse(report["dviros_study_persisted"])
        self.assertEqual(report["research_release_status"], "HOLD")
        self.assertTrue(verify_study_comparison(
            receipt, before, before, secret=self.secret,
        )["comparison_hmac_verified"])

    def test_signed_review_status_change_is_detected_not_approved(self):
        before = self.original()
        row = self.fixture.store.forward[0]
        row["evidence_review_status"] = (
            "rejected" if row["evidence_review_status"] != "rejected"
            else "disputed"
        )
        after = self.original()
        receipt = compare_study_packets(before, after, secret=self.secret)
        report = receipt["comparison"]
        self.assertTrue(report["metadata_changed"])
        self.assertEqual(len(report["changes"]), 1)
        self.assertEqual(report["changes"][0]["kind"], "MODIFIED")
        self.assertIn(
            "evidence_review_status",
            report["changes"][0]["changed_fields"],
        )
        verified = verify_study_comparison(
            receipt, before, after, secret=self.secret,
        )
        self.assertTrue(verified["review_required"])
        self.assertFalse(verified["human_review_decision_recorded"])

    def test_removed_selection_is_explicit_and_not_a_graph_delete(self):
        before = self.original()
        after = self.fixture.get(
            evidence_ids=self.fixture.ids.split(",")[0]
        ).json()
        receipt = compare_study_packets(before, after, secret=self.secret)
        self.assertEqual(
            [change["kind"] for change in receipt["comparison"]["changes"]],
            ["REMOVED"],
        )
        self.assertFalse(receipt["comparison"]["immutable_graph_snapshot_verified"])

    def test_unsigned_change_wrong_key_and_bogus_flags_refused(self):
        before = self.original()
        receipt = compare_study_packets(before, before, secret=self.secret)
        for field, replacement in (
            ("dviros_study_persisted", True),
            ("licensed_source_rights_verified", True),
            ("research_release_status", "PASS"),
        ):
            broken = deepcopy(receipt)
            broken["comparison"][field] = replacement
            with self.subTest(field=field), self.assertRaises(StudyPacketError):
                verify_study_comparison(
                    broken, before, before, secret=self.secret,
                )
        with self.assertRaises(StudyPacketError):
            verify_study_comparison(
                receipt, before, before, secret="X" * 48,
            )
        forged = deepcopy(before)
        forged["packet_hmac_sha256"] = "0" * 64
        with self.assertRaises(StudyPacketError):
            compare_study_packets(forged, before, secret=self.secret)

    def test_private_cli_create_only_and_offline_verify(self):
        original = self.original()
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            before = folder / "before.json"
            current = folder / "current.json"
            report = folder / "comparison.json"
            for path in (before, current):
                path.write_text(json.dumps(original), encoding="utf-8")
                path.chmod(0o600)
            args = [
                "--baseline", str(before), "--current", str(current),
                "--token-path", str(self.fixture.key),
            ]
            self.assertEqual(cli(["compare", *args, "--output", str(report)]), 0)
            self.assertEqual(cli(["verify", *args, "--report", str(report)]), 0)
            self.assertEqual(cli(["compare", *args, "--output", str(report)]), 1)
            self.assertEqual(report.stat().st_mode & 0o777, 0o600)
            altered = json.loads(report.read_text(encoding="utf-8"))
            altered["comparison"]["human_review_decision_recorded"] = True
            report.write_text(json.dumps(altered), encoding="utf-8")
            self.assertEqual(cli(["verify", *args, "--report", str(report)]), 1)
            before.chmod(0o644)
            self.assertEqual(cli(["compare", *args, "--output", str(folder / "new.json")]), 1)


if __name__ == "__main__":
    unittest.main()
