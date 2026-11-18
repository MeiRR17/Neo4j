"""v0.10.5 signed keyset pages: pagination, filters, tampering, private CLI."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.study_review_pages_v0105 import main as cli
from services.research_api.study_packets_v0100 import (
    StudyPacketError, preview_study_packet,
)
from services.research_api.study_review_queue_v0104 import (
    build_evidence_review_queue,
)
from services.research_api.study_review_pages_v0105 import (
    FILTERS, MAX_PAGE_SIZE, page_review_candidates, verify_review_page,
)
from tests.test_study_packets_v0100 import StudyPacketTests
from tests.test_work_comparison import LEFT, RIGHT, edge


class SignedReviewPagesTests(unittest.TestCase):
    def setUp(self):
        fixture = StudyPacketTests(
            "test_two_citations_and_exact_audit_provenance"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.secret = fixture.secret

    def packet(self, stamp, *, selected=None):
        return preview_study_packet(
            self.fixture.store,
            source_work_id=LEFT, target_work_id=RIGHT,
            evidence_ids=selected or self.fixture.ids,
            secret=self.secret, now=stamp,
        )

    def changed_fixture(self, count=35):
        self.fixture.store.forward = [
            edge(f"review-page-{index:03d}") for index in range(count)
        ]
        self.fixture.ids = ",".join(sorted(
            row["evidence_id"] for row in self.fixture.store.forward
        )[:2])
        first = self.packet(100)
        for index, row in enumerate(self.fixture.store.forward):
            row["version_id"] = f"synthetic-revision-{index}"
        second = self.packet(200)
        previews = [first, second]
        queue = build_evidence_review_queue(previews, secret=self.secret)
        return previews, queue

    def test_keyset_walk_covers_every_candidate_once_and_no_database_calls(self):
        previews, queue = self.changed_fixture()
        self.assertEqual(queue["queue"]["candidate_count"], 35)
        self.fixture.store.calls.clear()
        cursor = None
        seen = []
        pages = 0
        while True:
            page = page_review_candidates(
                queue, previews, secret=self.secret, cursor=cursor, limit=7,
            )
            body = page["page"]
            pages += 1
            self.assertEqual(body["requested_limit"], 7)
            self.assertEqual(body["filtered_candidate_count"], 35)
            self.assertTrue(verify_review_page(
                page, queue, previews, secret=self.secret,
                cursor=cursor, limit=7,
            )["page_hmac_verified"])
            seen.extend(item["evidence_id"] for item in body["items"])
            if not body["has_more"]:
                self.assertIsNone(body["next_cursor"])
                break
            cursor = body["next_cursor"]
            self.assertIsInstance(cursor, str)
            self.assertLessEqual(len(cursor), 1024)
        self.assertEqual(pages, 5)
        self.assertEqual(len(seen), 35)
        self.assertEqual(len(set(seen)), 35)
        self.assertEqual(self.fixture.store.calls, [])

    def test_operational_order_and_reason_filters(self):
        first = self.packet(100)
        selected = self.fixture.ids.split(",")
        removed = self.fixture.store.forward.pop(3)
        changed = self.fixture.store.forward[2]
        changed["evidence_review_status"] = "disputed"
        second = self.packet(200, selected=selected[0])
        previews = [first, second]
        queue = build_evidence_review_queue(previews, secret=self.secret)
        full = page_review_candidates(queue, previews, secret=self.secret)
        self.assertEqual(full["page"]["page_candidate_count"], 3)
        self.assertEqual(
            full["page"]["items"][0]["evidence_id"], changed["evidence_id"]
        )
        self.assertEqual(
            page_review_candidates(
                queue, previews, secret=self.secret,
                reason_filter="source_or_review",
            )["page"]["page_candidate_count"], 1,
        )
        self.assertEqual(
            page_review_candidates(
                queue, previews, secret=self.secret,
                reason_filter="membership",
            )["page"]["items"][0]["evidence_id"], removed["evidence_id"],
        )
        self.assertEqual(
            page_review_candidates(
                queue, previews, secret=self.secret,
                reason_filter="selection",
            )["page"]["items"][0]["evidence_id"], selected[1],
        )

    def test_cursor_is_bound_to_queue_filter_and_limit(self):
        previews, queue = self.changed_fixture(25)
        page = page_review_candidates(
            queue, previews, secret=self.secret, limit=3,
        )
        cursor = page["page"]["next_cursor"]
        self.assertIsNotNone(cursor)
        for opts in (
            {"cursor": cursor, "limit": 4},
            {"cursor": cursor, "limit": 3, "reason_filter": "selection"},
            {"cursor": cursor + "0", "limit": 3},
            {"cursor": cursor[:-1] + ("0" if cursor[-1] != "0" else "1"),
             "limit": 3},
            {"cursor": "bad", "limit": 3},
        ):
            with self.subTest(opts=opts), self.assertRaises(StudyPacketError):
                page_review_candidates(
                    queue, previews, secret=self.secret, **opts
                )
        self.assertEqual(
            page_review_candidates(
                queue, previews, secret=self.secret, limit=3, cursor=cursor,
            )["page"]["page_candidate_count"], 3,
        )
        different = deepcopy(queue)
        different["queue_sha256"] = "a" * 64
        with self.assertRaises(StudyPacketError):
            page_review_candidates(
                different, previews, secret=self.secret, limit=3,
                cursor=cursor,
            )

    def test_bounded_inputs_and_empty_view(self):
        previews, queue = self.changed_fixture(22)
        for limit in (0, MAX_PAGE_SIZE + 1, True, "4"):
            with self.subTest(limit=limit), self.assertRaises(StudyPacketError):
                page_review_candidates(
                    queue, previews, secret=self.secret, limit=limit
                )
        self.assertEqual(len(FILTERS), 6)
        with self.assertRaises(StudyPacketError):
            page_review_candidates(
                queue, previews, secret=self.secret, reason_filter="approved"
            )
        page = page_review_candidates(
            queue, previews, secret=self.secret, reason_filter="returned_state"
        )
        self.assertEqual(page["page"]["items"], [])
        self.assertEqual(page["page"]["filtered_candidate_count"], 0)
        self.assertFalse(page["page"]["has_more"])
        self.assertEqual(page["page"]["research_release_status"], "HOLD")

    def test_forged_approval_and_hmac_are_refused(self):
        previews, queue = self.changed_fixture(4)
        page = page_review_candidates(queue, previews, secret=self.secret)
        for key, value in (
            ("item_approval_implemented", True),
            ("licensed_source_rights_verified", True),
            ("research_release_status", "PASS"),
            ("next_cursor", "forged"),
        ):
            modified = deepcopy(page)
            modified["page"][key] = value
            with self.subTest(key=key), self.assertRaises(StudyPacketError):
                verify_review_page(
                    modified, queue, previews, secret=self.secret
                )
        modified = deepcopy(page)
        modified["page_hmac_sha256"] = "f" * 64
        with self.assertRaises(StudyPacketError):
            verify_review_page(
                modified, queue, previews, secret=self.secret
            )
        with self.assertRaises(StudyPacketError):
            verify_review_page(
                page, queue, previews, secret="Q" * 48
            )

    def test_cli_owner_only_create_and_verify(self):
        previews, queue = self.changed_fixture(6)
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            names = [base / f"packet-{index}.json" for index in range(2)]
            for path, packet in zip(names, previews):
                path.write_text(json.dumps(packet), encoding="utf-8")
                path.chmod(0o600)
            qpath = base / "review-queue.json"
            qpath.write_text(json.dumps(queue), encoding="utf-8")
            qpath.chmod(0o600)
            report = base / "page.json"
            inputs = ["--queue", str(qpath)]
            for name in names:
                inputs += ["--packet", str(name)]
            inputs += [
                "--token-path", str(self.fixture.key), "--limit", "3"
            ]
            self.assertEqual(
                cli(["page", *inputs, "--output", str(report)]), 0
            )
            self.assertEqual(
                cli(["verify", *inputs, "--report", str(report)]), 0
            )
            self.assertEqual(
                cli(["page", *inputs, "--output", str(report)]), 1
            )
            self.assertEqual(report.stat().st_mode & 0o777, 0o600)
            forged = json.loads(report.read_text(encoding="utf-8"))
            forged["page"]["item_approval_implemented"] = True
            report.write_text(json.dumps(forged), encoding="utf-8")
            self.assertEqual(
                cli(["verify", *inputs, "--report", str(report)]), 1
            )
            qpath.chmod(0o644)
            self.assertEqual(
                cli(["page", *inputs, "--output", str(base / "new.json")]), 1
            )


if __name__ == "__main__":
    unittest.main()
