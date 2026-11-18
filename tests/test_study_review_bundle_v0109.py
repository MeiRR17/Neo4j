"""v0.10.9 multi-page signed Evidence draft: real source and scope replay."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.study_review_bundle_v0109 import main as bundle_cli
from services.research_api.study_packets_v0100 import StudyPacketError
from services.research_api.study_review_queue_v0104 import (
    build_evidence_review_queue,
)
from services.research_api.study_review_matrix_v0108 import (
    build_review_triage_matrix, FILTER_ORDER,
)
from services.research_api.study_review_bundle_v0109 import (
    build_cross_page_review_bundle, verify_cross_page_review_bundle,
)
from tests.test_study_review_matrix_v0108 import SixViewTriageTests


class CrossPageBundleTests(unittest.TestCase):
    def setUp(self):
        fixture = SixViewTriageTests(
            "test_complete_six_view_matrix_signed_and_offline"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.secret = fixture.secret

    def source(self, count=9, limit=2):
        previews, queue = self.fixture.fixture.changed_fixture(count)
        coverages, pages = self.fixture.six_views(
            previews, queue, limit=limit,
        )
        matrix = build_review_triage_matrix(
            queue, previews, coverages, pages,
            secret=self.secret, limit=limit,
        )
        return previews, queue, coverages, pages, matrix

    def build(self, previews, queue, coverages, pages, matrix, ids, limit=2):
        return build_cross_page_review_bundle(
            matrix, queue, previews, coverages, pages,
            secret=self.secret, evidence_ids=",".join(ids), limit=limit,
        )

    def test_three_nonadjacent_pages_have_distinct_authenticated_handoffs(self):
        previews, queue, coverages, pages, matrix = self.source()
        ids = [row["evidence_id"] for row in matrix["matrix"]["rows"]]
        chosen = [ids[0], ids[4], ids[8]]
        self.fixture.fixture.fixture.store.calls.clear()
        report = self.build(
            previews, queue, coverages, pages, matrix, chosen,
        )
        bundle = report["bundle"]
        self.assertEqual(bundle["schema_version"], "0.10.9")
        self.assertEqual(bundle["selected_evidence_ids"], chosen)
        self.assertEqual(bundle["selected_count"], 3)
        self.assertEqual(bundle["source_page_count"], 3)
        self.assertEqual(
            [h["page_index"] for h in bundle["page_handoffs"]],
            [0, 2, 4],
        )
        self.assertEqual(
            [r["matched_filters"] for r in bundle["selected_rows"]],
            [["all", "source_or_review"]] * 3,
        )
        for item in bundle["page_handoffs"]:
            nested = item["handoff"]
            self.assertEqual(
                nested["handoff"]["parent_page_sha256"],
                item["page_sha256"],
            )
            self.assertEqual(len(nested["handoff"]["items"]), 1)
            self.assertEqual(
                len(nested["handoff"]["items"][0]["observation_history"]), 2,
            )
        self.assertFalse(bundle["human_review_approved"])
        self.assertEqual(bundle["research_release_status"], "HOLD")
        verify = verify_cross_page_review_bundle(
            report, matrix, queue, previews, coverages, pages,
            secret=self.secret, evidence_ids=",".join(chosen), limit=2,
        )
        self.assertTrue(verify["all_selected_page_handoffs_verified"])
        self.assertEqual(self.fixture.fixture.fixture.store.calls, [])

    def test_removed_evidence_retains_only_explicit_historical_source(self):
        before = self.fixture.fixture.packet(100)
        removed = self.fixture.fixture.fixture.store.forward.pop(3)
        after = self.fixture.fixture.packet(200)
        previews = [before, after]
        queue = build_evidence_review_queue(previews, secret=self.secret)
        coverages, pages = self.fixture.six_views(
            previews, queue, limit=2,
        )
        matrix = build_review_triage_matrix(
            queue, previews, coverages, pages,
            secret=self.secret, limit=2,
        )
        report = self.build(
            previews, queue, coverages, pages, matrix,
            [removed["evidence_id"]],
        )
        item = report["bundle"]["page_handoffs"][0]["handoff"][
            "handoff"
        ]["items"][0]
        self.assertFalse(item["source_metadata_is_current_observation"])
        self.assertEqual(
            [capture["observed_in_audit"]
             for capture in item["observation_history"]],
            [True, False],
        )
        self.assertIsNone(item["observation_history"][1]["citation_metadata"])

    def test_unsigned_scope_forged_approval_and_missing_matrix_id_refused(self):
        previews, queue, coverages, pages, matrix = self.source(6)
        ids = [row["evidence_id"] for row in matrix["matrix"]["rows"]]
        report = self.build(
            previews, queue, coverages, pages, matrix, ids[:2],
        )
        for field, value in (
            ("human_review_approved", True),
            ("research_release_status", "PASS"),
            ("selected_count", 5),
        ):
            altered = deepcopy(report)
            altered["bundle"][field] = value
            with self.subTest(field=field), self.assertRaises(StudyPacketError):
                verify_cross_page_review_bundle(
                    altered, matrix, queue, previews, coverages, pages,
                    secret=self.secret, evidence_ids=",".join(ids[:2]), limit=2,
                )
        altered = deepcopy(report)
        altered["bundle"]["page_handoffs"][0]["handoff"][
            "handoff"
        ]["human_review_approved"] = True
        with self.assertRaises(StudyPacketError):
            verify_cross_page_review_bundle(
                altered, matrix, queue, previews, coverages, pages,
                secret=self.secret, evidence_ids=",".join(ids[:2]), limit=2,
            )
        with self.assertRaises(StudyPacketError):
            self.build(
                previews, queue, coverages, pages, matrix,
                ["evidence:missing"],
            )
        with self.assertRaises(StudyPacketError):
            self.build(
                previews, queue, coverages, pages, matrix,
                [ids[0], ids[0]],
            )
        with self.assertRaises(StudyPacketError):
            self.build(
                previews, queue, coverages, pages, matrix,
                list(reversed(ids[:2])),
            )
        with self.assertRaises(StudyPacketError):
            build_cross_page_review_bundle(
                matrix, queue, previews, coverages, pages,
                secret=self.secret, evidence_ids=ids[0], limit=3,
            )

    def test_private_cli_create_verify_and_refuse_overwrite(self):
        previews, queue, coverages, pages, matrix = self.source(5)
        ids = [row["evidence_id"] for row in matrix["matrix"]["rows"]]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def private(name, value):
                path = root / name
                path.write_text(json.dumps(value), encoding="utf-8")
                path.chmod(0o600)
                return path
            queue_path = private("queue.json", queue)
            matrix_path = private("matrix.json", matrix)
            args = [
                "--queue", str(queue_path),
                "--matrix", str(matrix_path),
                "--token-path", str(self.fixture.fixture.fixture.key),
                "--ids", ",".join([ids[0], ids[-1]]),
                "--limit", "2",
            ]
            for index, packet in enumerate(previews):
                path = private(f"packet-{index}.json", packet)
                args.extend(["--packet", str(path)])
            last_coverage = None
            for name in FILTER_ORDER:
                last_coverage = private(
                    f"coverage-{name}.json", coverages[name],
                )
                args.extend(["--coverage", f"{name}={last_coverage}"])
                for index, page in enumerate(pages[name]):
                    path = private(f"page-{name}-{index}.json", page)
                    args.extend(["--page", f"{name}={path}"])
            output = root / "review-bundle.json"
            self.assertEqual(
                bundle_cli(["build", *args, "--output", str(output)]), 0,
            )
            self.assertEqual(
                bundle_cli(["verify", *args, "--report", str(output)]), 0,
            )
            self.assertEqual(
                bundle_cli(["build", *args, "--output", str(output)]), 1,
            )
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            last_coverage.chmod(0o644)
            self.assertEqual(
                bundle_cli(["verify", *args, "--report", str(output)]), 1,
            )


if __name__ == "__main__":
    unittest.main()
