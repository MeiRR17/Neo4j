"""v0.9.7 topology fixtures, query-plan stress matrix, CI denials."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from unittest import TestCase
from unittest.mock import patch

from scripts.analytics_stress_fixture_v097 import (
    CASES, MAX_NODE_IDS, SIZES, fixture_ids, stress_case,
)
from scripts.analytics_stress_v097 import (
    OPERATIONS, REPEATS, PlanEvidenceError, _compare_growth,
    main, run_case, run_stress, summarize_stress,
)


class FakeAdmin:
    def __init__(self, *_args, occupied=False, fail_seed=False,
                 fail_cleanup=False):
        self.calls = []
        self.occupied = occupied
        self.fail_seed = fail_seed
        self.fail_cleanup = fail_cleanup

    def query(self, statement, params):
        self.calls.append((statement, deepcopy(params)))
        if "MATCH (n) WHERE n.id IN $ids RETURN count(n)" in statement:
            return [[1 if self.occupied else 0]]
        if "UNWIND $rows AS item" in statement:
            if self.fail_seed:
                raise RuntimeError("Synthetic injection: partial seed.")
            return [[len(params["rows"])]]
        if "DETACH DELETE" in statement:
            return [[0 if self.fail_cleanup else len(params["ids"])]]
        return [["synthetic"]]


class FakeProfiler:
    def __init__(self, *_args):
        self.cost = 44
        self.case = None
        self.calls = []

    def profile(self, operation, params):
        self.calls.append((operation, deepcopy(params)))
        if operation == "incident_frequency":
            expected = 51 if self.case["topology"] == "hub" else 1
        elif operation == "work_descriptor":
            expected = 1
        else:
            expected = 11
        return {
            "operation": operation,
            "returned_rows": expected,
            "read_template_sha256": "a" * 64,
            "source_values_exposed": False,
            "representative_performance_proven": False,
            "db_hits": self.cost,
            "observed_wall_ms": 3.5,
            "operator_count": 3,
            "operator_types": [
                "NodeIndexSeek", "ExpandAll", "ProduceResults",
            ],
            "label_or_full_scan_detected": False,
            "source_text": "UNLICENSED must not appear in report",
        }


def samples(case, operation="forward_links", *, cost=42):
    result = []
    expected_rows = (
        case["incident_rows_expected"] if operation == "incident_frequency"
        else 1 if operation == "work_descriptor" else 11
    )
    for _ in range(REPEATS):
        result.append({
            "operation": operation,
            "returned_rows": expected_rows,
            "read_template_sha256": "d" * 64,
            "source_values_exposed": False,
            "representative_performance_proven": False,
            "db_hits": cost,
            "observed_wall_ms": 4.125,
            "operator_count": 2,
            "operator_types": ["NodeIndexSeek", "ProduceResults"],
            "label_or_full_scan_detected": False,
            "unsafe_details": "HIDDEN GRAPH CONTENT",
        })
    return result


class StressSuiteTests(TestCase):
    def test_four_exact_synthetic_cases_and_replay_hashes(self):
        self.assertEqual(CASES, (
            "disjoint-256", "hub-256", "disjoint-512", "hub-512"))
        self.assertEqual(SIZES, (256, 512))
        for name in CASES:
            with self.subTest(name=name):
                case = stress_case(name)
                self.assertEqual(case, stress_case(name))
                self.assertEqual(len(case["fixture_sha256"]), 64)
                self.assertEqual(len(case["edges"]), case["size"])
                self.assertEqual(len(fixture_ids(case)),
                                 case["synthetic_passage_count"] + case["size"] + 4)
                self.assertLessEqual(len(fixture_ids(case)), MAX_NODE_IDS)

    def test_skewed_hub_shares_only_the_expected_passage(self):
        for size in SIZES:
            with self.subTest(size=size):
                hub = stress_case(f"hub-{size}")
                disjoint = stress_case(f"disjoint-{size}")
                self.assertEqual(disjoint["synthetic_passage_count"], 2 * size)
                self.assertEqual(disjoint["max_source_out_degree"], 1)
                self.assertEqual(hub["max_source_out_degree"], size // 2)
                self.assertEqual(hub["synthetic_passage_count"], 3 * size // 2 + 1)
                self.assertEqual(sum(x["source_passage_id"] ==
                                     hub["hub_passage_id"] for x in hub["edges"]),
                                 size // 2)
                self.assertEqual(hub["incident_rows_expected"], 51)
                self.assertEqual(disjoint["incident_rows_expected"], 1)

    def test_unknown_fixture_inputs_rejected(self):
        for bad in (None, True, "hub-32", "skewed-512", "hub-1024",
                    "disjoint-512;DELETE", "hub-256 ", 512):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                stress_case(bad)

    def test_bounded_cost_summary_has_no_source_values(self):
        case = stress_case("hub-512")
        metrics = summarize_stress(case, "incident_frequency",
                                   samples(case, "incident_frequency"))
        self.assertEqual(metrics["observed_rows_each"], 51)
        self.assertEqual(metrics["db_hits_median"], 42)
        self.assertEqual(metrics["samples"], REPEATS)
        self.assertFalse(metrics["source_values_disclosed"])
        self.assertFalse(metrics["representative_performance_proven"])
        self.assertNotIn("HIDDEN GRAPH CONTENT", json.dumps(metrics))
        self.assertNotIn("unsafe_details", json.dumps(metrics))

    def test_cost_operator_flags_are_sanitized(self):
        case = stress_case("hub-256")
        rows = samples(case)
        rows[0]["operator_types"].append("CartesianProduct")
        metrics = summarize_stress(case, "forward_links", rows)
        self.assertTrue(metrics["potentially_expensive_join_observed"])
        self.assertNotIn("operator_types", metrics)

    def test_invalid_row_count_and_bad_plan_metrics_fail_closed(self):
        case = stress_case("disjoint-512")
        for edit in (
            {"returned_rows": 10},
            {"db_hits": 250_001},
            {"db_hits": True},
            {"observed_wall_ms": -3},
            {"observed_wall_ms": float("nan")},
            {"read_template_sha256": "tampered"},
            {"operator_types": "not-an-array"},
            {"source_values_exposed": True},
            {"representative_performance_proven": True},
        ):
            with self.subTest(edit=str(edit)[:40]):
                records = samples(case)
                records[0].update(edit)
                with self.assertRaises(PlanEvidenceError):
                    summarize_stress(case, "forward_links", records)

    def test_profile_failure_classification_never_leaks_exception_body(self):
        from scripts.analytics_stress_v097 import _safe_failure
        message = "PRIVATE SOURCE CONTENT AND GRAPH QUERY PLAN"
        self.assertEqual(
            _safe_failure(
                "forward_links", PlanEvidenceError(
                    "Graph profiler request unavailable.")),
            "stage_forward_links_reason_transport_or_timeout",
        )
        diagnostic = _safe_failure(
            "incident_frequency", PlanEvidenceError(message))
        self.assertEqual(
            diagnostic, "stage_incident_frequency_reason_unclassified_denial")
        self.assertNotIn("PRIVATE", diagnostic)

    def test_unknown_operation_and_missing_repeats_are_rejected(self):
        case = stress_case("disjoint-256")
        with self.assertRaises(PlanEvidenceError):
            summarize_stress(case, "DELETE_ALL", samples(case))
        with self.assertRaises(PlanEvidenceError):
            summarize_stress(case, "forward_links", samples(case)[:2])

    def test_case_success_seeds_profiles_and_cleans_exact_nodes(self):
        case = stress_case("hub-256")
        admin, profiler = FakeAdmin(), FakeProfiler()
        profiler.case = case
        result = run_case(admin, profiler, case)
        self.assertEqual(result["case"], "hub-256")
        self.assertEqual(result["synthetic_passage_count"], 385)
        self.assertEqual(result["max_source_out_degree"], 128)
        self.assertEqual(len(result["operations"]), 4)
        self.assertEqual(len(profiler.calls), 4 * REPEATS)
        self.assertIn("DETACH DELETE", admin.calls[-2][0])
        self.assertEqual(admin.calls[-2][1]["ids"], fixture_ids(case))
        self.assertIn("MATCH (n) WHERE n.id IN $ids RETURN count(n)", admin.calls[-1][0])
        self.assertNotIn("UNLICENSED", json.dumps(result))

    def test_no_overwrite_and_cleanup_even_on_failed_seed(self):
        case = stress_case("disjoint-256")
        admin = FakeAdmin(occupied=True)
        with self.assertRaises(PlanEvidenceError):
            run_case(admin, FakeProfiler(), case)
        self.assertEqual(len(admin.calls), 1)
        admin = FakeAdmin(fail_seed=True)
        with self.assertRaises(RuntimeError):
            run_case(admin, FakeProfiler(), case)
        self.assertIn("DETACH DELETE", admin.calls[-2][0])
        admin = FakeAdmin(fail_cleanup=True)
        profiler = FakeProfiler()
        profiler.case = case
        with self.assertRaises(PlanEvidenceError):
            run_case(admin, profiler, case)

    def test_guard_rejects_partial_matrix_or_missing_ci_approval(self):
        with patch.dict(os.environ, {"CI": "false"}):
            with self.assertRaises(ValueError):
                run_stress(acknowledged_disposable=True)
            self.assertEqual(main(["--ack-disposable-fixture"]), 2)
        with patch.dict(os.environ, {"CI": "true"}):
            self.assertEqual(main([]), 2)
            with self.assertRaises(ValueError):
                run_stress(cases=("hub-512",), acknowledged_disposable=True)

    def test_full_fake_stress_report_is_explicitly_unapproved(self):
        class CaseProfiler(FakeProfiler):
            def profile(self, operation, params):
                # Determine topology by fixture ID (the case is encoded in
                # stable namespaced IDs only as a hash; resolve through
                # known fixed fixture references, never user text).
                self.case = next(c for c in (
                    stress_case(name) for name in CASES)
                    if (params.get("work_id", params.get("source_work_id",
                         params.get("passage_id"))) in (
                             c["left_work_id"], c["right_work_id"],
                             c["edges"][0]["source_passage_id"]))
                )
                return super().profile(operation, params)
        with patch.dict(os.environ, {"CI": "true"}), \
             patch("scripts.analytics_stress_v097.LocalQueryClient",
                   FakeAdmin), \
             patch("scripts.analytics_stress_v097.FixedAnalyticsProfiler",
                   CaseProfiler):
            report = run_stress(acknowledged_disposable=True)
        self.assertEqual(report["schema_version"], "0.9.7")
        self.assertEqual(report["case_order"], list(CASES))
        self.assertEqual(len(report["case_results"]), 4)
        self.assertEqual(len(report["growth_by_topology"]), 2)
        self.assertEqual(report["research_release_status"], "HOLD")
        self.assertFalse(report["real_corpus_benchmarked"])
        self.assertFalse(report["representative_performance_proven"])
        self.assertFalse(report["query_regression_gate_enforced"])
        self.assertNotIn("UNLICENSED", json.dumps(report))

    def test_growth_factors_distinguish_disjoint_and_hub(self):
        records = []
        for name in CASES:
            case = stress_case(name)
            baseline = 100 if case["size"] == 256 else 230
            records.append({
                "case": name,
                "operations": [
                    {"operation": op, "db_hits_median": baseline}
                    for op in OPERATIONS
                ],
            })
        growth = _compare_growth(records)
        self.assertEqual(growth["hub"]["forward_links"]["observed_growth_factor"], 2.3)
        self.assertEqual(growth["disjoint"]["reverse_links"]["db_hits_at_512"], 230)


if __name__ == "__main__":
    import unittest
    unittest.main()
