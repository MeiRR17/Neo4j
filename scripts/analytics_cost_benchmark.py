#!/usr/bin/env python3
"""v0.9.5 reproducible synthetic graph cost fixture on disposable CI Neo4j.

All node creation is synthetic, gated by CI=true and explicit acknowledgment.
Only fixed query templates are PROFILEd. All generated node IDs are enumerated
and checked absent before seeding; cleanup is attempted even on failure.
JSON output contains only synthetic node counts and sanitized metrics, never
query rows, source text, credentials or Neo4j plan Details.
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

from scripts.analytics_fixture_v095 import SIZES, exact_fixture_ids, fixture_case
from scripts.analytics_profile_v095 import FixedAnalyticsProfiler, PlanEvidenceError
from scripts.bootstrap import DEFAULT_SECRET_PATH
from scripts.migrate import LocalQueryClient

REPEATS = 3
OPERATIONS = ("work_descriptor", "forward_links",
              "reverse_links", "incident_frequency")
MAX_SYNTHETIC_GRAPH_NODES = 3 * max(SIZES) + 4

_SEED_PEOPLE_AND_WORKS = """
MERGE (wa:Work {id:$left})
  ON CREATE SET wa.title='SYNTHETIC BENCHMARK LEFT',
    wa.provider='ci-v095', wa.provider_ref='synthetic:benchmark-left'
MERGE (wb:Work {id:$right})
  ON CREATE SET wb.title='SYNTHETIC BENCHMARK RIGHT',
    wb.provider='ci-v095', wb.provider_ref='synthetic:benchmark-right'
MERGE (pa:Person {id:$author_left})
  ON CREATE SET pa.display_name='SYNTHETIC CI A',
    pa.date_from_year=1100, pa.date_to_year=1170
MERGE (pb:Person {id:$author_right})
  ON CREATE SET pb.display_name='SYNTHETIC CI B',
    pb.date_from_year=1200, pb.date_to_year=1270
MERGE (pa)-[:AUTHORED {id:$authored_left}]->(wa)
MERGE (pb)-[:AUTHORED {id:$authored_right}]->(wb)
RETURN wa.id AS sample
""".strip()

_SEED_EDGES = """
UNWIND $rows AS item
MERGE (a:Passage {id:item.source_passage_id})
  ON CREATE SET a.work_id=item.source_work_id,
    a.source_ref=item.source_ref
MERGE (b:Passage {id:item.target_passage_id})
  ON CREATE SET b.work_id=item.target_work_id,
    b.source_ref=item.target_ref
MERGE (e:Evidence {id:item.evidence_id})
  ON CREATE SET e.claim_kind='OBSERVED_SOURCE_LINK',
    e.review_status='unreviewed', e.source_ref=item.source_ref,
    e.version_id='SYNTHETIC-V095', e.rights_tag='NO_RIGHTS_CLAIM'
MERGE (a)-[r:SOURCE_LINK {id:item.edge_id}]->(b)
  ON CREATE SET r.evidence_id=item.evidence_id,
    r.claim_kind='OBSERVED_SOURCE_LINK', r.review_status='unreviewed'
RETURN count(*) AS edges
""".strip()


def profile_params(case: dict, operation: str) -> dict:
    if operation == "work_descriptor":
        return {"work_id": case["left_work_id"]}
    if operation == "forward_links":
        return {"source_work_id": case["left_work_id"],
                "target_work_id": case["right_work_id"], "fetch_limit": 11}
    if operation == "reverse_links":
        return {"source_work_id": case["right_work_id"],
                "target_work_id": case["left_work_id"], "fetch_limit": 11}
    if operation == "incident_frequency":
        return {"passage_id": case["edges"][0]["source_passage_id"],
                "fetch_limit": 51}
    raise ValueError("Unrecognized fixed benchmark case.")


def summarize_profiles(case: dict, operation: str, samples: list[dict]) -> dict:
    if len(samples) != REPEATS:
        raise PlanEvidenceError("Missing benchmark repetitions.")
    keys = ("operation", "read_template_sha256")
    if any(not isinstance(sample, dict) or
           any(sample.get(k) != samples[0].get(k) for k in keys)
           for sample in samples):
        raise PlanEvidenceError("Inconsistent fixed query version.")
    expected_rows = 1 if operation in ("work_descriptor", "incident_frequency") else 11
    if any(sample["returned_rows"] != expected_rows or
           sample["source_values_exposed"] is not False for sample in samples):
        raise PlanEvidenceError("Synthetic fixture query cardinality mismatch.")
    hits = [sample["db_hits"] for sample in samples]
    times = [sample["observed_wall_ms"] for sample in samples]
    if any(type(h) is not int or h < 0 for h in hits):
        raise PlanEvidenceError("Malformed profiler cost.")
    if any(type(t) not in (float, int) or not 0 <= t <= 8000 for t in times):
        raise PlanEvidenceError("Malformed observed wall time.")
    return {
        "operation": operation,
        "fixed_query_sha256": samples[0]["read_template_sha256"],
        "sample_count": len(samples),
        "returned_rows_each": expected_rows,
        "db_hits_min": min(hits),
        "db_hits_max": max(hits),
        "db_hits_median": statistics.median(hits),
        "http_wall_p50_ms": round(statistics.median(times), 3),
        "http_wall_p95_nearest_rank_ms": sorted(times)[math.ceil(.95 * len(times)) - 1],
        "full_or_label_scan_detected": any(s["label_or_full_scan_detected"] for s in samples),
        "observed_max_operator_count": max(s["operator_count"] for s in samples),
        "source_values_exposed": False,
        "representative_performance_proven": False,
    }


def inspect_fixture_absence(admin: LocalQueryClient, case: dict) -> None:
    ids = exact_fixture_ids(case)
    if len(ids) > MAX_SYNTHETIC_GRAPH_NODES:
        raise PlanEvidenceError("Fixture node count exceeds budget.")
    rows = admin.query(
        "MATCH (n) WHERE n.id IN $ids RETURN count(n) AS count", {"ids": ids}
    )
    if rows != [[0]]:
        raise PlanEvidenceError("Synthetic IDs already exist; refusing overwrite.")


def run_fixture(admin: LocalQueryClient, profiler: FixedAnalyticsProfiler,
                case: dict) -> dict:
    ids = exact_fixture_ids(case)
    inspect_fixture_absence(admin, case)
    did_start = False
    try:
        # From this point on, cleanup must run even if seeding fails midway.
        did_start = True
        params = {
            "left": case["left_work_id"], "right": case["right_work_id"],
            "author_left": case["author_ids"][0],
            "author_right": case["author_ids"][1],
            "authored_left": case["authored_edge_ids"][0],
            "authored_right": case["authored_edge_ids"][1],
        }
        admin.query(_SEED_PEOPLE_AND_WORKS, params)
        seeded = admin.query(_SEED_EDGES, {"rows": case["edges"]})
        if seeded != [[case["size"]]]:
            raise PlanEvidenceError("Seeded relationship count mismatch.")
        metrics = []
        for operation in OPERATIONS:
            fixed_params = profile_params(case, operation)
            observations = [
                profiler.profile(operation, fixed_params)
                for _ in range(REPEATS)
            ]
            metrics.append(summarize_profiles(case, operation, observations))
        return {
            "size": case["size"],
            "fixture_sha256": case["fixture_sha256"],
            "synthetic_work_count": 2,
            "synthetic_author_count": 2,
            "synthetic_passage_count": 2 * case["size"],
            "synthetic_evidence_count": case["size"],
            "synthetic_source_link_count": case["size"],
            "operation_profiles": metrics,
            "representative_performance_proven": False,
        }
    finally:
        if did_start:
            # Only explicitly enumerated namespaced synthetic node IDs.
            admin.query(
                "MATCH (n) WHERE n.id IN $ids DETACH DELETE n RETURN count(n) AS removed",
                {"ids": ids},
            )


def run_benchmark(*, sizes: tuple[int, ...] = SIZES,
                  base_url: str = "http://127.0.0.1:7474",
                  secret_path: Path = DEFAULT_SECRET_PATH,
                  acknowledged_disposable: bool = False) -> dict:
    if os.getenv("CI") != "true" or acknowledged_disposable is not True:
        raise ValueError("Explicit CI disposable-fixture authorization is required.")
    if (not sizes or len(sizes) != len(set(sizes)) or
            any(type(size) is not int or size not in SIZES for size in sizes)):
        raise ValueError("Only declared fixture sizes are permitted.")
    admin = LocalQueryClient(base_url, secret_path)
    profiler = FixedAnalyticsProfiler(base_url, secret_path)
    results = [run_fixture(admin, profiler, fixture_case(size)) for size in sizes]
    return {
        "schema_version": "0.9.5",
        "fixture_generator_version": "synthetic-v0.9.5-1",
        "database_isolation": "disposable_ci_only",
        "sizes": results,
        "case_values_disclosed": False,
        "credentials_disclosed": False,
        "producer_digest_digitally_signed": False,
        "graph_snapshot_verified": False,
        "real_corpus_benchmarked": False,
        "representative_performance_proven": False,
        "research_release_status": "HOLD",
        "note": (
            "Only synthetic fixture node counts and sanitized PROFILE plans "
            "were observed. Query limit and latency at small sizes do not "
            "establish scalable execution or production acceptance."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, choices=SIZES, action="append")
    parser.add_argument("--ack-disposable-fixture", action="store_true")
    parser.add_argument("--url", default="http://127.0.0.1:7474")
    parser.add_argument("--secret", type=Path, default=DEFAULT_SECRET_PATH)
    args = parser.parse_args(argv)
    if os.getenv("CI") != "true" or not args.ack_disposable_fixture:
        print("[BLOCKED] Synthetic graph PROFILE requires CI=true and explicit disposable-fixture acknowledgment.")
        return 2
    try:
        size_values = tuple(args.size) if args.size else SIZES
        report = run_benchmark(
            sizes=size_values, base_url=args.url, secret_path=args.secret,
            acknowledged_disposable=True,
        )
        print(json.dumps(report, ensure_ascii=False,
                         sort_keys=True, separators=(",", ":")))
        return 0
    except (PlanEvidenceError, ValueError, OSError, RuntimeError):
        print("[FAIL] Isolated analytics benchmark unavailable or budget exceeded.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
