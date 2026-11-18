"""v0.10.6 signed Evidence handoff: scope, stale metadata, offline CLI."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.study_review_handoff_v0106 import main as handoff_cli
from services.research_api.study_packets_v0100 import (
    StudyPacketError, preview_study_packet,
)
from services.research_api.study_review_queue_v0104 import (
    build_evidence_review_queue,
)
from services.research_api.study_review_pages_v0105 import (
    page_review_candidates,
)
from services.research_api.study_review_handoff_v0106 import (
    build_review_handoff, verify_review_handoff,
)
from tests.test_study_packets_v0100 import StudyPacketTests
from tests.test_work_comparison import LEFT, RIGHT, edge


class ReviewHandoffTests(unittest.TestCase):
    def setUp(self):
        fixture = StudyPacketTests(
            "test_two_citations_and_exact_audit_provenance"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.secret = fixture.secret

    def packet(self, at: int, selection: str | None = None) -> dict:
        return preview_study_packet(
            self.fixture.store,
            source_work_id=LEFT, target_work_id=RIGHT,
            evidence_ids=selection or self.fixture.ids,
            secret=self.secret, now=at,
        )

    def changed(self):
        before = self.packet(100)
        row = self.fixture.store.forward[3]
        row["version_id"] = "changed-edition-synthetic"
        after = self.packet(200)
        previews = [before, after]
        queue = build_evidence_review_queue(previews, secret=self.secret)
        page = page_review_candidates(queue, previews, secret=self.secret)
        return previews, queue, page

    def build(self, previews, queue, page, evidence_ids=None, **opts):
        if evidence_ids is None:
            evidence_ids = page["page"]["items"][0]["evidence_id"]
        return build_review_handoff(
            page, queue, previews, secret=self.secret,
            evidence_ids=evidence_ids, **opts,
        )

    def test_exact_page_candidate_keeps_metadata_and_history(self):
        previews, queue, page = self.changed()
        self.fixture.store.calls.clear()
        handoff = self.build(previews, queue, page)
        value = handoff["handoff"]
        self.assertEqual(value["schema_version"], "0.10.6")
        self.assertEqual(value["selected_count"], 1)
        self.assertEqual(value["parent_queue_sha256"], queue["queue_sha256"])
        self.assertEqual(value["parent_page_sha256"], page["page_sha256"])
        item = value["items"][0]
        self.assertEqual(item["last_observed_capture_index"], 1)
        self.assertEqual(
            item["last_observed_citation_metadata"]["version_id"],
            "changed-edition-synthetic",
        )
        self.assertTrue(item["source_metadata_is_current_observation"])
        history = item["observation_history"]
        self.assertEqual([x["capture_index"] for x in history], [0, 1])
        self.assertEqual(
            [x["packet_sha256"] for x in history],
            [packet["packet_sha256"] for packet in previews],
        )
        self.assertTrue(all(x["observed_in_audit"] for x in history))
        self.assertNotEqual(
            history[0]["citation_metadata"]["version_id"],
            history[1]["citation_metadata"]["version_id"],
        )
        self.assertEqual(item["review_decision"], "NOT_RECORDED")
        self.assertIsNone(item["draft_reviewer_note"])
        self.assertFalse(item["human_approved"])
        self.assertFalse(value["dviros_saved_review_created"])
        self.assertEqual(value["research_release_status"], "HOLD")
        verification = verify_review_handoff(
            handoff, page, queue, previews, secret=self.secret,
            evidence_ids=item["evidence_id"],
        )
        self.assertTrue(verification["handoff_hmac_verified"])
        self.assertEqual(self.fixture.store.calls, [])

    def test_removed_observation_uses_explicit_stale_reference(self):
        before = self.packet(100)
        removed = self.fixture.store.forward.pop(3)
        after = self.packet(200)
        previews = [before, after]
        queue = build_evidence_review_queue(previews, secret=self.secret)
        page = page_review_candidates(queue, previews, secret=self.secret)
        value = self.build(previews, queue, page)["handoff"]
        item = value["items"][0]
        self.assertEqual(item["evidence_id"], removed["evidence_id"])
        self.assertFalse(item["observed_in_latest_window"])
        self.assertEqual(item["last_observed_capture_index"], 0)
        self.assertFalse(item["source_metadata_is_current_observation"])
        self.assertEqual(
            [x["observed_in_audit"] for x in item["observation_history"]],
            [True, False],
        )
        self.assertIsNone(item["observation_history"][1]["citation_metadata"])
        self.assertEqual(
            item["last_observed_citation_metadata"]["evidence_id"],
            removed["evidence_id"],
        )
        self.assertEqual(item["reason_codes"], ["OBSERVED_WINDOW_REMOVED"])

    def test_selection_only_candidate_has_current_audit_metadata(self):
        before = self.packet(100)
        chosen = self.fixture.ids.split(",")[0]
        after = self.packet(200, selection=chosen)
        previews = [before, after]
        queue = build_evidence_review_queue(previews, secret=self.secret)
        page = page_review_candidates(queue, previews, secret=self.secret)
        item = self.build(previews, queue, page)["handoff"]["items"][0]
        self.assertEqual(item["reason_codes"], ["SELECTION_REMOVED"])
        self.assertTrue(item["observed_in_latest_window"])
        self.assertFalse(item["selected_in_latest_capture"])
        self.assertTrue(item["source_metadata_is_current_observation"])
        self.assertEqual(
            [x["selected_in_study"] for x in item["observation_history"]],
            [True, False],
        )
        self.assertEqual(
            [x["observed_in_audit"] for x in item["observation_history"]],
            [True, True],
        )

    def test_page_scope_cannot_cross_cursor_filter_or_selection(self):
        self.fixture.store.forward = [
            edge(f"handoff-many-{i:03d}") for i in range(7)
        ]
        self.fixture.ids = ",".join(sorted(
            row["evidence_id"] for row in self.fixture.store.forward
        )[:2])
        before = self.packet(100)
        for row in self.fixture.store.forward:
            row["version_id"] = "changed-for-handoff"
        after = self.packet(200)
        previews = [before, after]
        queue = build_evidence_review_queue(previews, secret=self.secret)
        first = page_review_candidates(
            queue, previews, secret=self.secret, limit=2,
        )
        cursor = first["page"]["next_cursor"]
        self.assertIsNotNone(cursor)
        second = page_review_candidates(
            queue, previews, secret=self.secret, limit=2, cursor=cursor,
        )
        first_id = first["page"]["items"][0]["evidence_id"]
        second_id = second["page"]["items"][0]["evidence_id"]
        self.assertEqual(
            self.build(previews, queue, second, second_id,
                       limit=2, cursor=cursor)["handoff"]["selected_count"], 1,
        )
        for id_value in (first_id, "evidence:invalid"):
            with self.subTest(evidence_id=id_value), self.assertRaises(
                StudyPacketError
            ):
                self.build(previews, queue, second, id_value,
                           limit=2, cursor=cursor)
        with self.assertRaises(StudyPacketError):
            self.build(previews, queue, second, second_id, limit=2)
        with self.assertRaises(StudyPacketError):
            self.build(previews, queue, second, second_id,
                       limit=2, cursor=cursor, reason_filter="selection")

    def test_forged_status_and_hmac_are_refused(self):
        previews, queue, page = self.changed()
        item_id = page["page"]["items"][0]["evidence_id"]
        receipt = self.build(previews, queue, page, item_id)
        for field, forged in (
            ("human_review_approved", True),
            ("source_licenses_verified", True),
            ("research_release_status", "PASS"),
            ("selected_count", 12),
        ):
            changed = deepcopy(receipt)
            changed["handoff"][field] = forged
            with self.subTest(field=field), self.assertRaises(StudyPacketError):
                verify_review_handoff(
                    changed, page, queue, previews,
                    secret=self.secret, evidence_ids=item_id,
                )
        forged_history = deepcopy(receipt)
        forged_history["handoff"]["items"][0]["observation_history"][0][
            "citation_metadata"
        ]["rights_tag"] = "verified"
        with self.assertRaises(StudyPacketError):
            verify_review_handoff(
                forged_history, page, queue, previews,
                secret=self.secret, evidence_ids=item_id,
            )
        wrong = deepcopy(receipt)
        wrong["handoff_hmac_sha256"] = "f" * 64
        with self.assertRaises(StudyPacketError):
            verify_review_handoff(
                wrong, page, queue, previews,
                secret=self.secret, evidence_ids=item_id,
            )
        with self.assertRaises(StudyPacketError):
            verify_review_handoff(
                receipt, page, queue, previews,
                secret="Z" * 48, evidence_ids=item_id,
            )

    def test_invalid_selector_duplicate_and_extra_item_refused(self):
        previews, queue, page = self.changed()
        candidate = page["page"]["items"][0]["evidence_id"]
        for selector in (
            "", candidate + "," + candidate, candidate + ",",
            candidate + ",not-canonical",
        ):
            with self.subTest(selector=selector), self.assertRaises(
                StudyPacketError
            ):
                self.build(previews, queue, page, selector)
        with self.assertRaises(StudyPacketError):
            self.build(previews, queue, page, candidate, limit=0)

    def test_private_cli_create_verify_and_no_overwrite(self):
        previews, queue, page = self.changed()
        candidate = page["page"]["items"][0]["evidence_id"]
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            packets = []
            for index, packet in enumerate(previews):
                p = folder / f"packet-{index}.json"
                p.write_text(json.dumps(packet), encoding="utf-8")
                p.chmod(0o600)
                packets.append(p)
            queue_path = folder / "queue.json"
            page_path = folder / "page.json"
            queue_path.write_text(json.dumps(queue), encoding="utf-8")
            page_path.write_text(json.dumps(page), encoding="utf-8")
            queue_path.chmod(0o600)
            page_path.chmod(0o600)
            output = folder / "handoff.json"
            args = ["--queue", str(queue_path), "--page", str(page_path)]
            for packet in packets:
                args.extend(("--packet", str(packet)))
            args += [
                "--ids", candidate,
                "--token-path", str(self.fixture.key),
            ]
            self.assertEqual(handoff_cli([
                "build", *args, "--output", str(output),
            ]), 0)
            self.assertEqual(handoff_cli([
                "verify", *args, "--report", str(output),
            ]), 0)
            self.assertEqual(handoff_cli([
                "build", *args, "--output", str(output),
            ]), 1)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            tampered = json.loads(output.read_text(encoding="utf-8"))
            tampered["handoff"]["human_review_approved"] = True
            output.write_text(json.dumps(tampered), encoding="utf-8")
            self.assertEqual(handoff_cli([
                "verify", *args, "--report", str(output),
            ]), 1)
            page_path.chmod(0o644)
            self.assertEqual(handoff_cli([
                "build", *args, "--output", str(folder / "fresh.json"),
            ]), 1)


if __name__ == "__main__":
    unittest.main()
