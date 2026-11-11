#!/usr/bin/env python3
"""v0.9.7 fail-closed CI *synthetic fixture* regression gate.

Calibrated from GitHub Actions run 43105105335 (artifact 13894175625).
These fixed sample budgets do NOT define production SLOs, corpus completeness
or proof of scholarly rights, authenticity or historical influence.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from scripts.analytics_stress_fixture_v097 import CASES, VERSION, stress_case
from scripts.analytics_stress_v097 import OPERATIONS, REPEATS

MAX_INPUT_BYTES = 32_768
MAX_GROWTH = 2.8
BUDGET = {
    "disjoint-256": {
        "work_descriptor": 30, "forward_links": 3000,
        "reverse_links": 3000, "incident_frequency": 40,
    },
    "hub-256": {
        "work_descriptor": 30, "forward_links": 2700,
        "reverse_links": 3000, "incident_frequency": 2000,
    },
    "disjoint-512": {
        "work_descriptor": 30, "forward_links": 6000,
        "reverse_links": 6000, "incident_frequency": 40,
    },
    "hub-512": {
        "work_descriptor": 30, "forward_links": 5300,
        "reverse_links": 6000, "incident_frequency": 3800,
    },
}
CASE_KEYS = frozenset({
    "case", "topology", "source_link_count", "synthetic_passage_count",
    "synthetic_evidence_count", "synthetic_work_count", "synthetic_author_count",
    "max_source_out_degree", "fixture_sha256", "operations",
    "real_corpus_benchmarked",
})
PROFILE_KEYS = frozenset({
    "operation", "read_template_sha256", "observed_rows_each", "samples",
    "db_hits_min", "db_hits_median", "db_hits_max", "http_wall_p50_ms",
    "http_wall_p95_nearest_rank_ms", "max_plan_operators",
    "label_or_full_scan_observed", "potentially_expensive_join_observed",
    "source_values_disclosed", "representative_performance_proven",
})


class StressGateError(ValueError):
    """Safe fixed diagnostics; no query data in exception messages."""


def _cost(value: object, message: str) -> int:
    if type(value) is not int or not 0 <= value <= 250_000:
        raise StressGateError(message)
    return value


def check_synthetic_stress(report: object) -> dict:
    if not isinstance(report, dict):
        raise StressGateError("Missing synthetic benchmark record.")
    if (report.get("schema_version") != "0.9.7" or
            report.get("fixture_version") != VERSION or
            report.get("case_order") != list(CASES) or
            report.get("research_release_status") != "HOLD" or
            report.get("real_corpus_benchmarked") is not False or
            report.get("representative_performance_proven") is not False or
            report.get("source_values_disclosed") is not False or
            report.get("credentials_disclosed") is not False or
            report.get("query_regression_gate_enforced") is not False or
            report.get("source_rights_verified") is not False or
            report.get("historical_influence_proven") is not False or
            report.get("observed_costs_only") is not True):
        raise StressGateError("Untrusted synthetic benchmark scope.")
    results = report.get("case_results")
    if not isinstance(results, list) or len(results) != len(CASES):
        raise StressGateError("Synthetic case matrix incomplete.")
    summaries = {}
    for expected_name, case in zip(CASES, results):
        expected = stress_case(expected_name)
        if (not isinstance(case, dict) or set(case) != CASE_KEYS or
                case.get("case") != expected_name or
                case.get("topology") != expected["topology"] or
                case.get("source_link_count") != expected["size"] or
                case.get("synthetic_passage_count") !=
                expected["synthetic_passage_count"] or
                case.get("synthetic_evidence_count") != expected["size"] or
                case.get("synthetic_work_count") != 2 or
                case.get("synthetic_author_count") != 2 or
                case.get("max_source_out_degree") !=
                expected["max_source_out_degree"] or
                case.get("fixture_sha256") != expected["fixture_sha256"] or
                case.get("real_corpus_benchmarked") is not False):
            raise StressGateError("Fixture hash or cardinality changed.")
        profiles = case["operations"]
        if not isinstance(profiles, list) or len(profiles) != len(OPERATIONS):
            raise StressGateError("Fixed query profile matrix incomplete.")
        summaries[expected_name] = {}
        for operation, profile in zip(OPERATIONS, profiles):
            expected_rows = (
                expected["incident_rows_expected"]
                if operation == "incident_frequency"
                else 1 if operation == "work_descriptor" else 11
            )
            if (not isinstance(profile, dict) or
                    set(profile) != PROFILE_KEYS or
                    profile.get("operation") != operation or
                    profile.get("samples") != REPEATS or
                    profile.get("observed_rows_each") != expected_rows or
                    profile.get("source_values_disclosed") is not False or
                    profile.get("representative_performance_proven") is not False or
                    profile.get("potentially_expensive_join_observed") is not False or
                    profile.get("label_or_full_scan_observed") is not False or
                    not isinstance(profile.get("read_template_sha256"), str) or
                    re.fullmatch(r"[0-9a-f]{64}", profile["read_template_sha256"]) is None):
                raise StressGateError("Unsafe PROFILE operator or result shape.")
            minimum = _cost(profile.get("db_hits_min"), "Invalid minimum dbHits.")
            median = _cost(profile.get("db_hits_median"), "Invalid median dbHits.")
            maximum = _cost(profile.get("db_hits_max"), "Invalid maximum dbHits.")
            if (not minimum <= median <= maximum or
                    maximum > BUDGET[expected_name][operation]):
                raise StressGateError("Synthetic query cost regression detected.")
            summaries[expected_name][operation] = median
    growth = {}
    for topology in ("disjoint", "hub"):
        growth[topology] = {}
        for operation in OPERATIONS:
            smaller = summaries[f"{topology}-256"][operation]
            larger = summaries[f"{topology}-512"][operation]
            if smaller <= 0 or larger / smaller > MAX_GROWTH:
                raise StressGateError("Synthetic topology-scaling regression detected.")
            growth[topology][operation] = round(larger / smaller, 3)
    # Only validated allowlisted counters are exported; the original report,
    # its plan metadata and source/graph identities are never passed through.
    return {
        "schema_version": "0.9.7",
        "case_order": list(CASES),
        "observed_median_db_hits": summaries,
        "observed_256_to_512_growth": growth,
        "fixed_fixture_budget_enforced": True,
        "synthetic_stress_gate_passed": True,
        "representative_performance_proven": False,
        "source_rights_verified": False,
        "historical_influence_proven": False,
        "research_release_status": "HOLD",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.input.is_symlink() or args.output.is_symlink():
            raise StressGateError("Symlink artifact refused.")
        if (not args.input.is_file() or args.input.stat().st_size >
                MAX_INPUT_BYTES):
            raise StressGateError("Benchmark report exceeds input budget.")
        source = json.loads(args.input.read_text(encoding="utf-8"))
        checked = check_synthetic_stress(source)
        args.output.write_text(
            json.dumps(checked, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        print("[OK] 256/512 disjoint and hub synthetic cost guard passed (HOLD).")
        return 0
    except (StressGateError, OSError, UnicodeError, ValueError):
        print("[FAIL] Fixed synthetic stress cost guard failed closed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
