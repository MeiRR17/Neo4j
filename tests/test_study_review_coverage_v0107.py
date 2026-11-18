"""v0.10.7 verified full review-inbox traversal, tampering and private CLI."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.study_review_coverage_v0107 import main as cli
from services.research_api.study_packets_v0100 import StudyPacketError
from services.research_api.study_review_coverage_v0107 import (
    build_review_inbox_coverage, verify_review_inbox_coverage,
)
from services.research_api.study_review_pages_v0105 import (
    page_review_candidates,
)
from tests.test_study_review_pages_v0105 import SignedReviewPagesTests


class ReviewInboxCoverageTests(unittest.TestCase):
    def setUp(self):
        fixture = SignedReviewPagesTests("test_keyset_walk_covers_every_candidate_once_and_no_database_calls")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.secret = fixture.secret

    def walk(self, previews, queue, *, reason_filter="all", limit=3):
        pages = []
        cursor = None
        while True:
            page = page_review_candidates(
                queue, previews, secret=self.secret, reason_filter=reason_filter,
                limit=limit, cursor=cursor,
            )
            pages.append(page)
            if not page["page"]["has_more"]:
                return pages
            cursor = page["page"]["next_cursor"]

    def build(self, previews, queue, pages, **options):
        return build_review_inbox_coverage(
            queue, previews, pages, secret=self.secret, **options,
        )

    def test_full_multi_page_walk_covers_each_candidate_once(self):
        previews, queue = self.fixture.changed_fixture(13)
        self.fixture.fixture.store.calls.clear()
        pages = self.walk(previews, queue, limit=4)
        receipt = self.build(previews, queue, pages, limit=4)
        manifest = receipt["manifest"]
        self.assertEqual(manifest["schema_version"], "0.10.7")
        self.assertEqual(manifest["queue_candidate_count"], 13)
        self.assertEqual(manifest["covered_candidate_count"], 13)
        self.assertEqual(manifest["page_count"], 4)
        self.assertEqual(
            [p["candidate_count"] for p in manifest["pages"]], [4, 4, 4, 1],
        )
        self.assertEqual(
            manifest["ordered_evidence_ids"],
            [row["evidence_id"] for page in pages for row in page["page"]["items"]],
        )
        self.assertTrue(manifest["keyset_walk_complete"])
        self.assertFalse(manifest["human_decisions_recorded"])
        self.assertEqual(manifest["research_release_status"], "HOLD")
        report = verify_review_inbox_coverage(
            receipt, queue, previews, pages, secret=self.secret, limit=4,
        )
        self.assertTrue(report["manifest_hmac_verified"])
        self.assertEqual(report["covered_candidate_count"], 13)
        self.assertEqual(self.fixture.fixture.store.calls, [])

    def test_missing_duplicate_reordered_or_appended_pages_refused(self):
        previews, queue = self.fixture.changed_fixture(7)
        pages = self.walk(previews, queue, limit=3)
        self.assertEqual(len(pages), 3)
        for invalid in (
            pages[:2],
            pages[1:],
            [pages[0], pages[0], pages[1], pages[2]],
            [pages[1], pages[0], pages[2]],
            pages + [pages[-1]],
            [],
        ):
            with self.subTest(count=len(invalid)), self.assertRaises(
                StudyPacketError
            ):
                self.build(previews, queue, invalid, limit=3)

    def test_filter_scope_and_empty_view(self):
        previews, queue = self.fixture.changed_fixture(5)
        pages = self.walk(
            previews, queue, reason_filter="returned_state", limit=2,
        )
        self.assertEqual(len(pages), 1)
        receipt = self.build(
            previews, queue, pages, reason_filter="returned_state", limit=2,
        )
        self.assertEqual(receipt["manifest"]["covered_candidate_count"], 0)
        self.assertEqual(receipt["manifest"]["page_count"], 1)
        for opts in (
            {"reason_filter": "all", "limit": 2},
            {"reason_filter": "returned_state", "limit": 3},
            {"reason_filter": "approved", "limit": 2},
        ):
            with self.subTest(opts=opts), self.assertRaises(StudyPacketError):
                self.build(previews, queue, pages, **opts)

    def test_tampered_page_receipt_and_forged_manifest_denied(self):
        previews, queue = self.fixture.changed_fixture(8)
        pages = self.walk(previews, queue, limit=3)
        receipt = self.build(previews, queue, pages, limit=3)
        fake_page = deepcopy(pages)
        fake_page[1]["page"]["items"][0]["human_approved"] = True
        with self.assertRaises(StudyPacketError):
            self.build(previews, queue, fake_page, limit=3)
        forged = deepcopy(receipt)
        forged["manifest"]["human_decisions_recorded"] = True
        with self.assertRaises(StudyPacketError):
            verify_review_inbox_coverage(
                forged, queue, previews, pages, secret=self.secret, limit=3,
            )
        forged = deepcopy(receipt)
        forged["manifest_hmac_sha256"] = "0" * 64
        with self.assertRaises(StudyPacketError):
            verify_review_inbox_coverage(
                forged, queue, previews, pages, secret=self.secret, limit=3,
            )

    def test_private_cli_create_verify_and_no_overwrite(self):
        previews, queue = self.fixture.changed_fixture(5)
        pages = self.walk(previews, queue, limit=3)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            args = []
            for index, packet in enumerate(previews):
                path = folder / f"packet-{index}.json"
                path.write_text(json.dumps(packet), encoding="utf-8")
                path.chmod(0o600)
                args += ["--packet", str(path)]
            queue_path = folder / "queue.json"
            queue_path.write_text(json.dumps(queue), encoding="utf-8")
            queue_path.chmod(0o600)
            for index, page in enumerate(pages):
                path = folder / f"page-{index}.json"
                path.write_text(json.dumps(page), encoding="utf-8")
                path.chmod(0o600)
                args += ["--page", str(path)]
            args += [
                "--queue", str(queue_path),
                "--token-path", str(self.fixture.fixture.key),
                "--limit", "3",
            ]
            output = folder / "receipt.json"
            self.assertEqual(cli(["build", *args, "--output", str(output)]), 0)
            self.assertEqual(cli(["verify", *args, "--report", str(output)]), 0)
            self.assertEqual(cli(["build", *args, "--output", str(output)]), 1)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            page_path = folder / "page-0.json"
            page_path.chmod(0o644)
            self.assertEqual(cli(["verify", *args, "--report", str(output)]), 1)


if __name__ == "__main__":
    unittest.main()
