"""v0.9.6 pinned synthetic dbHits delta and index-anchored query guard."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest

from scripts.analytics_cost_delta_v096 import (
    BASELINE_ARTIFACT_ID, BASELINE_DB_HITS, BASELINE_RUN_ID,
    DeltaError, compare_cost_report, main,
)
from services.research_api.queries import READ_OPERATIONS


def report(*, forward32=4366, forward128=66382):
    cases = []
    for size in (32, 128):
        plans = []
        for operation, old in BASELINE_DB_HITS[size].items():
            median = old
            if operation in ("forward_links", "reverse_links"):
                median = forward32 if size == 32 else forward128
            plans.append({
                "operation": operation,
                "fixed_query_sha256": "a" * 64,
                "db_hits_median": median,
                "sample_count": 3,
                "source_values_exposed": False,
                "representative_performance_proven": False,
                "operator_types": ["DO NOT COPY ARBITRARY CONTENT"],
                "source_record": "not permitted in public delta output",
            })
        cases.append({
            "size": size,
            "synthetic_source_link_count": size,
            "synthetic_work_count": 2,
            "synthetic_author_count": 2,
            "representative_performance_proven": False,
            "operation_profiles": plans,
        })
    return {
        "schema_version": "0.9.5",
        "research_release_status": "HOLD",
        "real_corpus_benchmarked": False,
        "representative_performance_proven": False,
        "case_values_disclosed": False,
        "sizes": cases,
    }


class AnalyticsCostDeltaTests(unittest.TestCase):
    def test_baseline_is_exactly_pinned_and_does_not_claim_improvement(self):
        result = compare_cost_report(report())
        self.assertEqual(result["baseline_run_id"], BASELINE_RUN_ID)
        self.assertEqual(result["baseline_artifact_id"], BASELINE_ARTIFACT_ID)
        self.assertEqual(result["fixture_scales"], [32, 128])
        for size in ("32", "128"):
            for metric in result["cost_comparisons"][size].values():
                self.assertEqual(metric["db_hits_saved"], 0)
                self.assertFalse(metric["lower_db_hits_than_baseline"])
        self.assertEqual(result["cross_work_scaling"]["forward_links"]
                         ["baseline_growth_factor"], 15.204)
        self.assertFalse(result["regression_gate_enforced"])
        self.assertEqual(result["research_release_status"], "HOLD")

    def test_measured_optimization_reports_both_directions(self):
        result = compare_cost_report(report(forward32=175, forward128=560))
        self.assertEqual(result["cost_comparisons"]["128"]["forward_links"]
                         ["db_hits_saved"], 66382 - 560)
        self.assertTrue(result["cost_comparisons"]["128"]["reverse_links"]
                        ["lower_db_hits_than_baseline"])
        self.assertEqual(result["cross_work_scaling"]["forward_links"]
                         ["current_growth_factor"], 3.2)
        self.assertEqual(result["cross_work_scaling"]["reverse_links"]
                         ["current_growth_factor"], 3.2)

    def test_untrusted_profiler_details_cannot_cross_delta_report(self):
        result = compare_cost_report(report(forward32=125, forward128=500))
        encoded = json.dumps(result)
        self.assertNotIn("DO NOT COPY", encoded)
        self.assertNotIn("not permitted", encoded)
        self.assertNotIn("operator_types", encoded)
        self.assertFalse(result["historical_influence_proven"])
        self.assertFalse(result["source_rights_verified"])
        self.assertFalse(result["representative_performance_proven"])

    def test_missing_or_repeated_sizes_fail_closed(self):
        baseline = report()
        variants = [
            {"sizes": []},
            {"sizes": [baseline["sizes"][0]]},
            {"sizes": [baseline["sizes"][0], baseline["sizes"][0]]},
            {"sizes": [dict(baseline["sizes"][0], size=64),
                        baseline["sizes"][1]]},
        ]
        for variant in variants:
            with self.subTest(variant=str(variant)[:80]):
                bad = {**baseline, **variant}
                with self.assertRaises(DeltaError):
                    compare_cost_report(bad)

    def test_malformed_status_or_operation_is_rejected(self):
        variants = [
            ("real_corpus_benchmarked", True),
            ("research_release_status", "PASS"),
            ("representative_performance_proven", True),
            ("case_values_disclosed", True),
        ]
        for key, value in variants:
            bad = report()
            bad[key] = value
            with self.subTest(key=key), self.assertRaises(DeltaError):
                compare_cost_report(bad)
        bad = report()
        bad["sizes"][0]["operation_profiles"][0]["operation"] = "DROP_DATABASE"
        with self.assertRaises(DeltaError):
            compare_cost_report(bad)

    def test_bad_sample_count_nonnumeric_hits_and_duplicate_operations(self):
        for key, value in (
            ("sample_count", 2), ("db_hits_median", True),
            ("db_hits_median", -1), ("db_hits_median", 999_999),
            ("fixed_query_sha256", "not-a-digest"),
        ):
            bad = report()
            bad["sizes"][0]["operation_profiles"][0][key] = value
            with self.subTest(key=key), self.assertRaises(DeltaError):
                compare_cost_report(bad)
        bad = report()
        bad["sizes"][0]["operation_profiles"][0] = deepcopy(
            bad["sizes"][0]["operation_profiles"][1])
        with self.assertRaises(DeltaError):
            compare_cost_report(bad)

    def test_schema_validation_and_no_division_by_zero(self):
        bad = report()
        bad["schema_version"] = "1.0.0"
        with self.assertRaises(DeltaError):
            compare_cost_report(bad)
        improved = compare_cost_report(report(forward32=0, forward128=0))
        self.assertIsNone(
            improved["cross_work_scaling"]["forward_links"]["current_growth_factor"])
        self.assertTrue(improved["cross_work_scaling"]["forward_links"]
                        ["lower_128_hit_count_than_baseline"])

    def test_cli_file_roundtrip_without_text_or_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sanitized-v095.json"
            target = Path(tmp) / "delta-v096.json"
            source.write_text(json.dumps(report()), encoding="utf-8")
            self.assertEqual(main(["--input", str(source), "--output", str(target)]), 0)
            result = json.loads(target.read_text())
            self.assertEqual(result["schema_version"], "0.9.6")
            self.assertEqual(result["research_release_status"], "HOLD")
            symlink = Path(tmp) / "source-symlink.json"
            symlink.symlink_to(source)
            self.assertEqual(main(["--input", str(symlink), "--output", str(target)]), 1)
            source.write_bytes(b"x" * 20_001)
            self.assertEqual(main(["--input", str(source), "--output", str(target)]), 1)

    def test_index_anchored_fixed_read_only_work_link_query(self):
        statement = READ_OPERATIONS["analysis_work_cross_links"]
        self.assertIn("USING INDEX a:Passage(work_id)", statement)
        self.assertIn("MATCH (a)-[r:SOURCE_LINK]->(b:Passage)", statement)
        self.assertIn("WHERE coalesce(b.work_id, '') = $target_work_id", statement)
        self.assertIn("MATCH (ev:Evidence {id:r.evidence_id})", statement)
        self.assertIn("ORDER BY edge_id", statement)
        self.assertIn("LIMIT $fetch_limit", statement)
        for forbidden in ("MERGE ", "DELETE ", "CREATE ", "SET ", "CALL ",
                          "LOAD CSV", "APOC."):
            self.assertNotIn(forbidden, statement.upper())


if __name__ == "__main__":
    unittest.main()
