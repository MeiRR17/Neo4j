"""v0.8.8 reviewer workflow: synthetic fixtures and independent human-claim gates."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from scripts.search_quality_eval import read_evidence, evaluate
from scripts.search_review_workflow import (
    ReviewWorkflowError, _write_private, prepare_packet, reviewer_template,
    freeze_reviews, main,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CATALOG = FIXTURES / "search_review_questions_synthetic.json"
CAPTURES = FIXTURES / "search_quality_responses_synthetic.json"


class ReviewPacketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog, cls.chash = read_evidence(CATALOG)
        cls.captures, cls.rhash = read_evidence(CAPTURES)

    def packet(self):
        return prepare_packet(
            copy.deepcopy(self.catalog), copy.deepcopy(self.captures),
            catalog_hash=self.chash, captures_hash=self.rhash)

    def form(self, packet, reviewer):
        return reviewer_template(packet, packet_hash="a" * 64,
                                 reviewer_id=reviewer)

    @staticmethod
    def fill(form, change=None):
        for n, row in enumerate(form["labels"]):
            row["relevance"] = int(n % 5 < 4)
            row["evidence_ref"] = "SYNTHETIC:REVIEW:" + str(n)
        if change:
            form["labels"][0]["relevance"] = change
        return form

    def test_metadata_packet_does_not_invent_judgments(self):
        packet = self.packet()
        self.assertEqual(packet["schema_version"], "0.8.8")
        self.assertEqual(packet["review_status"], "UNREVIEWED")
        self.assertEqual(packet["catalog_sha256"], self.chash)
        self.assertEqual(packet["captures_sha256"], self.rhash)
        self.assertEqual([len(q["hits"]) for q in packet["questions"]], [5, 5])
        self.assertEqual(packet["questions"][0]["search_schema"], "0.8.2")
        self.assertEqual(packet["questions"][1]["search_schema"], "0.8.3")
        self.assertTrue(all("relevance" not in hit for q in packet["questions"] for hit in q["hits"]))
        self.assertNotIn("excerpt", json.dumps(packet))

    def test_templates_require_manual_labels(self):
        packet = self.packet()
        first = self.form(packet, "SYNTHETIC_A")
        second = self.form(packet, "SYNTHETIC_B")
        self.assertTrue(all(x["relevance"] is None for x in first["labels"]))
        with self.assertRaises(ReviewWorkflowError):
            freeze_reviews(packet, packet_hash="a"*64,
                           first=first, second=second)

    def test_two_independent_agreeing_synthetic_reviewers_freeze_for_evaluator(self):
        packet = self.packet()
        a = self.fill(self.form(packet, "SYNTHETIC_A"))
        b = self.fill(self.form(packet, "SYNTHETIC_B"))
        judgments, audit = freeze_reviews(
            packet, packet_hash="a"*64, first=a, second=b,
            review_hashes=("b"*64, "c"*64))
        self.assertEqual(judgments["dataset_kind"], "synthetic")
        self.assertEqual(audit["disagreements_adjudicated"], 0)
        self.assertEqual(audit["judgments"], 10)
        self.assertEqual(evaluate(judgments, self.captures)["mean_precision_at_5_eligible_only"], 0.8)
        self.assertFalse(evaluate(judgments, self.captures)["quality_target_observed"])
        self.assertFalse(audit["independent_reviewer_identity_verified"])
        self.assertEqual(audit["production_release_status"], "HOLD")

    def test_conflicts_require_explicit_third_distinct_reviewer(self):
        packet = self.packet()
        a = self.fill(self.form(packet, "SYNTHETIC_A"))
        b = self.fill(self.form(packet, "SYNTHETIC_B"))
        b["labels"][0]["relevance"] = 0
        with self.assertRaises(ReviewWorkflowError):
            freeze_reviews(packet, packet_hash="a"*64, first=a, second=b)
        third = reviewer_template(packet, packet_hash="a"*64,
                                  reviewer_id="SYNTHETIC_C")
        third["labels"] = [dict(a["labels"][0])]
        frozen, audit = freeze_reviews(
            packet, packet_hash="a"*64, first=a, second=b, third=third)
        self.assertEqual(audit["disagreements_adjudicated"], 1)
        self.assertEqual(frozen["queries"][0]["judgments"][0]["reviewer_id"], "SYNTHETIC_C")
        third["reviewer_id"] = "SYNTHETIC_A"
        with self.assertRaises(ReviewWorkflowError):
            freeze_reviews(packet, packet_hash="a"*64,
                           first=a, second=b, third=third)
        third["reviewer_id"] = "SYNTHETIC_C"
        third["labels"][0]["relevance"] = None
        with self.assertRaises(ReviewWorkflowError):
            freeze_reviews(packet, packet_hash="a"*64,
                           first=a, second=b, third=third)

    def test_rejects_forged_packet_hash_and_duplicate_rows(self):
        packet = self.packet()
        a = self.fill(self.form(packet, "SYNTHETIC_A"))
        b = self.fill(self.form(packet, "SYNTHETIC_B"))
        a["packet_sha256"] = "b"*64
        with self.assertRaises(ReviewWorkflowError):
            freeze_reviews(packet, packet_hash="a"*64, first=a, second=b)
        a["packet_sha256"] = "a"*64
        b["labels"][1]["id"] = b["labels"][0]["id"]
        with self.assertRaises(ReviewWorkflowError):
            freeze_reviews(packet, packet_hash="a"*64, first=a, second=b)

    def test_rejects_incomplete_captures_and_unlicensed_text(self):
        for variant in ("incomplete", "source_text", "missing_anchor", "too_few"):
            with self.subTest(variant=variant):
                captures = copy.deepcopy(self.captures)
                page = captures["responses"][0]["pages"][0]
                if variant == "incomplete":
                    page["search_complete"] = False
                    page["has_more"] = True
                    page["next_cursor"] = page["items"][-1]["id"]
                elif variant == "source_text":
                    page["items"][0]["excerpt"] = "UNLICENSED"
                elif variant == "missing_anchor":
                    page["items"][0]["source_anchor"] = None
                elif variant == "too_few":
                    page["items"].pop()
                with self.assertRaises(ReviewWorkflowError):
                    prepare_packet(self.catalog, captures,
                                   catalog_hash=self.chash, captures_hash=self.rhash)

    def test_private_output_is_0600_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)/"packet.json"
            _write_private(target, self.packet())
            self.assertEqual(os.stat(target).st_mode & 0o777, 0o600)
            contents = target.read_bytes()
            with self.assertRaises(FileExistsError):
                _write_private(target, self.packet())
            self.assertEqual(target.read_bytes(), contents)

    def test_cli_prepares_unfilled_template_offline_only(self):
        with tempfile.TemporaryDirectory() as dirname:
            packet = Path(dirname)/"packet.json"
            template = Path(dirname)/"reviewer.json"
            self.assertEqual(main(["prepare", "--questions", str(CATALOG),
                                   "--responses", str(CAPTURES),
                                   "--output", str(packet)]), 0)
            self.assertEqual(main(["template", "--packet", str(packet),
                                   "--reviewer-id", "SYNTHETIC_A",
                                   "--output", str(template)]), 0)
            self.assertIsNone(read_evidence(template)[0]["labels"][0]["relevance"])
            self.assertEqual(main(["template", "--packet", str(packet),
                                   "--reviewer-id", "SYNTHETIC_A",
                                   "--output", str(template)]), 2)

    def test_declared_human_review_remains_unverified_and_on_hold(self):
        packet = self.packet()
        packet["dataset_kind"] = "candidate_human"
        a = self.fill(self.form(packet, "DECLARED_A"))
        b = self.fill(self.form(packet, "DECLARED_B"))
        frozen, audit = freeze_reviews(packet, packet_hash="a"*64,
                                       first=a, second=b)
        self.assertEqual(frozen["dataset_kind"], "human_reviewed")
        self.assertFalse(audit["independent_reviewer_identity_verified"])
        self.assertFalse(evaluate(frozen, self.captures)["external_human_review_verified"])
        self.assertEqual(audit["production_release_status"], "HOLD")


if __name__ == "__main__":
    unittest.main()
