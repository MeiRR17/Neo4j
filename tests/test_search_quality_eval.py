"""Strict frozen search-quality evidence evaluation; no network or human labels."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.search_quality_eval import (
    QualityEvidenceError, evaluate, main, read_evidence,
)

ROOT = Path(__file__).resolve().parent / "fixtures"
JUDGMENTS = ROOT / "search_quality_judgments_synthetic.json"
CAPTURES = ROOT / "search_quality_responses_synthetic.json"


class FrozenQualityEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.judgments, cls.jhash = read_evidence(JUDGMENTS)
        cls.captures, cls.chash = read_evidence(CAPTURES)

    def test_two_language_synthetic_fixture_is_explicitly_not_release_quality(self):
        report = evaluate(self.judgments, self.captures,
                          hashes=(self.jhash, self.chash))
        self.assertEqual(report["questions_total"], 2)
        self.assertEqual(report["eligible_questions"], 2)
        self.assertEqual(report["mean_precision_at_5_eligible_only"], 0.8)
        self.assertFalse(report["quality_target_observed"])
        self.assertFalse(report["external_human_review_verified"])
        self.assertEqual(report["production_release_status"], "HOLD")
        self.assertEqual(report["judgments_sha256"], self.jhash)
        self.assertEqual(report["captures_sha256"], self.chash)
        self.assertTrue(all(q["eligible"] for q in report["cases"]))
        self.assertNotIn("SYNTHETIC WORK", json.dumps(report))

    def test_unjudged_hit_disables_score_not_assumed_nonrelevant(self):
        responses = copy.deepcopy(self.captures)
        responses["responses"][0]["pages"][0]["items"][0]["id"] = (
            "work:" + "a" * 64
        )
        r = evaluate(self.judgments, responses)
        self.assertEqual(r["unjudged_hits_top5"], 1)
        self.assertEqual(r["unscorable_queries"], 1)
        self.assertIsNone(r["cases"][1]["precision_at_5"] if
                          r["cases"][1]["id"] == "q-he-001" else
                          r["cases"][0]["precision_at_5"])
        self.assertEqual(r["eligible_questions"], 1)

    def test_incomplete_scan_page_never_produces_precision(self):
        responses = copy.deepcopy(self.captures)
        page = responses["responses"][0]["pages"][0]
        page["has_more"] = True
        page["search_complete"] = False
        page["next_cursor"] = "work:" + "b" * 64
        r = evaluate(self.judgments, responses)
        self.assertEqual(r["incomplete_queries"], 1)
        self.assertEqual(r["unscorable_queries"], 1)

    def test_missing_source_anchor_disables_score(self):
        captures = copy.deepcopy(self.captures)
        captures["responses"][0]["pages"][0]["items"][0]["source_anchor"] = None
        result = evaluate(self.judgments, captures)
        self.assertEqual(result["missing_source_anchors"], 1)
        self.assertEqual(result["eligible_questions"], 1)

    def test_rejects_duplicate_and_cross_kind_judgments(self):
        for change in ("duplicate", "kind", "reviewer", "judged_count", "bool_label"):
            with self.subTest(change=change):
                judgments = copy.deepcopy(self.judgments)
                q = judgments["queries"][0]
                if change == "duplicate":
                    q["judgments"][1]["id"] = q["judgments"][0]["id"]
                elif change == "kind":
                    q["judgments"][0]["id"] = "passage:" + "1" * 64
                elif change == "reviewer":
                    q["judgments"][0]["reviewer_id"] = ""
                elif change == "judged_count":
                    q["judgments"].pop()
                else:
                    q["judgments"][0]["relevance"] = True
                with self.assertRaises(QualityEvidenceError):
                    evaluate(judgments, self.captures)

    def test_rejects_missing_or_duplicated_capture_and_excess_items(self):
        variants = []
        copies = copy.deepcopy(self.captures)
        copies["responses"][1]["id"] = copies["responses"][0]["id"]
        variants.append(copies)
        wrong = copy.deepcopy(self.captures)
        wrong["responses"][1]["pages"][0]["kind"] = "persons"
        variants.append(wrong)
        overflow = copy.deepcopy(self.captures)
        overflow["responses"][0]["pages"][0]["items"] *= 5
        variants.append(overflow)
        replay = copy.deepcopy(self.captures)
        replay["responses"][0]["pages"][0]["items"][1] = replay[
            "responses"][0]["pages"][0]["items"][0]
        variants.append(replay)
        for malformed in variants:
            with self.subTest(malformed=malformed["responses"][0]["id"]):
                with self.assertRaises(QualityEvidenceError):
                    evaluate(self.judgments, malformed)

    def test_rejects_unsupported_rights_promotion_or_content(self):
        for key, value in (("review_status", "approved"),
                           ("rights_status", "CLEARED"),
                           ("text_available", True),
                           ("excerpt", "unlicensed text")):
            captured = copy.deepcopy(self.captures)
            captured["responses"][0]["pages"][0]["items"][0][key] = value
            with self.subTest(key=key), self.assertRaises(QualityEvidenceError):
                evaluate(self.judgments, captured)

    def test_rejects_lying_pagination_and_repeated_cursors(self):
        captured = copy.deepcopy(self.captures)
        p = captured["responses"][0]["pages"][0]
        p["has_more"] = True
        with self.assertRaises(QualityEvidenceError):
            evaluate(self.judgments, captured)
        captured = copy.deepcopy(self.captures)
        p = captured["responses"][0]["pages"][0]
        p["has_more"] = True
        p["search_complete"] = False
        p["next_cursor"] = "work:" + "a"*64
        captured["responses"][0]["pages"].append({
            **p, "items": [], "next_cursor": "work:" + "a"*64
        })
        with self.assertRaises(QualityEvidenceError):
            evaluate(self.judgments, captured)

    def test_self_declared_fifty_human_queries_is_not_release_approval(self):
        judgment = copy.deepcopy(self.judgments)
        captured = copy.deepcopy(self.captures)
        judgment["dataset_kind"] = "human_reviewed"
        judgment["queries"] = []
        captured["responses"] = []
        for n in range(50):
            q = copy.deepcopy(self.judgments["queries"][n % 2])
            p = copy.deepcopy(self.captures["responses"][n % 2])
            q["id"] = p["id"] = "q-replicated-%03d" % n
            q["judgments"] = [{**row, "reviewer_id": "DECLARED_NOT_VERIFIED"}
                               for row in q["judgments"]]
            judgment["queries"].append(q)
            captured["responses"].append(p)
        result = evaluate(judgment, captured)
        self.assertTrue(result["quality_target_observed"])
        self.assertFalse(result["external_human_review_verified"])
        self.assertEqual(result["production_release_status"], "HOLD")

    def test_duplicate_json_keys_and_synthetic_strict_gate(self):
        with tempfile.TemporaryDirectory() as root:
            bad = Path(root) / "duplicates.json"
            bad.write_text('{"schema_version":"0.8.7","schema_version":"0.8.7"}')
            with self.assertRaises(QualityEvidenceError):
                read_evidence(bad)
        self.assertEqual(main(["--judgments", str(JUDGMENTS),
                               "--responses", str(CAPTURES)]), 0)
        self.assertEqual(main(["--judgments", str(JUDGMENTS),
                               "--responses", str(CAPTURES),
                               "--require-quality-target"]), 1)


if __name__ == "__main__":
    unittest.main()
