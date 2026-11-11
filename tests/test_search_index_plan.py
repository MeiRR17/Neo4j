"""v0.8.6 execution-plan verification without source text or real DB."""
from __future__ import annotations

import json
import os
from unittest import TestCase
from unittest.mock import patch
from urllib import request

from scripts.search_index_plan import (
    FETCH_LIMIT, LocalPlanClient, PlanEvidenceError, inspect_plan_response,
    main, statement_for, validate_prefix,
)


def tree(operator: str = "NodeIndexSeekByRange@neo4j", details: str = "n.search_key_v1 STARTS WITH $prefix"):
    return {
        "operatorType": "ProduceResults@neo4j",
        "arguments": {"Details": "n.id"},
        "children": [{
            "operatorType": operator,
            "arguments": {"Details": details, "DbHits": 4},
            "dbHits": 4,
            "children": [],
        }],
    }


def reply(*, profile: bool = False, operator: str = "NodeIndexSeekByRange@neo4j") -> dict:
    return {
        "data": {"fields": ["id"], "values": [["synthetic"]] if profile else []},
        "queryType": "r",
        ("profiledQueryPlan" if profile else "queryPlan"): tree(operator=operator),
    }


class DummyResponse:
    status = 202

    def __init__(self, body: dict):
        self.body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, count: int):
        return self.body[:count]


class DummyOpener:
    def __init__(self, body: dict):
        self.body = body
        self.last_request = None
        self.timeout = None

    def open(self, req: request.Request, timeout: int):
        self.last_request = req
        self.timeout = timeout
        return DummyResponse(self.body)


class SearchPlanTests(TestCase):
    def test_fixed_queries_only_no_user_statement_or_write(self):
        for kind in ("works", "persons", "passages", "concepts"):
            statement = statement_for(kind, False)
            self.assertTrue(statement.startswith("EXPLAIN "))
            self.assertIn("STARTS WITH $prefix", statement)
            self.assertIn("ORDER BY id", statement)
            self.assertNotIn(" SET ", statement.upper())
            self.assertNotIn(" DELETE ", statement.upper())
            self.assertTrue(statement_for(kind, True).startswith("PROFILE "))
        with self.assertRaises(PlanEvidenceError):
            statement_for("works MATCH (n) DELETE n", False)

    def test_prefix_unicode_bounded_and_never_embedded_in_statement(self):
        self.assertEqual(validate_prefix("מוֹרֶה"), "מורה")
        for raw in ("", "   ", "\n", "\x00", "x" * 101):
            with self.subTest(raw=raw), self.assertRaises(PlanEvidenceError):
                validate_prefix(raw)
        self.assertNotIn("synthetic", statement_for("works", False))

    def test_explain_uses_range_seek_only_when_property_matches(self):
        plan = inspect_plan_response(reply(), kind="works", profile=False)
        self.assertTrue(plan["search_key_range_seek_planned"])
        self.assertFalse(plan["execution_metrics_available"])
        self.assertFalse(plan["results_exposed"])
        self.assertFalse(plan["representative_performance_proven"])
        self.assertNotIn("synthetic", json.dumps(plan))
        other = inspect_plan_response(
            reply(operator="NodeByLabelScan@neo4j"), kind="works", profile=False)
        self.assertFalse(other["search_key_range_seek_planned"])
        self.assertTrue(other["node_or_label_scan_planned"])
        # Punctuation in real Neo4j plan names must never break CI, nor leak.
        unusual = reply(operator="Unexpected (Fusion)+@neo4j")
        parsed = inspect_plan_response(unusual, kind="works", profile=False)
        self.assertIn("OtherOperator", parsed["operator_types"])
        self.assertNotIn("Unexpected (Fusion)", json.dumps(parsed))
        wrong = reply()
        wrong["queryPlan"]["children"][0]["arguments"]["Details"] = "n.id"
        self.assertFalse(inspect_plan_response(
            wrong, kind="works", profile=False)["search_key_range_seek_planned"])

    def test_profile_records_bounded_counters_but_never_source_values(self):
        item = reply(profile=True)
        item["resultAvailableAfter"] = 8
        item["resultConsumedAfter"] = 4
        metrics = inspect_plan_response(item, kind="works", profile=True)
        self.assertEqual(metrics["returned_rows"], 1)
        self.assertEqual(metrics["db_hits"], 4)
        self.assertEqual(metrics["result_available_after_ms"], 8)
        self.assertNotIn("synthetic", json.dumps(metrics))

    def test_invalid_plan_shapes_and_non_read_queries_rejected(self):
        changes = [
            {"errors": [{"code": "PrivateFault"}]},
            {"queryType": "rw"},
            {"queryPlan": []},
            {"data": {"fields": [], "values": [[1]]}},
            {"queryPlan": {**tree(), "children": "not-a-list"}},
            {"queryPlan": {**tree(), "operatorType": 42}},
        ]
        for change in changes:
            with self.subTest(change=change):
                body = reply()
                body.update(change)
                with self.assertRaises(PlanEvidenceError):
                    inspect_plan_response(body, kind="works", profile=False)
        with self.assertRaises(PlanEvidenceError):
            inspect_plan_response(reply(profile=True), kind="works", profile=False)
        with self.assertRaises(PlanEvidenceError):
            inspect_plan_response(reply(profile=False), kind="works", profile=True)
        invalid_profile = reply(profile=True)
        invalid_profile["profiledQueryPlan"]["children"][0]["dbHits"] = -1
        with self.assertRaises(PlanEvidenceError):
            inspect_plan_response(invalid_profile, kind="works", profile=True)

    def test_wire_request_is_fixed_and_read_mode(self):
        cli = object.__new__(LocalPlanClient)
        cli.endpoint = "http://127.0.0.1:7474/db/neo4j/query/v2"
        cli.headers = {"Authorization": "Basic synthetic-fixture-only"}
        cli.opener = DummyOpener(reply())
        result = cli.query_plan("works", "synthetic", profile=False)
        wire = json.loads(cli.opener.last_request.data)
        self.assertTrue(wire["statement"].startswith("EXPLAIN "))
        self.assertEqual(wire["parameters"]["prefix"], "synthetic")
        self.assertEqual(wire["parameters"]["fetch_limit"], FETCH_LIMIT)
        self.assertEqual(wire["accessMode"], "Read")
        self.assertEqual(wire["maxExecutionTime"], 5)
        self.assertEqual(cli.opener.timeout, 8)
        self.assertTrue(result["search_key_range_seek_planned"])

    def test_profile_fails_before_connecting_without_explicit_ci_approval(self):
        with patch.dict(os.environ, {"CI": "false"}):
            self.assertEqual(main(["--profile", "--ack-disposable-fixture"]), 2)
        with patch.dict(os.environ, {"CI": "true"}):
            self.assertEqual(main(["--profile"]), 2)
