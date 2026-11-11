#!/usr/bin/env python3
"""v0.9.8 fail-closed fixture-only Work-distractor selectivity gate.

Ceilings calibrated from GitHub Actions #43108294329, three fabricated
four-Work fixtures. NOT real-corpus performance, a production SLO, source
licensing, research quality, or scholarly authority.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from scripts.analytics_distractor_fixture_v098 import (
    CASES, PRIMARY_EDGES, VERSION, distractor_case,
)
from scripts.analytics_distractor_v098 import OPERATIONS, REPEATS

BUDGET = {
    "work_descriptor": 30,
    "forward_links": 1600,
    "reverse_links": 1600,
    "incident_frequency": 30,
}
MAX_NOISE_RATIO = 1.25
MAX_INPUT_BYTES = 65536
ROOT_KEYS = frozenset({
    "schema_version", "fixture_version", "case_order",
    "fixed_selected_source_links", "case_results",
    "interference_vs_control", "research_release_status",
    "real_corpus_benchmarked", "representative_performance_proven",
    "source_values_disclosed", "credentials_disclosed",
    "source_rights_verified", "historical_influence_proven",
    "graph_snapshot_verified", "production_slo_verified",
    "new_cost_gate_enforced",
})
CASE_KEYS = frozenset({
    "case", "fixture_sha256", "selected_source_link_count",
    "distractor_source_link_count", "total_source_link_count",
    "work_count", "author_count", "synthetic_node_count",
    "operations", "real_corpus_benchmarked",
})
METRIC_KEYS = frozenset({
    "operation", "read_template_sha256", "observed_rows_each",
    "samples", "db_hits_min", "db_hits_median", "db_hits_max",
    "http_wall_p50_ms", "http_wall_p95_nearest_rank_ms",
    "max_plan_operators", "label_or_full_scan_observed",
    "potentially_expensive_join_observed", "source_values_disclosed",
    "representative_performance_proven",
})
RATIO_KEYS = frozenset({
    "control_db_hits", "observed_db_hits", "ratio_to_control",
    "added_db_hits",
})


class DistractorGateError(ValueError):
    """Bounded diagnostics only. Never embed input values."""


def _counter(value: object) -> int:
    if type(value) is not int or not 0 <= value <= 250_000:
        raise DistractorGateError("Invalid fixed-fixture cost.")
    return value


def check_distractor_gate(report: object) -> dict:
    if not isinstance(report, dict) or set(report) != ROOT_KEYS:
        raise DistractorGateError("Unexpected distractor report projection.")
    if (report["schema_version"] != "0.9.8" or
            report["fixture_version"] != VERSION or
            report["case_order"] != list(CASES) or
            report["fixed_selected_source_links"] != PRIMARY_EDGES or
            report["research_release_status"] != "HOLD" or
            report["new_cost_gate_enforced"] is not False or
            any(report[key] is not False for key in (
                "real_corpus_benchmarked", "representative_performance_proven",
                "source_values_disclosed", "credentials_disclosed",
                "source_rights_verified", "historical_influence_proven",
                "graph_snapshot_verified", "production_slo_verified",
            ))):
        raise DistractorGateError("Untrusted synthetic benchmark scope.")
    cases = report["case_results"]
    ratios = report["interference_vs_control"]
    if (not isinstance(cases, list) or len(cases) != len(CASES) or
            not isinstance(ratios, dict) or set(ratios) != set(CASES)):
        raise DistractorGateError("Incomplete Work isolation matrix.")
    observed = {}
    for name, item in zip(CASES, cases):
        expected = distractor_case(name)
        if (not isinstance(item, dict) or set(item) != CASE_KEYS or
                item["case"] != name or
                item["fixture_sha256"] != expected["fixture_sha256"] or
                item["selected_source_link_count"] != PRIMARY_EDGES or
                item["distractor_source_link_count"] !=
                expected["distractor_edge_count"] or
                item["total_source_link_count"] != expected["total_link_count"] or
                item["synthetic_node_count"] != expected["synthetic_node_count"] or
                type(item["work_count"]) is not int or item["work_count"] != 4 or
                type(item["author_count"]) is not int or item["author_count"] != 4 or
                item["real_corpus_benchmarked"] is not False):
            raise DistractorGateError("Fixture identity or cardinality invalid.")
        operations = item["operations"]
        if not isinstance(operations, list) or len(operations) != len(OPERATIONS):
            raise DistractorGateError("Missing Work selectivity operations.")
        observed[name] = {}
        for op, metric in zip(OPERATIONS, operations):
            if (not isinstance(metric, dict) or set(metric) != METRIC_KEYS or
                    metric["operation"] != op or
                    metric["samples"] != REPEATS or
                    metric["observed_rows_each"] != (
                        1 if op in ("work_descriptor", "incident_frequency") else 11
                    ) or
                    metric["source_values_disclosed"] is not False or
                    metric["representative_performance_proven"] is not False or
                    metric["label_or_full_scan_observed"] is not False or
                    metric["potentially_expensive_join_observed"] is not False or
                    not isinstance(metric["read_template_sha256"], str) or
                    len(metric["read_template_sha256"]) != 64 or
                    any(character not in "0123456789abcdef"
                        for character in metric["read_template_sha256"])):
                raise DistractorGateError("Untrusted fixed query profile.")
            lo = _counter(metric["db_hits_min"])
            med = _counter(metric["db_hits_median"])
            hi = _counter(metric["db_hits_max"])
            if lo > med or med > hi or hi > BUDGET[op]:
                raise DistractorGateError("Selected Work dbHits budget exceeded.")
            for key in ("http_wall_p50_ms", "http_wall_p95_nearest_rank_ms"):
                t = metric[key]
                if (type(t) not in (float, int) or not
                        math.isfinite(t) or not 0 <= t <= 8000):
                    raise DistractorGateError("Invalid fixture timing.")
            count = metric["max_plan_operators"]
            if type(count) is not int or not 1 <= count <= 100:
                raise DistractorGateError("Invalid query-plan bound.")
            observed[name][op] = med
    baseline = observed["control-0"]
    for name in CASES:
        row = ratios[name]
        if not isinstance(row, dict) or set(row) != set(OPERATIONS):
            raise DistractorGateError("Invalid control comparison mapping.")
        for op in OPERATIONS:
            entry = row[op]
            if not isinstance(entry, dict) or set(entry) != RATIO_KEYS:
                raise DistractorGateError("Unexpected ratio projection.")
            old, now = baseline[op], observed[name][op]
            if old <= 0:
                raise DistractorGateError("Zero-cost baseline is unsupported.")
            expected_ratio = round(now / old, 3)
            if (_counter(entry["control_db_hits"]) != old or
                    _counter(entry["observed_db_hits"]) != now or
                    type(entry["added_db_hits"]) is not int or
                    entry["added_db_hits"] != now - old or
                    type(entry["ratio_to_control"]) not in (float, int) or
                    not math.isfinite(entry["ratio_to_control"]) or
                    entry["ratio_to_control"] != expected_ratio or
                    expected_ratio > MAX_NOISE_RATIO):
                raise DistractorGateError("Unrelated-Work interference regression.")
    return {
        "schema_version": "0.9.8",
        "case_order": list(CASES),
        "synthetic_selectivity_gate_passed": True,
        "fixed_fixture_budget_enforced": True,
        "maximum_interference_ratio": MAX_NOISE_RATIO,
        "per_operation_db_hits_limits": dict(BUDGET),
        "observed_median_db_hits": observed,
        "real_corpus_benchmarked": False,
        "production_slo_verified": False,
        "representative_performance_proven": False,
        "source_rights_verified": False,
        "historical_influence_proven": False,
        "research_release_status": "HOLD",
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)
    try:
        if args.input.is_symlink() or args.output.is_symlink():
            raise DistractorGateError("Symlink artifact paths refused.")
        if not args.input.is_file() or args.input.stat().st_size > MAX_INPUT_BYTES:
            raise DistractorGateError("Invalid fixture report byte bound.")
        report = json.loads(args.input.read_text(encoding="utf-8"))
        summary = check_distractor_gate(report)
        args.output.write_text(json.dumps(
            summary, sort_keys=True, separators=(",", ":"), allow_nan=False
        ) + "\n", encoding="utf-8")
        print("[OK] Synthetic Work-selectivity cost gate passed (HOLD).")
        return 0
    except (DistractorGateError, OSError, ValueError, UnicodeError):
        print("[FAIL] Synthetic Work-selectivity fixture gate failed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
