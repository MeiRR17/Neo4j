"""v0.10.4 deterministic, offline review queue and refusal tests."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.study_review_queue_v0104 import main as cli
from services.research_api.study_packets_v0100 import (
    StudyPacketError, preview_study_packet,
)
from services.research_api.study_review_queue_v0104 import (
    build_evidence_review_queue, verify_evidence_review_queue,
)
from tests.test_study_packets_v0100 import StudyPacketTests
from tests.test_work_comparison import LEFT, RIGHT, edge


class StudyReviewQueueTests(unittest.TestCase):
    def setUp(self):
        fixture = StudyPacketTests(
            "test_two_citations_and_exact_audit_provenance"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.secret = fixture.secret

    def packet(self, now, *, selection=None):
        return preview_study_packet(
            self.fixture.store, source_work_id=LEFT,
            target_work_id=RIGHT,
            evidence_ids=selection or self.fixture.ids,
            secret=self.secret, now=now,
        )

    def test_unchanged_window_and_selection_yield_no_review_items(self):
        packets = [self.packet(n) for n in (100, 200, 300)]
        self.fixture.store.calls.clear()
        result = build_evidence_review_queue(packets, secret=self.secret)
        data = result["queue"]
        self.assertEqual(data["candidate_count"], 0)
        self.assertEqual(data["items"], [])
        self.assertFalse(data["requires_human_triage"])
        self.assertFalse(data["reviewer_decisions_recorded"])
        self.assertEqual(self.fixture.store.calls, [])
        self.assertFalse(verify_evidence_review_queue(
            result, packets, secret=self.secret
        )["requires_human_triage"])

    def test_unselected_review_status_change_creates_bounded_candidate(self):
        before = self.packet(100)
        row = self.fixture.store.forward[3]
        row["evidence_review_status"] = (
            "rejected" if row["evidence_review_status"] != "rejected"
            else "disputed"
        )
        after = self.packet(200)
        q = build_evidence_review_queue([before, after], secret=self.secret)
        data = q["queue"]
        self.assertEqual(data["candidate_count"], 1)
        item = data["items"][0]
        self.assertEqual(item["evidence_id"], row["evidence_id"])
        self.assertEqual(item["reason_codes"], ["REVIEW_STATUS_CHANGED"])
        self.assertTrue(item["unselected_window_drift"])
        self.assertFalse(item["selected_in_initial_capture"])
        self.assertFalse(item["selected_in_latest_capture"])
        self.assertFalse(item["human_approved"])
        self.assertEqual(item["review_status"], "PENDING_HUMAN_TRIAGE")
        self.assertEqual(
            verify_evidence_review_queue(
                q, [before, after], secret=self.secret
            )["unselected_window_candidate_count"], 1
        )

    def test_selection_only_change_is_not_ignored(self):
        before = self.packet(100)
        selected = self.fixture.ids.split(",")
        after = self.packet(200, selection=selected[0])
        receipt = build_evidence_review_queue(
            [before, after], secret=self.secret
        )
        data = receipt["queue"]
        self.assertEqual(data["candidate_count"], 1)
        self.assertEqual(data["selection_only_candidate_count"], 1)
        item = data["items"][0]
        self.assertEqual(item["evidence_id"], selected[1])
        self.assertEqual(item["reason_codes"], ["SELECTION_REMOVED"])
        self.assertEqual(item["events"][0]["window_change_kind"], "NONE")
        self.assertTrue(data["requires_human_triage"])
        self.assertEqual(data["research_release_status"], "HOLD")

    def test_a_b_a_evidence_row_return_requires_triage(self):
        first = self.packet(100)
        row = self.fixture.store.forward[3]
        original = row["version_id"]
        row["version_id"] = "synthetic-revised-edition"
        middle = self.packet(200)
        row["version_id"] = original
        final = self.packet(300)
        result = build_evidence_review_queue(
            [first, middle, final], secret=self.secret
        )
        data = result["queue"]
        self.assertEqual(data["candidate_count"], 1)
        item = data["items"][0]
        self.assertTrue(item["returned_to_prior_observed_state"])
        self.assertEqual(item["event_count"], 2)
        self.assertEqual(item["reason_codes"], ["SOURCE_METADATA_CHANGED"])
        self.assertEqual(data["returned_state_candidate_count"], 1)
        self.assertFalse(data["immutable_corpus_revision_verified"])

    def test_added_removed_membership_is_not_a_graph_delete_claim(self):
        before = self.packet(100)
        original_selection = set(self.fixture.ids.split(","))
        removed = next(
            row for row in self.fixture.store.forward
            if row["evidence_id"] not in original_selection
        )
        self.fixture.store.forward.remove(removed)
        added = edge("queue-new-synthetic")
        self.fixture.store.forward.append(added)
        after = self.packet(200)
        data = build_evidence_review_queue(
            [before, after], secret=self.secret,
        )["queue"]
        self.assertEqual(data["candidate_count"], 2)
        by_id = {item["evidence_id"]: item for item in data["items"]}
        self.assertEqual(
            by_id[removed["evidence_id"]]["reason_codes"],
            ["OBSERVED_WINDOW_REMOVED"],
        )
        self.assertEqual(
            by_id[added["evidence_id"]]["reason_codes"],
            ["OBSERVED_WINDOW_ADDED"],
        )
        self.assertFalse(data["dviros_saved_study_created"])

    def test_tamper_wrong_key_and_swapped_packet_order_are_denied(self):
        originals = [self.packet(100), self.packet(200)]
        receipt = build_evidence_review_queue(
            originals, secret=self.secret
        )
        for key, forged in (
            ("reviewer_decisions_recorded", True),
            ("source_licenses_verified", True),
            ("research_release_status", "PASS"),
            ("requires_human_triage", True),
        ):
            altered = deepcopy(receipt)
            altered["queue"][key] = forged
            with self.subTest(key=key), self.assertRaises(StudyPacketError):
                verify_evidence_review_queue(
                    altered, originals, secret=self.secret
                )
        with self.assertRaises(StudyPacketError):
            verify_evidence_review_queue(
                receipt, originals, secret="Q" * 48
            )
        with self.assertRaises(StudyPacketError):
            verify_evidence_review_queue(
                receipt, list(reversed(originals)), secret=self.secret
            )
        corrupt = deepcopy(originals[0])
        corrupt["packet_hmac_sha256"] = "f" * 64
        with self.assertRaises(StudyPacketError):
            build_evidence_review_queue(
                [corrupt, originals[1]], secret=self.secret
            )

    def test_cli_private_round_trip_refuses_overwrites_symlinks_and_forgery(self):
        packets = [self.packet(100), self.packet(200)]
        with tempfile.TemporaryDirectory() as folder_name:
            folder = Path(folder_name)
            paths = [folder / "one.json", folder / "two.json"]
            for path, packet in zip(paths, packets):
                path.write_text(json.dumps(packet), encoding="utf-8")
                path.chmod(0o600)
            out = folder / "queue.json"
            args = [
                item for path in paths for item in ("--packet", str(path))
            ] + ["--token-path", str(self.fixture.key)]
            self.assertEqual(cli(["build", *args, "--output", str(out)]), 0)
            self.assertEqual(cli(["verify", *args, "--report", str(out)]), 0)
            self.assertEqual(cli(["build", *args, "--output", str(out)]), 1)
            self.assertEqual(out.stat().st_mode & 0o777, 0o600)
            forged = json.loads(out.read_text(encoding="utf-8"))
            forged["queue"]["reviewer_decisions_recorded"] = True
            out.write_text(json.dumps(forged), encoding="utf-8")
            self.assertEqual(cli(["verify", *args, "--report", str(out)]), 1)
            alias = folder / "alias.json"
            alias.symlink_to(paths[0])
            self.assertEqual(cli([
                "build", "--packet", str(alias), "--packet", str(paths[1]),
                "--token-path", str(self.fixture.key),
                "--output", str(folder / "never.json"),
            ]), 1)
            paths[0].chmod(0o644)
            self.assertEqual(cli([
                "build", *args, "--output", str(folder / "unsafe.json"),
            ]), 1)


if __name__ == "__main__":
    unittest.main()
