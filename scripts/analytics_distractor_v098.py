#!/usr/bin/env python3
"""v0.9.8 CI-only selectivity probe with unrelated-work distractors.

Every write uses unique synthetic IDs in disposable loopback Neo4j.
Never profile user-supplied Cypher or expose source rows, credentials or
Neo4j plan Details. The baseline is one *synthetic* selected pair of Works,
not real source corpus coverage or proof of consistent database snapshots.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analytics_cost_benchmark import (
    _SEED_EDGES, _SEED_PEOPLE_AND_WORKS, OPERATIONS,
    REPEATS, profile_params,
)
from scripts.analytics_stress_v097 import (
    _count_existing, summarize_stress,
)
from scripts.analytics_distractor_fixture_v098 import (
    CASES, PRIMARY_EDGES, VERSION, distractor_case, fixture_ids,
)
from scripts.analytics_profile_v095 import (
    FixedAnalyticsProfiler, PlanEvidenceError,
)
from scripts.bootstrap import DEFAULT_SECRET_PATH
from scripts.migrate import LocalQueryClient


def _seed_authors(admin, case: dict, first: int) -> None:
    params = {
        "left": case["work_ids"][first],
        "right": case["work_ids"][first + 1],
        "author_left": case["author_ids"][first],
        "author_right": case["author_ids"][first + 1],
        "authored_left": case["authored_edge_ids"][first],
        "authored_right": case["authored_edge_ids"][first + 1],
    }
    rows = admin.query(_SEED_PEOPLE_AND_WORKS, params)
    if rows != [[case["work_ids"][first]]]:
        raise PlanEvidenceError("Synthetic Work seed result mismatch.")


def run_case(admin, profiler, case: dict) -> dict:
    ids = fixture_ids(case)
    if _count_existing(admin, ids) != 0:
        raise PlanEvidenceError("Synthetic distractor IDs already occupied.")
    started = False
    try:
        started = True
        _seed_authors(admin, case, 0)
        _seed_authors(admin, case, 2)
        primary = case["edges"][:PRIMARY_EDGES]
        extras = case["edges"][PRIMARY_EDGES:]
        if admin.query(_SEED_EDGES, {"rows": primary}) != [[PRIMARY_EDGES]]:
            raise PlanEvidenceError("Selected source-link seed mismatch.")
        if extras and admin.query(_SEED_EDGES, {"rows": extras}) != [[len(extras)]]:
            raise PlanEvidenceError("Distractor source-link seed mismatch.")
        # Under the fixed indexed query, unrelated Works must not alter
        # the 11-row selected-work windows or the single incident row.
        metrics = []
        for op in OPERATIONS:
            params = profile_params(case, op)
            observations = [
                profiler.profile(op, params)
                for _ in range(REPEATS)
            ]
            metrics.append(summarize_stress(
                {"incident_rows_expected": 1}, op, observations))
        return {
            "case": case["name"],
            "fixture_sha256": case["fixture_sha256"],
            "selected_source_link_count": case["selected_edge_count"],
            "distractor_source_link_count": case["distractor_edge_count"],
            "total_source_link_count": case["total_link_count"],
            "work_count": 4,
            "author_count": 4,
            "synthetic_node_count": case["synthetic_node_count"],
            "operations": metrics,
            "real_corpus_benchmarked": False,
        }
    finally:
        if started:
            removed = admin.query(
                "MATCH (n) WHERE n.id IN $ids DETACH DELETE n "
                "RETURN count(n) AS removed", {"ids": ids})
            if removed != [[len(ids)]] or _count_existing(admin, ids) != 0:
                raise PlanEvidenceError("Synthetic distractor cleanup failed.")


def _compare_costs(results: list[dict]) -> dict:
    if (not isinstance(results, list) or
            [item.get("case") for item in results] != list(CASES)):
        raise PlanEvidenceError("Fixed distractor result matrix incomplete.")
    baseline = {
        metric["operation"]: metric["db_hits_median"]
        for metric in results[0]["operations"]
    }
    if set(baseline) != set(OPERATIONS):
        raise PlanEvidenceError("Unexpected baseline query operations.")
    comparison = {}
    for result in results:
        costs = {}
        for metric in result["operations"]:
            op = metric["operation"]
            old = baseline[op]
            current = metric["db_hits_median"]
            if (op not in OPERATIONS or type(old) is not int or
                    type(current) is not int or old < 0 or current < 0 or
                    op in costs):
                raise PlanEvidenceError("Malformed synthetic cost comparison.")
            costs[op] = {
                "control_db_hits": old,
                "observed_db_hits": current,
                "ratio_to_control": round(current / old, 3) if old else None,
                "added_db_hits": current - old,
            }
        if set(costs) != set(OPERATIONS):
            raise PlanEvidenceError("Incomplete distractor operation coverage.")
        comparison[result["case"]] = costs
    return comparison


def run_matrix(*, cases: tuple[str, ...] = CASES,
               base_url: str = "http://127.0.0.1:7474",
               secret_path: Path = DEFAULT_SECRET_PATH,
               acknowledged_disposable: bool = False) -> dict:
    if os.getenv("CI") != "true" or acknowledged_disposable is not True:
        raise ValueError("Disposable CI and explicit approval required.")
    if type(cases) is not tuple or cases != CASES:
        raise ValueError("Full fixed distractor matrix required.")
    admin = LocalQueryClient(base_url, secret_path)
    profiler = FixedAnalyticsProfiler(base_url, secret_path)
    results = []
    for name in CASES:
        try:
            results.append(run_case(admin, profiler, distractor_case(name)))
        except (PlanEvidenceError, OSError, RuntimeError, ValueError) as exc:
            # Emit only fixed case ID + exception class, never a DB
            # exception body or unauthorized source data.
            raise PlanEvidenceError(
                "synthetic " + name + " failed: " + type(exc).__name__
            ) from None
    return {
        "schema_version": "0.9.8",
        "fixture_version": VERSION,
        "case_order": list(CASES),
        "fixed_selected_source_links": PRIMARY_EDGES,
        "case_results": results,
        "interference_vs_control": _compare_costs(results),
        "research_release_status": "HOLD",
        "real_corpus_benchmarked": False,
        "representative_performance_proven": False,
        "source_values_disclosed": False,
        "credentials_disclosed": False,
        "source_rights_verified": False,
        "historical_influence_proven": False,
        "graph_snapshot_verified": False,
        "production_slo_verified": False,
        "new_cost_gate_enforced": False,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ack-disposable-fixture", action="store_true")
    p.add_argument("--url", default="http://127.0.0.1:7474")
    p.add_argument("--secret", type=Path, default=DEFAULT_SECRET_PATH)
    args = p.parse_args(argv)
    if os.getenv("CI") != "true" or not args.ack_disposable_fixture:
        print("[BLOCKED] Synthetic distractor matrix needs disposable CI approval.")
        return 2
    try:
        report = run_matrix(
            base_url=args.url, secret_path=args.secret,
            acknowledged_disposable=True,
        )
        print(json.dumps(
            report, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False))
        return 0
    except (PlanEvidenceError, ValueError, OSError, RuntimeError) as exc:
        detail = (
            str(exc) if isinstance(exc, PlanEvidenceError) and
            str(exc).startswith("synthetic ") else type(exc).__name__
        )
        print("[FAIL] Disposable distractor matrix: " + detail,
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
