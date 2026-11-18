"""v0.10.2 bounded signed audit-window drift, security and CLI tests."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.compare_study_audit_window_v0102 import main as cli
from services.research_api.study_audit_window_v0102 import (
    compare_study_audit_windows, verify_study_audit_window_diff,
)
from services.research_api.study_packets_v0100 import (
    StudyPacketError, preview_study_packet,
)
from tests.test_study_packets_v0100 import StudyPacketTests
from tests.test_work_comparison import LEFT, RIGHT, edge


class StudyAuditWindowTests(unittest.TestCase):
    def setUp(self):
        fixture = StudyPacketTests(
            "test_two_citations_and_exact_audit_provenance"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.secret = fixture.secret

    def get(self):
        response = self.fixture.get()
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_unselected_change_is_not_silently_declared_clean(self):
        before = self.get()
        original = self.fixture.store.forward[3]["evidence_review_status"]
        self.fixture.store.forward[3]["evidence_review_status"] = (
            "rejected" if original != "rejected" else "disputed"
        )
        after = self.get()
        report = compare_study_audit_windows(
            before, after, secret=self.secret,
        )
        body = report["report"]
        self.assertEqual(body["window_change_count"], 1)
        self.assertEqual(body["unselected_window_change_count"], 1)
        self.assertFalse(body["selected_citation_metadata_changed"])
        self.assertFalse(body["window_changes"][0]["selected_in_baseline"])
        self.assertFalse(body["window_changes"][0]["selected_in_current"])
        self.assertEqual(
            body["window_changes"][0]["changed_fields"],
            ["evidence_review_status"],
        )
        check = verify_study_audit_window_diff(
            report, before, after, secret=self.secret,
        )
        self.assertTrue(check["review_required"])
        self.assertFalse(check["entire_corpus_revision_verified"])

    def test_identical_window_can_have_different_receipt_time(self):
        before = preview_study_packet(
            self.fixture.store, source_work_id=LEFT,
            target_work_id=RIGHT, evidence_ids=self.fixture.ids,
            secret=self.secret, now=100,
        )
        after = preview_study_packet(
            self.fixture.store, source_work_id=LEFT,
            target_work_id=RIGHT, evidence_ids=self.fixture.ids,
            secret=self.secret, now=101,
        )
        report = compare_study_audit_windows(
            before, after, secret=self.secret,
        )["report"]
        self.assertEqual(report["window_changes"], [])
        self.assertFalse(report["window_metadata_changed"])
        self.assertTrue(report["audit_receipt_changed"])
        self.assertFalse(report["immutable_graph_snapshot_verified"])

    def test_addition_removal_and_selection_are_explicit(self):
        before = self.get()
        old_selected = set(self.fixture.ids.split(","))
        removed = next(
            row for row in self.fixture.store.forward
            if row["evidence_id"] not in old_selected
        )
        self.fixture.store.forward.remove(removed)
        self.fixture.store.forward.append(edge("audit-window-new"))
        after = self.get()
        report = compare_study_audit_windows(
            before, after, secret=self.secret,
        )["report"]
        self.assertEqual(
            sorted(x["kind"] for x in report["window_changes"]),
            ["ADDED", "REMOVED"],
        )
        self.assertEqual(report["unselected_window_change_count"], 2)
        self.assertEqual(
            {x["evidence_id"] for x in report["window_changes"]},
            {
                removed["evidence_id"],
                self.fixture.store.forward[-1]["evidence_id"],
            },
        )

    def test_still_bounded_at_hundred_observed_links(self):
        self.fixture.store.forward = [
            edge(f"bounded-audit-{i:03d}") for i in range(100)
        ]
        self.fixture.ids = ",".join(sorted(
            row["evidence_id"]
            for row in self.fixture.store.forward
        )[:12])
        before = self.get()
        old_selected = set(self.fixture.ids.split(","))
        changed = next(
            row for row in self.fixture.store.forward
            if row["evidence_id"] not in old_selected
        )
        changed["version_id"] = "synthetic-edition-updated"
        after = self.get()
        result = compare_study_audit_windows(
            before, after, secret=self.secret,
        )
        self.assertEqual(result["report"]["baseline_observed_link_count"], 100)
        self.assertEqual(result["report"]["window_change_count"], 1)
        self.assertEqual(result["report"]["unselected_window_change_count"], 1)
        self.assertEqual(
            result["report"]["window_changes"][0]["changed_fields"],
            ["version_id"],
        )

    def test_forgery_wrong_secret_scope_and_clock_rollback_denied(self):
        before = self.get()
        result = compare_study_audit_windows(
            before, before, secret=self.secret,
        )
        for prop, value in (
            ("human_review_approved", True),
            ("entire_corpus_revision_verified", True),
            ("research_release_status", "PASS"),
        ):
            broken = deepcopy(result)
            broken["report"][prop] = value
            with self.subTest(property=prop), self.assertRaises(StudyPacketError):
                verify_study_audit_window_diff(
                    broken, before, before, secret=self.secret,
                )
        with self.assertRaises(StudyPacketError):
            verify_study_audit_window_diff(
                result, before, before, secret="Z" * 48,
            )
        earlier = preview_study_packet(
            self.fixture.store, source_work_id=LEFT,
            target_work_id=RIGHT, evidence_ids=self.fixture.ids,
            secret=self.secret, now=100,
        )
        later = preview_study_packet(
            self.fixture.store, source_work_id=LEFT,
            target_work_id=RIGHT, evidence_ids=self.fixture.ids,
            secret=self.secret, now=101,
        )
        with self.assertRaises(StudyPacketError):
            compare_study_audit_windows(
                later, earlier, secret=self.secret,
            )
        different_scope = preview_study_packet(
            self.fixture.store, source_work_id=RIGHT,
            target_work_id=LEFT,
            evidence_ids=self.fixture.store.reverse[0]["evidence_id"],
            secret=self.secret, now=101,
        )
        with self.assertRaises(StudyPacketError):
            compare_study_audit_windows(
                later, different_scope, secret=self.secret,
            )

    def test_private_cli_round_trip_no_overwrite_or_world_read(self):
        before = self.get()
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            p_old, p_new, p_report = (
                folder / "old.json",
                folder / "new.json",
                folder / "diff.json",
            )
            for path in (p_old, p_new):
                path.write_text(json.dumps(before), encoding="utf-8")
                path.chmod(0o600)
            flags = [
                "--baseline", str(p_old),
                "--current", str(p_new),
                "--token-path", str(self.fixture.key),
            ]
            self.assertEqual(cli(["compare", *flags, "--output", str(p_report)]), 0)
            self.assertEqual(cli(["verify", *flags, "--report", str(p_report)]), 0)
            self.assertEqual(cli(["compare", *flags, "--output", str(p_report)]), 1)
            self.assertEqual(p_report.stat().st_mode & 0o777, 0o600)
            invalid = json.loads(p_report.read_text(encoding="utf-8"))
            invalid["report"]["human_review_approved"] = True
            p_report.write_text(json.dumps(invalid), encoding="utf-8")
            self.assertEqual(cli(["verify", *flags, "--report", str(p_report)]), 1)
            p_old.chmod(0o644)
            self.assertEqual(cli([
                "compare", *flags, "--output", str(folder / "fresh.json"),
            ]), 1)


if __name__ == "__main__":
    unittest.main()
