#!/usr/bin/env python3
"""v0.9.7 CI-only 256/512 SOURCE_LINK disjoint and high-fanout stress suite.

All writes are namespaced synthetic fixtures in disposable CI Neo4j. Profile
ONLY existing fixed read-only query templates. Never return Passage rows,
source text, query-plan Details, credentials or Graph query results.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analytics_cost_benchmark import (
    _SEED_EDGES, _SEED_PEOPLE_AND_WORKS, OPERATIONS, REPEATS,
    profile_params,
)
from scripts.analytics_profile_v095 import FixedAnalyticsProfiler, PlanEvidenceError
from scripts.analytics_stress_fixture_v097 import (
    CASES, VERSION, fixture_ids, stress_case,
)
from scripts.bootstrap import DEFAULT_SECRET_PATH
from scripts.migrate import LocalQueryClient

MAX_STRESS_DB_HITS = 250_000
MAX_RESPONSE_MS = 8_000.0


def _count_existing(admin, ids: list[str]) -> int:
    found = admin.query(
        "MATCH (n) WHERE n.id IN $ids RETURN count(n) AS count", {"ids": ids}
    )
    if (not isinstance(found, list) or len(found) != 1 or
            not isinstance(found[0], list) or len(found[0]) != 1 or
            type(found[0][0]) is not int or found[0][0] < 0):
        raise PlanEvidenceError("Invalid synthetic inventory response.")
    return found[0][0]


def summarize_stress(case: dict, operation: str, samples: list[dict]) -> dict:
    if operation not in OPERATIONS or len(samples) != REPEATS:
        raise PlanEvidenceError("Unexpected fixed stress operation or repetition.")
    expected = (
        case["incident_rows_expected"] if operation == "incident_frequency"
        else 1 if operation == "work_descriptor" else 11
    )
    if not all(
        isinstance(row, dict) and
        row.get("operation") == operation and
        row.get("returned_rows") == expected and
        row.get("source_values_exposed") is False and
        row.get("representative_performance_proven") is False and
        row.get("read_template_sha256") == samples[0].get("read_template_sha256")
        for row in samples
    ):
        raise PlanEvidenceError("Stress PROFILE produced inconsistent sampled rows.")
    costs, times, operator_counts = [], [], []
    any_scans = any_risky_joins = False
    for row in samples:
        hits, elapsed, count = (
            row.get("db_hits"), row.get("observed_wall_ms"),
            row.get("operator_count"),
        )
        if (type(hits) is not int or not 0 <= hits <= MAX_STRESS_DB_HITS or
                type(elapsed) not in (int, float) or
                not 0 <= elapsed <= MAX_RESPONSE_MS or
                type(count) is not int or not 1 <= count <= 100):
            raise PlanEvidenceError("Synthetic stress budget exceeded.")
        operators = row.get("operator_types")
        if not isinstance(operators, list) or not 1 <= len(operators) <= 100:
            raise PlanEvidenceError("Malformed profiler operator list.")
        # Only select boolean flags from already sanitized operator names.
        any_risky_joins |= bool(set(operators) & {
            "CartesianProduct", "NodeHashJoin", "ValueHashJoin",
        })
        any_scans |= row.get("label_or_full_scan_detected") is True
        costs.append(hits)
        times.append(elapsed)
        operator_counts.append(count)
    return {
        "operation": operation,
        "read_template_sha256": samples[0]["read_template_sha256"],
        "observed_rows_each": expected,
        "samples": REPEATS,
        "db_hits_min": min(costs),
        "db_hits_median": statistics.median(costs),
        "db_hits_max": max(costs),
        "http_wall_p50_ms": round(statistics.median(times), 3),
        "http_wall_p95_nearest_rank_ms": sorted(times)[math.ceil(.95 * REPEATS) - 1],
        "max_plan_operators": max(operator_counts),
        "label_or_full_scan_observed": any_scans,
        "potentially_expensive_join_observed": any_risky_joins,
        "source_values_disclosed": False,
        "representative_performance_proven": False,
    }


def run_case(admin: LocalQueryClient, profiler: FixedAnalyticsProfiler,
             case: dict) -> dict:
    ids = fixture_ids(case)
    if _count_existing(admin, ids) != 0:
        raise PlanEvidenceError("Synthetic fixture identities already occupied.")
    started = False
    try:
        started = True
        author_params = {
            "left": case["left_work_id"], "right": case["right_work_id"],
            "author_left": case["author_ids"][0],
            "author_right": case["author_ids"][1],
            "authored_left": case["authored_edge_ids"][0],
            "authored_right": case["authored_edge_ids"][1],
        }
        admin.query(_SEED_PEOPLE_AND_WORKS, author_params)
        seeded = admin.query(_SEED_EDGES, {"rows": case["edges"]})
        if seeded != [[case["size"]]]:
            raise PlanEvidenceError("Synthetic stress seed cardinality mismatch.")
        metrics = []
        for op in OPERATIONS:
            params = profile_params(case, op)
            samples = [profiler.profile(op, params) for _ in range(REPEATS)]
            metrics.append(summarize_stress(case, op, samples))
        return {
            "case": case["name"],
            "topology": case["topology"],
            "source_link_count": case["size"],
            "synthetic_passage_count": case["synthetic_passage_count"],
            "synthetic_evidence_count": case["size"],
            "synthetic_work_count": 2,
            "synthetic_author_count": 2,
            "max_source_out_degree": case["max_source_out_degree"],
            "fixture_sha256": case["fixture_sha256"],
            "operations": metrics,
            "real_corpus_benchmarked": False,
        }
    finally:
        if started:
            deleted = admin.query(
                "MATCH (n) WHERE n.id IN $ids DETACH DELETE n RETURN count(n) AS removed",
                {"ids": ids},
            )
            if deleted != [[len(ids)]] or _count_existing(admin, ids) != 0:
                raise PlanEvidenceError("Synthetic fixture cleanup incomplete.")


def _compare_growth(cases: list[dict]) -> dict:
    lookups = {case["case"]: case for case in cases}
    result = {}
    for topology in ("disjoint", "hub"):
        low = lookups[f"{topology}-256"]
        high = lookups[f"{topology}-512"]
        ratios = {}
        for op in OPERATIONS:
            small = next(x for x in low["operations"] if x["operation"] == op)
            large = next(x for x in high["operations"] if x["operation"] == op)
            a, b = small["db_hits_median"], large["db_hits_median"]
            if (type(a) is not int or type(b) is not int or
                    a < 0 or b < 0):
                raise PlanEvidenceError("Unexpected stress cost.")
            ratios[op] = {
                "db_hits_at_256": a,
                "db_hits_at_512": b,
                "observed_growth_factor": round(b / a, 3) if a else None,
            }
        result[topology] = ratios
    return result


def run_stress(*, cases: tuple[str, ...] = CASES,
               base_url: str = "http://127.0.0.1:7474",
               secret_path: Path = DEFAULT_SECRET_PATH,
               acknowledged_disposable: bool = False) -> dict:
    if os.getenv("CI") != "true" or acknowledged_disposable is not True:
        raise ValueError("Explicit disposable CI authorization required.")
    if tuple(cases) != CASES:
        raise ValueError("Full v0.9.7 fixture matrix required.")
    admin = LocalQueryClient(base_url, secret_path)
    profiler = FixedAnalyticsProfiler(base_url, secret_path)
    results = [run_case(admin, profiler, stress_case(name)) for name in CASES]
    return {
        "schema_version": "0.9.7",
        "fixture_version": VERSION,
        "case_order": list(CASES),
        "case_results": results,
        "growth_by_topology": _compare_growth(results),
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ack-disposable-fixture", action="store_true")
    parser.add_argument("--url", default="http://127.0.0.1:7474")
    parser.add_argument("--secret", type=Path, default=DEFAULT_SECRET_PATH)
    args = parser.parse_args(argv)
    if os.getenv("CI") != "true" or not args.ack_disposable_fixture:
        print("[BLOCKED] Full v0.9.7 CI matrix requires explicit disposal approval.")
        return 2
    try:
        result = run_stress(
            base_url=args.url, secret_path=args.secret,
            acknowledged_disposable=True,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False))
        return 0
    except (PlanEvidenceError, ValueError, OSError, RuntimeError):
        print("[FAIL] Disposable stress matrix invalid, unsafe or incomplete.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
