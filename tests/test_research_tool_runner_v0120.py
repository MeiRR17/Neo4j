"""v0.12.0 registered read-only tool plan/replay and API safety checks."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from research_graph.ontology import stable_id
from services.research_api.app import create_app
from services.research_api.config import bootstrap_token, load_token
from services.research_api.db import DatabaseUnavailable
from services.research_api.research_tool_runner_v0120 import (
    read_only_tool_catalog, plan_read_only_research_tool,
    run_read_only_research_tool,
)
from tests.test_analytics import Stub, FOCUS, TARGET, EVIDENCE


class ReadOnlyResearchToolRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        key = Path(self.tmp.name) / "token"
        bootstrap_token(key)
        self.auth = {"Authorization": "Bearer " + load_token(key)}
        self.store = Stub()
        self.client = TestClient(create_app(backend=self.store, token_path=key))
        gates = patch.dict(os.environ, {
            "DVIROS_ENABLE_GROUNDED_CONTEXT": "1",
            "DVIROS_ENABLE_RESEARCH_TOOL_RUNNER": "1",
        })
        gates.start()
        self.addCleanup(gates.stop)

    def parameters(self, operation="compare_contexts", **overrides):
        values = {
            "operation": operation,
            "passage_ids": ",".join(sorted((FOCUS, TARGET))),
            "query": "Synthetic Multiword",
            "limit": 8,
            "read_budget": 3,
        }
        if operation == "source_context":
            values["passage_ids"] = FOCUS
        if operation == "review_dossier":
            values["evidence_ids"] = EVIDENCE
        values.update(overrides)
        return values

    def plan(self, operation="compare_contexts", **overrides):
        return self.client.get(
            "/v1/research/agent-tools/plan",
            params=self.parameters(operation, **overrides),
            headers=self.auth,
        )

    def execute_operation(self, operation="compare_contexts", **overrides):
        args = self.parameters(operation, **overrides)
        planned = self.client.get(
            "/v1/research/agent-tools/plan",
            params=args, headers=self.auth,
        )
        self.assertEqual(planned.status_code, 200, planned.text)
        args["request_checkpoint_sha256"] = planned.json()[
            "request_checkpoint_sha256"
        ]
        response = self.client.get(
            "/v1/research/agent-tools/execute", params=args,
            headers=self.auth,
        )
        return response, planned.json()

    def test_exact_registry_and_planning_make_no_graph_calls(self):
        r = self.client.get(
            "/v1/research/agent-tools/catalog", headers=self.auth,
        )
        self.assertEqual(r.status_code, 200, r.text)
        catalog = r.json()
        self.assertEqual([x["operation"] for x in catalog["registry"]], [
            "source_context", "compare_contexts", "review_dossier",
        ])
        self.assertTrue(all(x["read_only"] for x in catalog["registry"]))
        self.assertTrue(all(not x["writes_allowed"] for x in catalog["registry"]))
        plan = self.plan()
        self.assertEqual(plan.status_code, 200, plan.text)
        data = plan.json()
        self.assertEqual(data["parameters"]["scheduled_graph_reads"], 2)
        self.assertEqual(data["parameters"]["total_links_observation_bound"], 40)
        self.assertEqual(data["parameters"]["candidate_limit"], 8)
        self.assertEqual(len(data["request_checkpoint_sha256"]), 64)
        self.assertFalse(data["checkpoint_authenticates_reviewer"])
        self.assertFalse(data["checkpoint_persists_execution_state"])
        self.assertEqual(data["graph_reads_executed"], 0)
        self.assertEqual(self.store.calls, [])

    def test_readonly_compare_and_review_cards(self):
        response, plan = self.execute_operation()
        self.assertEqual(response.status_code, 200, response.text)
        value = response.json()
        self.assertEqual(value["tool_operation"], "compare_contexts")
        self.assertEqual(
            value["request_checkpoint_sha256"],
            plan["request_checkpoint_sha256"],
        )
        self.assertEqual(value["execution_status"], "COMPLETED_REVIEW_PREVIEW")
        self.assertEqual(value["scheduled_graph_reads"], 2)
        self.assertEqual(value["returned_card_count"], 1)
        card = value["evidence_cards"][0]
        self.assertEqual(card["evidence_id"], EVIDENCE)
        self.assertEqual(card["source_ref"], "Synthetic Multiword Work 1:1")
        self.assertFalse(card["human_approved"])
        self.assertFalse(card["source_rights_verified"])
        self.assertFalse(card["source_text_available"])
        self.assertTrue(value["stateless_replay_only"])
        self.assertFalse(value["execution_state_persisted"])
        self.assertFalse(value["graph_writes_performed"])
        self.assertFalse(value["provider_or_llm_calls"])
        self.assertIsNone(value["tool_result"]["generated_answer"])
        self.assertEqual(value["research_release_status"], "HOLD")
        self.assertEqual(self.store.calls, [
            ("analysis_source_links", {"id": p, "fetch_limit": 21})
            for p in sorted((FOCUS, TARGET))
        ])

    def test_context_and_dossier_dispatch_only_fixed_reads(self):
        self.store.calls.clear()
        response, _ = self.execute_operation("source_context", read_budget=1)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["scheduled_graph_reads"], 1)
        self.assertEqual(response.json()["returned_card_count"], 1)
        self.assertEqual(self.store.calls, [
            ("analysis_source_links", {"id": FOCUS, "fetch_limit": 21}),
        ])
        self.store.calls.clear()
        response, _ = self.execute_operation("review_dossier", limit=8, read_budget=2)
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["returned_card_count"], 1)
        self.assertFalse(
            payload["tool_result"]["dossier"]["human_approval_recorded"]
        )
        self.assertFalse(
            payload["tool_result"]["dossier_digitally_signed"]
        )
        self.assertEqual(len(self.store.calls), 2)

    def test_changed_checkpoint_scope_or_query_rejected_before_graph_read(self):
        arguments = self.parameters()
        plan = plan_read_only_research_tool(**arguments)
        for params in (
            {**arguments, "request_checkpoint_sha256": "0" * 64},
            {**arguments, "query": "Another reference",
             "request_checkpoint_sha256": plan["request_checkpoint_sha256"]},
            {**arguments, "limit": 7,
             "request_checkpoint_sha256": plan["request_checkpoint_sha256"]},
            {**arguments, "read_budget": 2,
             "request_checkpoint_sha256": plan["request_checkpoint_sha256"]},
        ):
            with self.subTest(params=params), self.assertRaises(ValueError):
                run_read_only_research_tool(self.store, **params)
        self.assertEqual(self.store.calls, [])

    def test_unknown_tools_overbudget_and_unauthorized_filters_fail_closed(self):
        for params in (
            self.parameters(operation="write_cypher"),
            self.parameters(read_budget=1),
            self.parameters(operation="source_context", evidence_ids=EVIDENCE),
            self.parameters(operation="review_dossier", evidence_ids=FOCUS),
            self.parameters(operation="source_context", passage_ids=EVIDENCE),
            self.parameters(operation="review_dossier", limit=9),
            self.parameters(query="ab\ncd"),
            self.parameters(read_budget=True),
        ):
            with self.subTest(params=params), self.assertRaises(ValueError):
                plan_read_only_research_tool(**params)
        self.assertEqual(self.store.calls, [])

    def test_disabled_invalid_flags_and_unauthorized_access_no_graph_reads(self):
        with patch.dict(os.environ, {"DVIROS_ENABLE_RESEARCH_TOOL_RUNNER": "0"}):
            self.assertEqual(self.plan().status_code, 404)
            self.assertEqual(
                self.client.get("/v1/research/agent-tools/catalog",
                                headers=self.auth).status_code, 404
            )
        with patch.dict(os.environ, {"DVIROS_ENABLE_GROUNDED_CONTEXT": "0"}):
            self.assertEqual(self.plan().status_code, 404)
        with patch.dict(os.environ, {"DVIROS_ENABLE_RESEARCH_TOOL_RUNNER": "bad"}):
            self.assertEqual(self.plan().status_code, 503)
        unauthenticated = self.client.get(
            "/v1/research/agent-tools/plan",
            params=self.parameters(),
        )
        self.assertEqual(unauthenticated.status_code, 401)
        self.assertEqual(self.store.calls, [])

    def test_duplicate_unknown_fields_and_bad_checkpoint_fail_before_read(self):
        params = self.parameters()
        base = (
            "/v1/research/agent-tools/plan?"
            f"operation=compare_contexts&passage_ids={params['passage_ids']}"
            "&query=Synthetic&limit=8"
        )
        for ending in ("&operation=write_cypher", "&role=admin", "&limit=9&limit=8"):
            with self.subTest(ending=ending):
                self.assertEqual(
                    self.client.get(base + ending, headers=self.auth).status_code,
                    422,
                )
        checkpoint = self.plan().json()["request_checkpoint_sha256"]
        result = self.client.get(
            "/v1/research/agent-tools/execute",
            params={**params, "request_checkpoint_sha256": checkpoint[:-1] + "x"},
            headers=self.auth,
        )
        self.assertEqual(result.status_code, 422)
        self.assertEqual(self.store.calls, [])

    def test_malformed_source_projection_never_leaks_unlicensed_body(self):
        self.store.data["analysis_source_links"][0]["source_text"] = (
            "PRIVATE_UNLICENSED_TEXT"
        )
        response, _ = self.execute_operation()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("PRIVATE_UNLICENSED_TEXT", response.text)
        with self.assertRaises(DatabaseUnavailable):
            args = self.parameters()
            plan = plan_read_only_research_tool(**args)
            run_read_only_research_tool(
                self.store, **args,
                request_checkpoint_sha256=plan["request_checkpoint_sha256"],
            )


if __name__ == "__main__":
    unittest.main()
