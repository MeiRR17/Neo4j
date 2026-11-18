"""v0.10.8 six-view signed review matrix: overlaps, scope and private IO."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.study_review_matrix_v0108 import main as matrix_cli
from services.research_api.study_packets_v0100 import (
    StudyPacketError,
)
from services.research_api.study_review_queue_v0104 import (
    build_evidence_review_queue,
)
from services.research_api.study_review_pages_v0105 import (
    page_review_candidates,
)
from services.research_api.study_review_coverage_v0107 import (
    build_review_inbox_coverage,
)
from services.research_api.study_review_matrix_v0108 import (
    FILTER_ORDER, build_review_triage_matrix, verify_review_triage_matrix,
)
from tests.test_study_review_pages_v0105 import SignedReviewPagesTests


class SixViewTriageTests(unittest.TestCase):
    def setUp(self):
        fixture = SignedReviewPagesTests(
            "test_keyset_walk_covers_every_candidate_once_and_no_database_calls"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.secret = fixture.secret

    def six_views(self, previews, queue, *, limit=3):
        coverages = {}
        pages = {}
        for reason_filter in FILTER_ORDER:
            walk = []
            cursor = None
            while True:
                page = page_review_candidates(
                    queue, previews, secret=self.secret,
                    reason_filter=reason_filter, limit=limit, cursor=cursor,
                )
                walk.append(page)
                if not page["page"]["has_more"]:
                    break
                cursor = page["page"]["next_cursor"]
            pages[reason_filter] = walk
            coverages[reason_filter] = build_review_inbox_coverage(
                queue, previews, walk, secret=self.secret,
                reason_filter=reason_filter, limit=limit,
            )
        return coverages, pages

    def build(self, previews, queue, coverages, pages, *, limit=3):
        return build_review_triage_matrix(
            queue, previews, coverages, pages,
            secret=self.secret, limit=limit,
        )

    def test_complete_six_view_matrix_signed_and_offline(self):
        previews, queue = self.fixture.changed_fixture(8)
        coverages, pages = self.six_views(previews, queue)
        self.fixture.fixture.store.calls.clear()
        receipt = self.build(previews, queue, coverages, pages)
        m = receipt["matrix"]
        self.assertEqual(m["schema_version"], "0.10.8")
        self.assertEqual(m["candidate_count"], 8)
        self.assertEqual(
            [s["reason_filter"] for s in m["filter_summaries"]],
            list(FILTER_ORDER),
        )
        self.assertEqual(
            [s["candidate_count"] for s in m["filter_summaries"]],
            [8, 8, 0, 0, 0, 0],
        )
        self.assertEqual(m["overlapping_specific_filter_candidate_count"], 0)
        self.assertTrue(all(row["matched_filters"] == [
            "all", "source_or_review"
        ] for row in m["rows"]))
        self.assertTrue(all(not row["human_review_approved"] for row in m["rows"]))
        self.assertEqual(m["research_release_status"], "HOLD")
        result = verify_review_triage_matrix(
            receipt, queue, previews, coverages, pages,
            secret=self.secret, limit=3,
        )
        self.assertTrue(result["all_six_complete_views_verified"])
        self.assertTrue(result["matrix_hmac_verified"])
        self.assertEqual(self.fixture.fixture.store.calls, [])

    def test_overlapping_review_selection_and_observation_removal(self):
        before = self.fixture.packet(100)
        selected = self.fixture.fixture.ids.split(",")
        changed_id = selected[1]
        changed_row = next(
            row for row in self.fixture.fixture.store.forward
            if row["evidence_id"] == changed_id
        )
        changed_row["evidence_review_status"] = "disputed"
        removed = next(
            row for row in self.fixture.fixture.store.forward
            if row["evidence_id"] not in selected
        )
        self.fixture.fixture.store.forward.remove(removed)
        after = self.fixture.packet(200, selected=selected[0])
        previews = [before, after]
        queue = build_evidence_review_queue(previews, secret=self.secret)
        coverages, pages = self.six_views(previews, queue)
        receipt = self.build(previews, queue, coverages, pages)
        matrix = receipt["matrix"]
        by_id = {row["evidence_id"]: row for row in matrix["rows"]}
        self.assertEqual(matrix["candidate_count"], 2)
        self.assertEqual(
            by_id[changed_id]["matched_filters"],
            ["all", "source_or_review", "selection"],
        )
        self.assertEqual(
            by_id[removed["evidence_id"]]["matched_filters"],
            ["all", "membership"],
        )
        self.assertEqual(matrix["overlapping_specific_filter_candidate_count"], 1)
        self.assertFalse(by_id[removed["evidence_id"]][
            "observed_in_latest_window"
        ])

    def test_exact_six_filters_and_boundaries(self):
        previews, queue = self.fixture.changed_fixture(4)
        coverages, pages = self.six_views(previews, queue)
        for bad_coverages, bad_pages, limit in (
            ({k: v for k, v in coverages.items() if k != "all"}, pages, 3),
            (coverages, {k: v for k, v in pages.items() if k != "all"}, 3),
            (coverages, pages, 0),
            (coverages, pages, True),
            (coverages, pages, 21),
        ):
            with self.assertRaises(StudyPacketError):
                self.build(
                    previews, queue, bad_coverages, bad_pages, limit=limit
                )
        fake = deepcopy(coverages)
        fake["membership"] = coverages["selection"]
        with self.assertRaises(StudyPacketError):
            self.build(previews, queue, fake, pages)
        changed_pages = deepcopy(pages)
        changed_pages["all"] = []
        with self.assertRaises(StudyPacketError):
            self.build(previews, queue, coverages, changed_pages)

    def test_forged_filter_history_or_approval_is_refused(self):
        previews, queue = self.fixture.changed_fixture(5)
        coverages, pages = self.six_views(previews, queue)
        receipt = self.build(previews, queue, coverages, pages)
        for field, tampered in (
            ("human_review_decisions_recorded", True),
            ("research_release_status", "PASS"),
            ("candidate_count", 100),
        ):
            bogus = deepcopy(receipt)
            bogus["matrix"][field] = tampered
            with self.subTest(field=field), self.assertRaises(
                StudyPacketError
            ):
                verify_review_triage_matrix(
                    bogus, queue, previews, coverages, pages,
                    secret=self.secret, limit=3,
                )
        bogus = deepcopy(receipt)
        bogus["matrix"]["rows"][0]["matched_filters"] = ["all", "membership"]
        with self.assertRaises(StudyPacketError):
            verify_review_triage_matrix(
                bogus, queue, previews, coverages, pages,
                secret=self.secret, limit=3,
            )
        bogus = deepcopy(receipt)
        bogus["matrix_hmac_sha256"] = "a" * 64
        with self.assertRaises(StudyPacketError):
            verify_review_triage_matrix(
                bogus, queue, previews, coverages, pages,
                secret=self.secret, limit=3,
            )

    def test_private_cli_replay_no_overwrite_and_no_weak_permissions(self):
        previews, queue = self.fixture.changed_fixture(5)
        coverages, pages = self.six_views(previews, queue)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queue_path = root / "queue.json"
            queue_path.write_text(json.dumps(queue), encoding="utf-8")
            queue_path.chmod(0o600)
            args = ["--queue", str(queue_path),
                    "--token-path", str(self.fixture.fixture.key), "--limit", "3"]
            for index, packet in enumerate(previews):
                path = root / f"packet-{index}.json"
                path.write_text(json.dumps(packet), encoding="utf-8")
                path.chmod(0o600)
                args += ["--packet", str(path)]
            for name in FILTER_ORDER:
                receipt = root / f"coverage-{name}.json"
                receipt.write_text(json.dumps(coverages[name]), encoding="utf-8")
                receipt.chmod(0o600)
                args += ["--coverage", f"{name}={receipt}"]
                for index, page in enumerate(pages[name]):
                    path = root / f"page-{name}-{index}.json"
                    path.write_text(json.dumps(page), encoding="utf-8")
                    path.chmod(0o600)
                    args += ["--page", f"{name}={path}"]
            report = root / "matrix.json"
            self.assertEqual(matrix_cli([
                "build", *args, "--output", str(report),
            ]), 0)
            self.assertEqual(matrix_cli([
                "verify", *args, "--report", str(report),
            ]), 0)
            self.assertEqual(matrix_cli([
                "build", *args, "--output", str(report),
            ]), 1)
            self.assertEqual(report.stat().st_mode & 0o777, 0o600)
            receipt.chmod(0o644)
            self.assertEqual(matrix_cli([
                "verify", *args, "--report", str(report),
            ]), 1)


if __name__ == "__main__":
    unittest.main()
