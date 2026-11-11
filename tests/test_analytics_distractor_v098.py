"""v0.9.8 four-Work distractor graph fixtures and cost contracts."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from unittest import TestCase
from unittest.mock import patch

from research_graph.ontology import CANONICAL_ID_PATTERN
from scripts.analytics_distractor_fixture_v098 import (
    CASES, PRIMARY_EDGES, MAX_IDS, distractor_case, fixture_ids,
)
from scripts.analytics_distractor_v098 import (
    OPERATIONS, REPEATS, PlanEvidenceError, _compare_costs,
    main, run_case, run_matrix,
)


class FakeAdmin:
    def __init__(self, *_args, occupied=False, broken_seed=False,
                 bad_cleanup=False):
        self.calls = []
        self.occupied = occupied
        self.broken_seed = broken_seed
        self.bad_cleanup = bad_cleanup

    def query(self, statement, params):
        self.calls.append((statement, deepcopy(params)))
        if "RETURN count(n) AS count" in statement:
            return [[1 if self.occupied else 0]]
        if "RETURN wa.id AS sample" in statement:
            return [[params["left"]]]
        if "UNWIND $rows AS item" in statement:
            if self.broken_seed:
                raise RuntimeError("confidential injected seed failure")
            return [[len(params["rows"])]]
        if "DETACH DELETE" in statement:
            return [[0 if self.bad_cleanup else len(params["ids"])]]
        raise AssertionError("Unexpected fixture statement")


class FakeProfiler:
    def __init__(self, *_args):
        self.calls = []
        self.targets = {}
        for case_name in CASES:
            case = distractor_case(case_name)
            self.targets[case["left_work_id"]] = case_name
            self.targets[case["right_work_id"]] = case_name
            self.targets[case["edges"][0]["source_passage_id"]] = case_name

    def profile(self, operation, params):
        self.calls.append((operation, deepcopy(params)))
        key = params.get("work_id", params.get(
            "source_work_id", params.get("passage_id")))
        case_name = self.targets[key]
        n = int(case_name.split("-")[-1])
        # Synthetic mock cost deliberately stays constant as noise grows.
        hits = {"work_descriptor": 12, "forward_links": 1102,
                "reverse_links": 1102, "incident_frequency": 15}[operation]
        return {
            "operation": operation,
            "read_template_sha256": "a" * 64,
            "returned_rows": 1 if operation in (
                "work_descriptor", "incident_frequency") else 11,
            "source_values_exposed": False,
            "representative_performance_proven": False,
            "db_hits": hits,
            "observed_wall_ms": 2.0 + n / 10000,
            "operator_count": 3,
            "operator_types": [
                "NodeIndexSeek", "ExpandAll", "ProduceResults"],
            "label_or_full_scan_detected": False,
            "unsafe_source_text": "NEVER-PUBLISH",
        }


class DistractorMatrixTests(TestCase):
    def test_fixed_matrix_and_unique_canonical_id_inventory(self):
        self.assertEqual(CASES, (
            "control-0", "distractor-128", "distractor-512"))
        for name, extras in zip(CASES, (0, 128, 512)):
            with self.subTest(name=name):
                case = distractor_case(name)
                self.assertEqual(case, distractor_case(name))
                self.assertEqual(case["selected_edge_count"], 128)
                self.assertEqual(case["distractor_edge_count"], extras)
                self.assertEqual(len(case["edges"]), 128 + extras)
                self.assertEqual(len(fixture_ids(case)), 8 + 3 * (128 + extras))
                self.assertEqual(case["synthetic_node_count"], len(fixture_ids(case)))
                self.assertLessEqual(len(fixture_ids(case)), MAX_IDS)
                self.assertTrue(all(
                    CANONICAL_ID_PATTERN.fullmatch(item)
                    for item in fixture_ids(case)))
                self.assertEqual(len(case["fixture_sha256"]), 64)

    def test_unrelated_work_links_are_disjoint_from_selection(self):
        case = distractor_case("distractor-512")
        selected = case["edges"][:PRIMARY_EDGES]
        others = case["edges"][PRIMARY_EDGES:]
        selected_works = set(case["work_ids"][:2])
        unrelated_works = set(case["work_ids"][2:])
        self.assertEqual(len(selected), 128)
        self.assertEqual(len(others), 512)
        self.assertTrue(all(
            {row["source_work_id"], row["target_work_id"]} ==
            selected_works for row in selected))
        self.assertTrue(all(
            {row["source_work_id"], row["target_work_id"]} ==
            unrelated_works for row in others))
        self.assertFalse({
            item["evidence_id"] for item in selected
        } & {
            item["evidence_id"] for item in others
        })

    def test_unsupported_fixtures_fail_closed(self):
        for bad in (None, True, 0, "distractor-32", "distractor-1024",
                    "control-128", "control-0;DELETE", "distractor-512 "):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                distractor_case(bad)

    def test_profile_only_returns_bounded_sanitized_metrics(self):
        case = distractor_case("distractor-128")
        admin, profiler = FakeAdmin(), FakeProfiler()
        result = run_case(admin, profiler, case)
        self.assertEqual(result["total_source_link_count"], 256)
        self.assertEqual(result["selected_source_link_count"], 128)
        self.assertEqual(result["distractor_source_link_count"], 128)
        self.assertEqual(len(result["operations"]), len(OPERATIONS))
        self.assertEqual(len(profiler.calls), len(OPERATIONS) * REPEATS)
        self.assertTrue(all(x["source_values_disclosed"] is False
                            for x in result["operations"]))
        self.assertNotIn("NEVER-PUBLISH", json.dumps(result))
        self.assertIn("DETACH DELETE", admin.calls[-2][0])
        self.assertEqual(admin.calls[-2][1]["ids"], fixture_ids(case))
        self.assertIn("RETURN count(n)", admin.calls[-1][0])

    def test_preseed_occupation_never_writes(self):
        admin = FakeAdmin(occupied=True)
        with self.assertRaises(PlanEvidenceError):
            run_case(admin, FakeProfiler(), distractor_case("control-0"))
        self.assertEqual(len(admin.calls), 1)
        self.assertNotIn("MERGE", admin.calls[0][0])

    def test_failed_seed_always_attempts_exact_cleanup(self):
        case = distractor_case("distractor-512")
        admin = FakeAdmin(broken_seed=True)
        with self.assertRaises(RuntimeError):
            run_case(admin, FakeProfiler(), case)
        self.assertIn("DETACH DELETE", admin.calls[-2][0])
        self.assertEqual(admin.calls[-2][1]["ids"], fixture_ids(case))
        admin = FakeAdmin(bad_cleanup=True)
        with self.assertRaises(PlanEvidenceError):
            run_case(admin, FakeProfiler(), case)

    def test_ratio_is_numeric_and_ignores_unsafe_details(self):
        records = []
        for name, n in zip(CASES, (0, 128, 512)):
            records.append({
                "case": name,
                "operations": [
                    {"operation": op, "db_hits_median": 100 + n // 4,
                     "source_text": "HIDDEN"}
                    for op in OPERATIONS],
            })
        comparisons = _compare_costs(records)
        self.assertEqual(comparisons["control-0"]["forward_links"]
                         ["ratio_to_control"], 1.0)
        self.assertEqual(comparisons["distractor-512"]["forward_links"]
                         ["ratio_to_control"], 2.28)
        self.assertNotIn("HIDDEN", json.dumps(comparisons))

    def test_reject_malformed_cost_matrix(self):
        records = [
            {"case": name, "operations": [
                {"operation": op, "db_hits_median": 12}
                for op in OPERATIONS]}
            for name in CASES
        ]
        broken = deepcopy(records)
        broken[1]["case"] = "control-0"
        with self.assertRaises(PlanEvidenceError):
            _compare_costs(broken)
        broken = deepcopy(records)
        broken[2]["operations"][0]["db_hits_median"] = True
        with self.assertRaises(PlanEvidenceError):
            _compare_costs(broken)
        broken = deepcopy(records)
        broken[0]["operations"][1]["operation"] = "DELETE"
        with self.assertRaises(PlanEvidenceError):
            _compare_costs(broken)

    def test_cli_and_library_both_need_disposable_ci_approval(self):
        with patch.dict(os.environ, {"CI": "false"}):
            self.assertEqual(main(["--ack-disposable-fixture"]), 2)
            with self.assertRaises(ValueError):
                run_matrix(acknowledged_disposable=True)
        with patch.dict(os.environ, {"CI": "true"}):
            self.assertEqual(main([]), 2)
            with self.assertRaises(ValueError):
                run_matrix(cases=("control-0",), acknowledged_disposable=True)

    def test_full_matrix_mocked_without_release_approval(self):
        with patch.dict(os.environ, {"CI": "true"}), \
             patch("scripts.analytics_distractor_v098.LocalQueryClient",
                   FakeAdmin), \
             patch("scripts.analytics_distractor_v098.FixedAnalyticsProfiler",
                   FakeProfiler):
            report = run_matrix(acknowledged_disposable=True)
        self.assertEqual(report["schema_version"], "0.9.8")
        self.assertEqual(report["case_order"], list(CASES))
        self.assertEqual(len(report["case_results"]), 3)
        self.assertTrue(all(
            v["ratio_to_control"] == 1.0
            for case in report["interference_vs_control"].values()
            for v in case.values()))
        self.assertEqual(report["research_release_status"], "HOLD")
        self.assertFalse(report["real_corpus_benchmarked"])
        self.assertFalse(report["new_cost_gate_enforced"])
        self.assertFalse(report["representative_performance_proven"])
        self.assertNotIn("NEVER-PUBLISH", json.dumps(report))


if __name__ == "__main__":
    import unittest
    unittest.main()
