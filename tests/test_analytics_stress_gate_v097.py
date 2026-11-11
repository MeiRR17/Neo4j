"""v0.9.7 measured synthetic fanout/distribution dbHits cost gate."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
from unittest import TestCase

from scripts.analytics_stress_fixture_v097 import CASES, stress_case
from scripts.analytics_stress_gate_v097 import (
    BUDGET, StressGateError, check_synthetic_stress, main,
)
from scripts.analytics_stress_v097 import OPERATIONS, REPEATS


MEASURED = {
    "disjoint-256": [12, 2126, 2126, 15],
    "hub-256": [12, 1873, 2126, 1386],
    "disjoint-512": [12, 4174, 4174, 15],
    "hub-512": [12, 3665, 4174, 2666],
}


def fixture_report():
    cases = []
    for name in CASES:
        case = stress_case(name)
        profiles = []
        for operation, cost in zip(OPERATIONS, MEASURED[name]):
            expected_rows = (
                case["incident_rows_expected"]
                if operation == "incident_frequency"
                else 1 if operation == "work_descriptor" else 11
            )
            profiles.append({
                "operation": operation,
                "read_template_sha256": "f" * 64,
                "observed_rows_each": expected_rows,
                "samples": REPEATS,
                "db_hits_min": cost,
                "db_hits_median": cost,
                "db_hits_max": cost,
                "http_wall_p50_ms": 3.4,
                "http_wall_p95_nearest_rank_ms": 4.4,
                "max_plan_operators": 12,
                "label_or_full_scan_observed": False,
                "potentially_expensive_join_observed": False,
                "source_values_disclosed": False,
                "representative_performance_proven": False,
            })
        cases.append({
            "case": name, "topology": case["topology"],
            "source_link_count": case["size"],
            "synthetic_passage_count": case["synthetic_passage_count"],
            "synthetic_evidence_count": case["size"],
            "synthetic_work_count": 2, "synthetic_author_count": 2,
            "max_source_out_degree": case["max_source_out_degree"],
            "fixture_sha256": case["fixture_sha256"],
            "operations": profiles,
            "real_corpus_benchmarked": False,
        })
    return {
        "schema_version": "0.9.7",
        "case_order": list(CASES),
        "case_results": cases,
        "observed_costs_only": True,
        "query_regression_gate_enforced": False,
        "source_values_disclosed": False,
        "credentials_disclosed": False,
        "source_rights_verified": False,
        "historical_influence_proven": False,
        "real_corpus_benchmarked": False,
        "representative_performance_proven": False,
        "research_release_status": "HOLD",
    }


class StressGateTests(TestCase):
    def test_observed_256_512_costs_fit_conservative_fixed_budgets(self):
        results = check_synthetic_stress(fixture_report())
        self.assertEqual(results["case_order"], list(CASES))
        self.assertEqual(results["observed_median_db_hits"]["hub-512"]
                         ["incident_frequency"], 2666)
        self.assertEqual(results["observed_256_to_512_growth"]["hub"]
                         ["forward_links"], 1.957)
        self.assertTrue(results["fixed_fixture_budget_enforced"])
        self.assertTrue(results["synthetic_stress_gate_passed"])
        self.assertEqual(results["research_release_status"], "HOLD")

    def test_high_fanout_incident_regression_refused(self):
        bad = fixture_report()
        bad["case_results"][3]["operations"][3]["db_hits_min"] = 3801
        bad["case_results"][3]["operations"][3]["db_hits_median"] = 3801
        bad["case_results"][3]["operations"][3]["db_hits_max"] = 3801
        with self.assertRaises(StressGateError):
            check_synthetic_stress(bad)

    def test_cross_work_quadratic_regression_refused(self):
        bad = fixture_report()
        row = bad["case_results"][2]["operations"][1]
        row["db_hits_min"] = row["db_hits_median"] = row["db_hits_max"] = 66_382
        with self.assertRaises(StressGateError):
            check_synthetic_stress(bad)

    def test_incomplete_or_forged_fixture_rejected(self):
        baseline = fixture_report()
        variants = [
            lambda r: r["case_results"].pop(),
            lambda r: r["case_results"][0].update(fixture_sha256="0"*64),
            lambda r: r["case_results"][1].update(max_source_out_degree=1),
            lambda r: r["case_results"][3].update(synthetic_passage_count=100),
            lambda r: r.update(research_release_status="APPROVED"),
            lambda r: r.update(real_corpus_benchmarked=True),
            lambda r: r["case_results"].reverse(),
        ]
        for change in variants:
            with self.subTest(change=str(change)[:75]):
                record = deepcopy(baseline)
                change(record)
                with self.assertRaises(StressGateError):
                    check_synthetic_stress(record)

    def test_malformed_plan_and_unlicensed_values_rejected(self):
        baseline = fixture_report()
        variants = [
            lambda r: r["case_results"][0]["operations"][0].update(source_text="SECRET"),
            lambda r: r["case_results"][1]["operations"][1].update(
                label_or_full_scan_observed=True),
            lambda r: r["case_results"][3]["operations"][2].update(
                potentially_expensive_join_observed=True),
            lambda r: r["case_results"][1]["operations"][3].update(
                observed_rows_each=50),
            lambda r: r["case_results"][0]["operations"][1].update(samples=1),
            lambda r: r["case_results"][0]["operations"][1].update(
                read_template_sha256="NOT_A_DIGEST"),
            lambda r: r["case_results"][0]["operations"][1].update(
                db_hits_max=True),
        ]
        for change in variants:
            with self.subTest(change=str(change)[:65]):
                record = deepcopy(baseline)
                change(record)
                with self.assertRaises(StressGateError):
                    check_synthetic_stress(record)

    def test_budget_tamper_or_nonmonotonic_statistic_denied(self):
        record = fixture_report()
        record["case_results"][0]["operations"][0]["db_hits_max"] = 3
        with self.assertRaises(StressGateError):
            check_synthetic_stress(record)
        self.assertEqual(BUDGET["hub-512"]["incident_frequency"], 3800)
        self.assertEqual(BUDGET["disjoint-256"]["forward_links"], 3000)

    def test_output_never_propagates_untrusted_graph_rows(self):
        record = fixture_report()
        output = check_synthetic_stress(record)
        out = json.dumps(output)
        self.assertNotIn("source_ref", out)
        self.assertNotIn("operator_types", out)
        self.assertNotIn("fixture_sha256", out)
        self.assertFalse(output["representative_performance_proven"])
        self.assertFalse(output["historical_influence_proven"])

    def test_cli_validates_and_rejects_large_or_symlink_inputs(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            input_file = directory / "stress.json"
            output_file = directory / "gate.json"
            args = ["--input", str(input_file), "--output", str(output_file)]
            input_file.write_text(json.dumps(fixture_report()), encoding="utf-8")
            self.assertEqual(main(args), 0)
            output = json.loads(output_file.read_text())
            self.assertTrue(output["synthetic_stress_gate_passed"])
            alias = directory / "alias.json"
            alias.symlink_to(input_file)
            self.assertEqual(main(["--input", str(alias),
                                   "--output", str(output_file)]), 1)
            input_file.write_bytes(b"q" * 40_000)
            self.assertEqual(main(args), 1)


if __name__ == "__main__":
    import unittest
    unittest.main()
