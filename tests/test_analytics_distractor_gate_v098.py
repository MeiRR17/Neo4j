"""v0.9.8 fail-closed fixed Work-distractor regression-gate tests."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch

from scripts.analytics_distractor_gate_v098 import (
    BUDGET, DistractorGateError, check_distractor_gate, main,
)
from scripts.analytics_distractor_v098 import run_matrix
from tests.test_analytics_distractor_v098 import FakeAdmin, FakeProfiler


def sample():
    with patch.dict(os.environ, {"CI": "true"}), \
         patch("scripts.analytics_distractor_v098.LocalQueryClient",
               FakeAdmin), \
         patch("scripts.analytics_distractor_v098.FixedAnalyticsProfiler",
               FakeProfiler):
        return run_matrix(acknowledged_disposable=True)


class DistractorGateTests(TestCase):
    def test_exact_three_case_fixture_gate_passes(self):
        result = check_distractor_gate(sample())
        self.assertTrue(result["synthetic_selectivity_gate_passed"])
        self.assertTrue(result["fixed_fixture_budget_enforced"])
        self.assertEqual(result["maximum_interference_ratio"], 1.25)
        self.assertEqual(result["observed_median_db_hits"]["distractor-512"]
                         ["forward_links"], 1102)
        self.assertEqual(result["per_operation_db_hits_limits"], BUDGET)
        self.assertEqual(result["research_release_status"], "HOLD")
        self.assertFalse(result["production_slo_verified"])
        self.assertFalse(result["representative_performance_proven"])

    def test_broken_fixture_hash_or_size_is_denied(self):
        for key, value in (("fixture_sha256", "f" * 64),
                           ("synthetic_node_count", 123),
                           ("total_source_link_count", 999),
                           ("selected_source_link_count", 129)):
            bad = sample()
            bad["case_results"][2][key] = value
            with self.subTest(key=key), self.assertRaises(DistractorGateError):
                check_distractor_gate(bad)

    def test_deny_unexpected_fields_and_unsafe_research_claims(self):
        baseline = sample()
        for path, value in (
            ("new_cost_gate_enforced", True),
            ("real_corpus_benchmarked", True),
            ("source_rights_verified", True),
            ("production_slo_verified", True),
            ("research_release_status", "PASS"),
            ("case_order", ["distractor-512"]),
        ):
            bad = deepcopy(baseline)
            bad[path] = value
            with self.subTest(field=path), self.assertRaises(DistractorGateError):
                check_distractor_gate(bad)
        extra = deepcopy(baseline)
        extra["private_source_text"] = "HIDDEN"
        with self.assertRaises(DistractorGateError):
            check_distractor_gate(extra)

    def test_deny_full_scan_expensive_join_and_raw_source(self):
        baseline = sample()
        for key, value in (
            ("label_or_full_scan_observed", True),
            ("potentially_expensive_join_observed", True),
            ("source_values_disclosed", True),
            ("samples", 2),
            ("observed_rows_each", 51),
            ("read_template_sha256", "INVALID"),
        ):
            bad = deepcopy(baseline)
            bad["case_results"][1]["operations"][1][key] = value
            with self.subTest(key=key), self.assertRaises(DistractorGateError):
                check_distractor_gate(bad)
        raw = deepcopy(baseline)
        raw["case_results"][0]["operations"][1]["raw_cypher"] = "DELETE ALL"
        with self.assertRaises(DistractorGateError):
            check_distractor_gate(raw)

    def test_absolute_db_hits_ceiling_fails_even_with_valid_ratio(self):
        bad = sample()
        op = bad["case_results"][1]["operations"][1]
        op["db_hits_min"] = 1800
        op["db_hits_median"] = 1800
        op["db_hits_max"] = 1800
        with self.assertRaises(DistractorGateError):
            check_distractor_gate(bad)

    def test_interference_ratio_enforced_independently_of_absolute_ceiling(self):
        bad = sample()
        metric = bad["case_results"][2]["operations"][1]
        for key in ("db_hits_min", "db_hits_median", "db_hits_max"):
            metric[key] = 1502  # under 1600 ceiling, but >25% overhead
        row = bad["interference_vs_control"]["distractor-512"]["forward_links"]
        row["observed_db_hits"] = 1502
        row["added_db_hits"] = 400
        row["ratio_to_control"] = round(1502 / 1102, 3)
        with self.assertRaises(DistractorGateError):
            check_distractor_gate(bad)

    def test_tampered_control_ratio_or_boolean_hit_is_rejected(self):
        bad = sample()
        bad["interference_vs_control"]["distractor-128"]["forward_links"][
            "ratio_to_control"] = 0.1
        with self.assertRaises(DistractorGateError):
            check_distractor_gate(bad)
        bad = sample()
        bad["case_results"][0]["operations"][0]["db_hits_median"] = True
        with self.assertRaises(DistractorGateError):
            check_distractor_gate(bad)

    def test_missing_case_or_duplicate_operation_is_rejected(self):
        bad = sample()
        bad["case_results"] = bad["case_results"][:2]
        with self.assertRaises(DistractorGateError):
            check_distractor_gate(bad)
        bad = sample()
        bad["case_results"][0]["operations"][1] = deepcopy(
            bad["case_results"][0]["operations"][0])
        with self.assertRaises(DistractorGateError):
            check_distractor_gate(bad)

    def test_cli_emits_sanitized_artifact_and_blocks_symlinks(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / "report.json"
            q = Path(root) / "approved-synthetic.json"
            p.write_text(json.dumps(sample()), encoding="utf-8")
            args = ["--input", str(p), "--output", str(q)]
            self.assertEqual(main(args), 0)
            summary = json.loads(q.read_text(encoding="utf-8"))
            self.assertTrue(summary["synthetic_selectivity_gate_passed"])
            self.assertNotIn("source_ref", json.dumps(summary))
            sym = Path(root) / "symbolic.json"
            sym.symlink_to(p)
            self.assertEqual(main(["--input", str(sym),
                                   "--output", str(q)]), 1)
            p.write_bytes(b"x" * 65_537)
            self.assertEqual(main(args), 1)


if __name__ == "__main__":
    import unittest
    unittest.main()
