"""v0.10.3 multi-capture study timeline and private offline CLI tests."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.study_timeline_v0103 import main as cli
from services.research_api.study_packets_v0100 import (
    StudyPacketError, preview_study_packet,
)
from services.research_api.study_timeline_v0103 import (
    MAX_CAPTURES, build_study_timeline, verify_study_timeline,
)
from tests.test_study_packets_v0100 import StudyPacketTests
from tests.test_work_comparison import LEFT, RIGHT


class StudyTimelineTests(unittest.TestCase):
    def setUp(self):
        fixture = StudyPacketTests(
            "test_two_citations_and_exact_audit_provenance"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.secret = fixture.secret

    def packet(self, at: int, *, reverse: bool = False) -> dict:
        return preview_study_packet(
            self.fixture.store,
            source_work_id=RIGHT if reverse else LEFT,
            target_work_id=LEFT if reverse else RIGHT,
            evidence_ids=(
                self.fixture.store.reverse[0]["evidence_id"]
                if reverse else self.fixture.ids
            ),
            secret=self.secret, now=at,
        )

    def test_identical_evidence_across_three_captures(self):
        packets = [self.packet(at) for at in (100, 200, 300)]
        receipt = build_study_timeline(packets, secret=self.secret)
        report = receipt["timeline"]
        self.assertEqual(report["capture_count"], 3)
        self.assertEqual(report["transition_count"], 2)
        self.assertEqual(report["total_window_change_events"], 0)
        self.assertEqual(report["unique_changed_evidence_ids"], [])
        self.assertEqual(report["revisited_window_states"], [])
        self.assertFalse(report["has_observed_intermediate_drift"])
        self.assertEqual(
            report["transitions"][1]["previous_chain_sha256"],
            report["transitions"][0]["chain_sha256"],
        )
        verified = verify_study_timeline(
            receipt, packets, secret=self.secret,
        )
        self.assertTrue(verified["all_source_previews_verified"])
        self.assertFalse(verified["requires_human_review"])
        self.assertFalse(verified["immutable_corpus_revision_verified"])

    def test_a_b_a_recovers_visible_intermediate_drift(self):
        before = self.packet(100)
        changed = self.fixture.store.forward[3]
        original = changed["evidence_review_status"]
        changed["evidence_review_status"] = (
            "rejected" if original != "rejected" else "disputed"
        )
        middle = self.packet(200)
        changed["evidence_review_status"] = original
        after = self.packet(300)
        receipt = build_study_timeline(
            [before, middle, after], secret=self.secret,
        )
        data = receipt["timeline"]
        self.assertEqual(data["total_window_change_events"], 2)
        self.assertEqual(len(data["unique_changed_evidence_ids"]), 1)
        self.assertEqual(data["revisited_window_states"], [
            {"capture_index": 2, "previous_matching_index": 0}
        ])
        self.assertEqual(
            [x["unselected_window_change_count"] for x in data["transitions"]],
            [1, 1],
        )
        self.assertTrue(verify_study_timeline(
            receipt, [before, middle, after], secret=self.secret,
        )["requires_human_review"])
        self.assertEqual(data["research_release_status"], "HOLD")

    def test_order_limits_scope_and_tampered_inputs_fail_closed(self):
        first, second = self.packet(100), self.packet(200)
        for packets in (
            [first], [first] * (MAX_CAPTURES + 1),
            [second, first], [first, first],
            [first, self.packet(101, reverse=True)],
        ):
            with self.subTest(count=len(packets)):
                with self.assertRaises(StudyPacketError):
                    build_study_timeline(packets, secret=self.secret)
        forged = deepcopy(first)
        forged["packet_hmac_sha256"] = "0" * 64
        with self.assertRaises(StudyPacketError):
            build_study_timeline([forged, second], secret=self.secret)

    def test_forged_summary_chain_order_and_key_are_refused(self):
        packets = [self.packet(at) for at in (100, 200, 300)]
        receipt = build_study_timeline(packets, secret=self.secret)
        for path, replacement in (
            (("timeline", "reviewer_approval_recorded"), True),
            (("timeline", "research_release_status"), "PASS"),
            (("timeline", "chain_tip_sha256"), "0" * 64),
            (("timeline", "transitions"), []),
        ):
            with self.subTest(path=path):
                changed = deepcopy(receipt)
                changed[path[0]][path[1]] = replacement
                with self.assertRaises(StudyPacketError):
                    verify_study_timeline(
                        changed, packets, secret=self.secret,
                    )
        with self.assertRaises(StudyPacketError):
            verify_study_timeline(
                receipt, packets, secret="X" * 48,
            )
        with self.assertRaises(StudyPacketError):
            verify_study_timeline(
                receipt, list(reversed(packets)), secret=self.secret,
            )

    def test_six_capture_maximum_and_isolated_metadata(self):
        packets = [self.packet(i) for i in range(100, 100 + MAX_CAPTURES)]
        receipt = build_study_timeline(packets, secret=self.secret)
        report = receipt["timeline"]
        self.assertEqual(report["capture_count"], MAX_CAPTURES)
        self.assertEqual(report["transition_count"], MAX_CAPTURES - 1)
        self.assertFalse(report["private_dviros_studies_saved"])
        self.assertFalse(report["source_rights_verified"])
        self.assertFalse(report["trusted_capture_times_verified"])
        self.assertNotIn("researcher_notes", json.dumps(report))

    def test_private_cli_round_trip_no_overwrite_or_public_files(self):
        packets = [self.packet(at) for at in (100, 200, 300)]
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            names = [folder / f"study-{i}.json" for i in range(3)]
            for path, packet in zip(names, packets):
                path.write_text(json.dumps(packet), encoding="utf-8")
                path.chmod(0o600)
            report = folder / "timeline.json"
            options = [
                option
                for name in names
                for option in ("--packet", str(name))
            ] + ["--token-path", str(self.fixture.key)]
            self.assertEqual(cli(["build", *options, "--output", str(report)]), 0)
            self.assertEqual(cli(["verify", *options, "--report", str(report)]), 0)
            self.assertEqual(cli(["build", *options, "--output", str(report)]), 1)
            self.assertEqual(report.stat().st_mode & 0o777, 0o600)
            changed = json.loads(report.read_text(encoding="utf-8"))
            changed["timeline"]["reviewer_approval_recorded"] = True
            report.write_text(json.dumps(changed), encoding="utf-8")
            self.assertEqual(cli(["verify", *options, "--report", str(report)]), 1)
            names[0].chmod(0o644)
            self.assertEqual(cli([
                "build", *options, "--output", str(folder / "other.json"),
            ]), 1)


if __name__ == "__main__":
    unittest.main()
