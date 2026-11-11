"""v0.9.5 reproducible analytics fixture and sanitized profiler contracts."""
from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import json
import os
from unittest import TestCase
from unittest.mock import patch

from research_graph.ontology import CANONICAL_ID_PATTERN
from scripts.analytics_fixture_v095 import SIZES, exact_fixture_ids, fixture_case
from scripts.analytics_profile_v095 import (
    FixedAnalyticsProfiler, MAX_DB_HITS, PlanEvidenceError,
    parse_profile, statement_hash,
)
from scripts.analytics_cost_benchmark import (
    REPEATS, OPERATIONS, inspect_fixture_absence, main, profile_params,
    run_benchmark, run_fixture, summarize_profiles,
)
from services.research_api.queries import READ_OPERATIONS


def synthetic_body(rows=1, *, hits=13):
    return {
        "queryType": "r",
        "data": {
            "fields": ["private_source_title"],
            "values": [["DO NOT LEAK SOURCE"] for _ in range(rows)],
        },
        "profiledQueryPlan": {
            "operatorType": "ProduceResults@neo4j",
            "arguments": {"Details": "DO NOT LEAK SOURCE"},
            "dbHits": 3,
            "children": [{
                "operatorType": "NodeByLabelScan",
                "arguments": {"Details": "DO NOT LEAK SOURCE"},
                "dbHits": hits,
                "children": [],
            }],
        },
    }


class FakeHTTPResponse:
    status = 202

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, length):
        return self.payload[:length]


class FakeOpener:
    def __init__(self, body=None):
        self.body = synthetic_body() if body is None else body
        self.last_request = None
        self.timeout = None

    def open(self, req, timeout):
        self.last_request = req
        self.timeout = timeout
        return FakeHTTPResponse(json.dumps(self.body).encode("utf-8"))


class FakeAdmin:
    def __init__(self, *, occupied=False, fail_seed=False):
        self.calls = []
        self.occupied = occupied
        self.fail_seed = fail_seed

    def query(self, statement, params):
        self.calls.append((statement, params))
        if "MATCH (n) WHERE n.id IN $ids RETURN count(n)" in statement:
            return [[1 if self.occupied else 0]]
        if "UNWIND $rows AS item" in statement:
            if self.fail_seed:
                raise RuntimeError("Synthetic injected seed failure")
            return [[len(params["rows"])]]
        if "DETACH DELETE" in statement:
            return [[len(params["ids"])]]
        return [["synthetic-work"]]


class FakeProfiler:
    def __init__(self):
        self.calls = []

    def profile(self, operation, params):
        self.calls.append((operation, params))
        return {
            "operation": operation,
            "read_template_sha256": statement_hash(operation),
            "returned_rows": (
                1 if operation in ("work_descriptor", "incident_frequency") else 11
            ),
            "db_hits": 14,
            "observed_wall_ms": 1.25,
            "operator_count": 2,
            "label_or_full_scan_detected": True,
            "source_values_exposed": False,
        }


class AnalyticsBenchmarkTests(TestCase):
    def test_declared_fixture_sizes_and_exact_counts(self):
        for size in SIZES:
            with self.subTest(size=size):
                case = fixture_case(size)
                self.assertEqual(len(case["edges"]), size)
                self.assertEqual(len(exact_fixture_ids(case)), 3 * size + 4)
                self.assertEqual(case["edges"][0]["source_work_id"],
                                 case["left_work_id"])
                self.assertEqual(case["edges"][1]["source_work_id"],
                                 case["right_work_id"])
                self.assertTrue(all(
                    CANONICAL_ID_PATTERN.fullmatch(identity)
                    for identity in exact_fixture_ids(case)
                ))
                self.assertEqual(case["fixture_sha256"],
                                 fixture_case(size)["fixture_sha256"])
                self.assertEqual(case, fixture_case(size))

    def test_reject_non_allowlisted_sizes_even_for_synthetic_fixtures(self):
        for size in (0, 1, 31, 129, 9999, True, "32", -1):
            with self.subTest(size=size):
                with self.assertRaises(ValueError):
                    fixture_case(size)

    def test_profile_response_discards_sensitive_rows_and_details(self):
        report = parse_profile(synthetic_body(), "work_descriptor")
        self.assertEqual(report["db_hits"], 16)
        self.assertEqual(report["returned_rows"], 1)
        self.assertEqual(report["operator_count"], 2)
        self.assertTrue(report["label_or_full_scan_detected"])
        self.assertFalse(report["source_values_exposed"])
        self.assertNotIn("DO NOT LEAK", json.dumps(report))
        self.assertEqual(len(report["read_template_sha256"]), 64)

    def test_deny_mutated_profile_and_cost_overflow(self):
        edits = [
            lambda x: x.update(queryType="w"),
            lambda x: x.update(errors=[{"code": "BAD"}]),
            lambda x: x.update(queryPlan={}),
            lambda x: x.pop("profiledQueryPlan"),
            lambda x: x["profiledQueryPlan"].update(dbHits=MAX_DB_HITS + 1),
            lambda x: x["profiledQueryPlan"]["children"][0].update(
                operatorType="x" * 101),
            lambda x: x["data"].update(values=[["x"]] * 52),
            lambda x: x["data"].update(values=[[]]),
        ]
        for modify in edits:
            with self.subTest(modify=str(modify)):
                body = synthetic_body()
                modify(body)
                with self.assertRaises(PlanEvidenceError):
                    parse_profile(body, "forward_links")
        with self.assertRaises(PlanEvidenceError):
            parse_profile(synthetic_body(), "arbitrary_query")

    def test_http_profile_uses_read_only_fixed_cypher_and_bounds(self):
        case = fixture_case(32)
        cli = object.__new__(FixedAnalyticsProfiler)
        cli.endpoint = "http://127.0.0.1:7474/db/neo4j/query/v2"
        cli.headers = {"Authorization": "Basic SYNTHETIC_ONLY"}
        cli.opener = FakeOpener()
        params = profile_params(case, "work_descriptor")
        result = cli.profile("work_descriptor", params)
        body = json.loads(cli.opener.last_request.data.decode("utf-8"))
        self.assertEqual(
            body["statement"],
            "PROFILE " + READ_OPERATIONS["analysis_work_descriptor"],
        )
        self.assertEqual(body["accessMode"], "Read")
        self.assertEqual(body["maxExecutionTime"], 5)
        self.assertEqual(body["parameters"], params)
        self.assertEqual(cli.opener.timeout, 8)
        self.assertEqual(result["returned_rows"], 1)
        self.assertNotIn("DO NOT LEAK", json.dumps(result))

    def test_http_rejects_param_injection_before_network(self):
        cli = object.__new__(FixedAnalyticsProfiler)
        cli.endpoint = "http://127.0.0.1:7474/db/neo4j/query/v2"
        cli.headers = {"Authorization": "Basic SYNTHETIC_ONLY"}
        cli.opener = FakeOpener()
        case = fixture_case(32)
        invalid = [
            ("drop_database", {}),
            ("work_descriptor", {"work_id": "admin"}),
            ("work_descriptor", {"work_id": case["edges"][0]["source_passage_id"]}),
            ("work_descriptor", {"work_id": case["left_work_id"], "cypher": "DELETE n"}),
            ("forward_links", {"source_work_id": case["left_work_id"]}),
            ("incident_frequency", {"passage_id": case["left_work_id"], "fetch_limit": 51}),
            ("forward_links", {"source_work_id": case["left_work_id"],
                                "target_work_id": case["right_work_id"],
                                "fetch_limit": 10000}),
        ]
        for operation, params in invalid:
            with self.subTest(operation=operation, params=params):
                with self.assertRaises(PlanEvidenceError):
                    cli.profile(operation, params)
                self.assertIsNone(cli.opener.last_request)

    def test_summarized_profile_is_explicitly_non_representative(self):
        case = fixture_case(128)
        profiler = FakeProfiler()
        reports = [profiler.profile("forward_links", profile_params(case, "forward_links"))
                   for _ in range(REPEATS)]
        result = summarize_profiles(case, "forward_links", reports)
        self.assertEqual(result["sample_count"], 3)
        self.assertEqual(result["returned_rows_each"], 11)
        self.assertEqual(result["db_hits_median"], 14)
        self.assertEqual(result["http_wall_p95_nearest_rank_ms"], 1.25)
        self.assertFalse(result["representative_performance_proven"])
        self.assertNotIn("source_ref", result)

    def test_fixture_refuses_existing_ids_before_any_write(self):
        admin = FakeAdmin(occupied=True)
        case = fixture_case(32)
        with self.assertRaises(PlanEvidenceError):
            inspect_fixture_absence(admin, case)
        self.assertEqual(len(admin.calls), 1)
        self.assertNotIn("MERGE ", admin.calls[0][0])

    def test_success_and_failure_cleanup_of_explicit_node_ids(self):
        case = fixture_case(32)
        admin = FakeAdmin()
        p = FakeProfiler()
        result = run_fixture(admin, p, case)
        self.assertEqual(result["synthetic_source_link_count"], 32)
        self.assertEqual(len(result["operation_profiles"]), 4)
        self.assertEqual(len(p.calls), 4 * REPEATS)
        self.assertIn("DETACH DELETE", admin.calls[-1][0])
        self.assertEqual(admin.calls[-1][1]["ids"], exact_fixture_ids(case))
        fail = FakeAdmin(fail_seed=True)
        with self.assertRaises(RuntimeError):
            run_fixture(fail, FakeProfiler(), case)
        self.assertIn("DETACH DELETE", fail.calls[-1][0])

    def test_runner_requires_two_explicit_ci_guards(self):
        with patch.dict(os.environ, {"CI": "false"}):
            self.assertEqual(main(["--ack-disposable-fixture"]), 2)
        with patch.dict(os.environ, {"CI": "true"}):
            self.assertEqual(main([]), 2)

    def test_constrained_report_does_not_certify_production(self):
        with patch("scripts.analytics_cost_benchmark.LocalQueryClient", FakeAdmin), \
             patch("scripts.analytics_cost_benchmark.FixedAnalyticsProfiler",
                   FakeProfiler):
            data = run_benchmark(sizes=(32, 128))
        self.assertEqual(data["schema_version"], "0.9.5")
        self.assertEqual([x["size"] for x in data["sizes"]], [32, 128])
        self.assertEqual(data["research_release_status"], "HOLD")
        self.assertFalse(data["graph_snapshot_verified"])
        self.assertFalse(data["real_corpus_benchmarked"])
        self.assertFalse(data["representative_performance_proven"])
        self.assertFalse(data["producer_digest_digitally_signed"])


if __name__ == "__main__":
    import unittest
    unittest.main()
