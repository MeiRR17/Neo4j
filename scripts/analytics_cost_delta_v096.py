#!/usr/bin/env python3
"""v0.9.6 sanitized cost delta versus a pinned v0.9.5 synthetic baseline.

Baseline was measured in GitHub Actions run 43099681819, artifact
13891625668, on 2026-11-11; both fixture sizes and four operations are
identified below. It is not a claim of production workload equivalence.
The comparator processes only allowlisted counters and cannot leak
returned records, source text, query plan Details, credentials, or IDs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

BASELINE_RUN_ID = 43099681819
BASELINE_ARTIFACT_ID = 13891625668
BASELINE_HEAD = "ae10aad62fb7b5fb1be2278b0b52536711a14bee"
BASELINE_DB_HITS = {
    32: {
        "work_descriptor": 12,
        "forward_links": 4366,
        "reverse_links": 4366,
        "incident_frequency": 15,
    },
    128: {
        "work_descriptor": 12,
        "forward_links": 66382,
        "reverse_links": 66382,
        "incident_frequency": 15,
    },
}
EXPECTED_OPS = tuple(BASELINE_DB_HITS[32])
MAX_INPUT_BYTES = 20_000


class DeltaError(ValueError):
    """Only constant diagnostics can cross this error boundary."""


def _hits(value: object) -> int:
    if type(value) is not int or not 0 <= value <= 250_000:
        raise DeltaError("Malformed synthetic dbHits observation.")
    return value


def compare_cost_report(report: object) -> dict:
    if not isinstance(report, dict) or report.get("schema_version") != "0.9.5":
        raise DeltaError("Unexpected benchmark report schema.")
    if (report.get("research_release_status") != "HOLD" or
            report.get("real_corpus_benchmarked") is not False or
            report.get("representative_performance_proven") is not False or
            report.get("case_values_disclosed") is not False):
        raise DeltaError("Untrusted benchmark scope flags.")
    cases = report.get("sizes")
    if not isinstance(cases, list) or len(cases) != 2:
        raise DeltaError("Both declared graph sizes are required.")
    result = {}
    for case in cases:
        if not isinstance(case, dict) or type(case.get("size")) is not int:
            raise DeltaError("Invalid graph fixture size.")
        size = case["size"]
        if size not in BASELINE_DB_HITS or size in result:
            raise DeltaError("Unknown or duplicate fixture size.")
        if (case.get("synthetic_source_link_count") != size or
                case.get("synthetic_work_count") != 2 or
                case.get("synthetic_author_count") != 2 or
                case.get("representative_performance_proven") is not False):
            raise DeltaError("Synthetic fixture contract mismatch.")
        plans = case.get("operation_profiles")
        if not isinstance(plans, list) or len(plans) != len(EXPECTED_OPS):
            raise DeltaError("Missing operation plan records.")
        result[size] = {}
        for p in plans:
            if not isinstance(p, dict):
                raise DeltaError("Malformed operation record.")
            op = p.get("operation")
            if op not in EXPECTED_OPS or op in result[size]:
                raise DeltaError("Unexpected or duplicate analysis operation.")
            if (p.get("source_values_exposed") is not False or
                    p.get("representative_performance_proven") is not False or
                    p.get("sample_count") != 3 or
                    not isinstance(p.get("fixed_query_sha256"), str) or
                    len(p["fixed_query_sha256"]) != 64):
                raise DeltaError("Unsafe or incomplete profiler observation.")
            med = p.get("db_hits_median")
            # Even sample count makes median potentially float; three samples
            # have an integer median, and the pinned runner uses three.
            measured = _hits(med)
            old = BASELINE_DB_HITS[size][op]
            result[size][op] = {
                "baseline_db_hits_median": old,
                "current_db_hits_median": measured,
                "db_hits_saved": old - measured,
                "fractional_reduction": round((old - measured) / old, 4),
                "lower_db_hits_than_baseline": measured < old,
            }
        if set(result[size]) != set(EXPECTED_OPS):
            raise DeltaError("Incomplete benchmark operation set.")

    # 4x fixture scaling: baseline link query 66,382 / 4,366 = 15.204...
    output = {
        "schema_version": "0.9.6",
        "baseline_run_id": BASELINE_RUN_ID,
        "baseline_artifact_id": BASELINE_ARTIFACT_ID,
        "baseline_commit": BASELINE_HEAD,
        "baseline_source": "GitHub Actions synthetic analytics-cost-v095 artifact",
        "comparison_method": "median_db_hits_per_fixed_operation",
        "fixture_scales": [32, 128],
        "cost_comparisons": {str(size): result[size] for size in (32, 128)},
        "cross_work_scaling": {},
        "historical_influence_proven": False,
        "source_rights_verified": False,
        "representative_performance_proven": False,
        "regression_gate_enforced": False,
        "research_release_status": "HOLD",
    }
    for op in ("forward_links", "reverse_links"):
        initial = result[32][op]["current_db_hits_median"]
        later = result[128][op]["current_db_hits_median"]
        output["cross_work_scaling"][op] = {
            "baseline_growth_factor": round(
                BASELINE_DB_HITS[128][op] / BASELINE_DB_HITS[32][op], 3),
            "current_growth_factor": round(later / initial, 3) if initial else None,
            "lower_128_hit_count_than_baseline": (
                later < BASELINE_DB_HITS[128][op]),
        }
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.input.is_symlink() or args.output.is_symlink():
            raise DeltaError("Symlink benchmark artifacts refused.")
        if not args.input.is_file() or args.input.stat().st_size > MAX_INPUT_BYTES:
            raise DeltaError("Benchmark report file exceeds size budget.")
        obj = json.loads(args.input.read_text(encoding="utf-8"))
        delta = compare_cost_report(obj)
        args.output.write_text(
            json.dumps(delta, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8")
        print("[OK] Sanitized 32/128-link cost comparison generated (HOLD).")
        return 0
    except (DeltaError, OSError, UnicodeError, ValueError):
        print("[FAIL] Pinned synthetic cost comparison unavailable.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
