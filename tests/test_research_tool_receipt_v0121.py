"""v0.12.1 source-bound service HMAC receipts and fail-closed replay."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from scripts.verify_research_tool_receipt_v0121 import main as verify_cli
from services.research_api.app import create_app
from services.research_api.config import bootstrap_token, load_token
from services.research_api.research_tool_receipt_v0121 import (
    build_signed_research_tool_run, verify_signed_research_tool_run,
)
from services.research_api.research_tool_runner_v0120 import (
    plan_read_only_research_tool,
)
from tests.test_analytics import Stub, FOCUS, TARGET, EVIDENCE


class SignedResearchToolRunTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.key = self.folder / "token"
        bootstrap_token(self.key)
        self.secret = load_token(self.key)
        self.auth = {"Authorization": "Bearer " + self.secret}
        self.store = Stub()
        self.client = TestClient(create_app(
            backend=self.store, token_path=self.key,
        ))
        gate = patch.dict(os.environ, {
            "DVIROS_ENABLE_GROUNDED_CONTEXT": "1",
            "DVIROS_ENABLE_RESEARCH_TOOL_RUNNER": "1",
        })
        gate.start()
        self.addCleanup(gate.stop)

    def arguments(self, operation="compare_contexts"):
        args = {
            "operation": operation,
            "passage_ids": ",".join(sorted((FOCUS, TARGET))),
            "query": "Synthetic Multiword",
            "limit": 8, "read_budget": 3,
        }
        if operation == "source_context":
            args["passage_ids"] = FOCUS
        if operation == "review_dossier":
            args["evidence_ids"] = EVIDENCE
        return args

    def signed_api(self, operation="compare_contexts"):
        params = self.arguments(operation)
        checkpoint = plan_read_only_research_tool(
            **params,
        )["request_checkpoint_sha256"]
        return self.client.get(
            "/v1/research/agent-tools/execute/signed",
            params={**params, "request_checkpoint_sha256": checkpoint},
            headers=self.auth,
        )

    def test_signed_comparison_replays_without_database_access(self):
        response = self.signed_api()
        self.assertEqual(response.status_code, 200, response.text)
        value = response.json()
        receipt = value["signed_receipt"]
        self.assertEqual(receipt["receipt"]["schema_version"], "0.12.1")
        self.assertEqual(receipt["receipt"]["ordered_evidence_ids"], [EVIDENCE])
        self.assertEqual(receipt["receipt"]["returned_card_count"], 1)
        self.assertFalse(receipt["receipt"]["reviewer_identity_verified"])
        self.assertFalse(receipt["receipt"]["immutable_graph_snapshot_verified"])
        self.assertEqual(receipt["receipt"]["research_release_status"], "HOLD")
        self.assertEqual(len(self.store.calls), 2)
        self.store.calls.clear()
        summary = verify_signed_research_tool_run(value, secret=self.secret)
        self.assertTrue(summary["local_service_hmac_verified"])
        self.assertEqual(summary["graph_reads_during_verification"], 0)
        self.assertEqual(self.store.calls, [])

    def test_all_registered_tool_receipts_are_typed_and_signed(self):
        for operation in ("source_context", "review_dossier"):
            with self.subTest(operation=operation):
                self.store.calls.clear()
                response = self.signed_api(operation)
                self.assertEqual(response.status_code, 200, response.text)
                value = response.json()
                summary = verify_signed_research_tool_run(
                    value, secret=self.secret,
                )
                self.assertEqual(summary["tool_operation"], operation)
                self.assertEqual(
                    summary["returned_card_count"],
                    value["execution"]["returned_card_count"],
                )
                self.assertFalse(summary["reviewer_identity_verified"])
                self.assertFalse(value["plan"][
                    "checkpoint_authenticates_reviewer"
                ])
                self.assertTrue(all(
                    not card["source_text_available"]
                    for card in value["execution"]["evidence_cards"]
                ))

    def test_tamper_wrong_key_and_rehashed_evidence_are_refused(self):
        value = self.signed_api().json()
        with self.assertRaises(ValueError):
            verify_signed_research_tool_run(
                value, secret="x" * 64,
            )
        changed = deepcopy(value)
        changed["execution"]["evidence_cards"][0]["rights_tag"] = "CLEARED"
        with self.assertRaises(ValueError):
            verify_signed_research_tool_run(changed, secret=self.secret)
        changed = deepcopy(value)
        changed["signed_receipt"]["receipt"][
            "human_research_approval_recorded"
        ] = True
        with self.assertRaises(ValueError):
            verify_signed_research_tool_run(changed, secret=self.secret)
        changed = deepcopy(value)
        changed["signed_receipt"]["receipt_sha256"] = "a" * 64
        with self.assertRaises(ValueError):
            verify_signed_research_tool_run(changed, secret=self.secret)
        changed = deepcopy(value)
        changed["plan"]["parameters"]["read_budget"] = 1
        with self.assertRaises(ValueError):
            verify_signed_research_tool_run(changed, secret=self.secret)

    def test_wrong_checkpoint_missing_auth_and_disabled_flags_make_no_read(self):
        params = self.arguments()
        wrong = self.client.get(
            "/v1/research/agent-tools/execute/signed",
            params={**params, "request_checkpoint_sha256": "a" * 64},
            headers=self.auth,
        )
        self.assertEqual(wrong.status_code, 422)
        with patch.dict(os.environ, {"DVIROS_ENABLE_RESEARCH_TOOL_RUNNER": "0"}):
            self.assertEqual(self.signed_api().status_code, 404)
        with patch.dict(os.environ, {"DVIROS_ENABLE_GROUNDED_CONTEXT": "0"}):
            self.assertEqual(self.signed_api().status_code, 404)
        unauthorized = self.client.get(
            "/v1/research/agent-tools/execute/signed",
            params={**params, "request_checkpoint_sha256": "a" * 64},
        )
        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(self.store.calls, [])

    def test_private_offline_cli_and_source_text_protection(self):
        response = self.signed_api()
        self.assertEqual(response.status_code, 200, response.text)
        report = self.folder / "signed-report.json"
        report.write_text(json.dumps(response.json()), encoding="utf-8")
        report.chmod(0o600)
        self.store.calls.clear()
        self.assertEqual(verify_cli([
            "--report", str(report), "--token-path", str(self.key),
        ]), 0)
        self.assertEqual(self.store.calls, [])
        report.chmod(0o644)
        self.assertEqual(verify_cli([
            "--report", str(report), "--token-path", str(self.key),
        ]), 1)
        self.store.data["analysis_source_links"][0]["source_text"] = (
            "PRIVATE_UNLICENSED_SOURCE_BODY"
        )
        failed = self.signed_api()
        self.assertEqual(failed.status_code, 503)
        self.assertNotIn("PRIVATE_UNLICENSED_SOURCE_BODY", failed.text)


if __name__ == "__main__":
    unittest.main()
