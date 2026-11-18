"""v0.12.2 signed multi-run review inbox: deduplication, HMAC and private CLI."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.research_review_inbox_v0122 import main as inbox_cli
from services.research_api.config import bootstrap_token, load_token
from services.research_api.research_review_inbox_v0122 import (
    build_research_review_inbox, verify_research_review_inbox,
)
from services.research_api.research_tool_runner_v0120 import (
    plan_read_only_research_tool,
)
from services.research_api.research_tool_receipt_v0121 import (
    build_signed_research_tool_run,
)
from tests.test_analytics import Stub, FOCUS, TARGET, EVIDENCE


class SignedResearchReviewInboxTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.key = self.folder / "token"
        bootstrap_token(self.key)
        self.secret = load_token(self.key)
        self.store = Stub()
        self.scopes = ",".join(sorted((FOCUS, TARGET)))

    def signed_run(self, operation, *, query="Synthetic Multiword"):
        params = {
            "operation": operation,
            "passage_ids": FOCUS if operation == "source_context" else self.scopes,
            "query": query,
            "limit": 8,
            "read_budget": 3,
        }
        if operation == "review_dossier":
            params["evidence_ids"] = EVIDENCE
        checkpoint = plan_read_only_research_tool(
            **params,
        )["request_checkpoint_sha256"]
        return build_signed_research_tool_run(
            self.store, secret=self.secret,
            request_checkpoint_sha256=checkpoint, **params,
        )

    def test_two_signed_runs_deduplicate_one_evidence_offline(self):
        first = self.signed_run("source_context")
        second = self.signed_run("compare_contexts")
        self.assertEqual(len(self.store.calls), 3)
        self.store.calls.clear()
        receipt = build_research_review_inbox(
            [first, second], secret=self.secret,
        )
        inbox = receipt["inbox"]
        self.assertEqual(inbox["schema_version"], "0.12.2")
        self.assertEqual(inbox["run_count"], 2)
        self.assertEqual(inbox["observed_card_count"], 2)
        self.assertEqual(inbox["distinct_evidence_count"], 1)
        self.assertEqual(inbox["repeated_evidence_count"], 1)
        self.assertEqual(inbox["evidence"][0]["evidence_id"], EVIDENCE)
        self.assertEqual(inbox["evidence"][0]["observation_count"], 2)
        self.assertEqual(inbox["metadata_warning_evidence_count"], 0)
        self.assertEqual(
            [s["run_index"] for s in inbox["run_summaries"]], [0, 1]
        )
        self.assertTrue(inbox["source_run_receipts_hmac_verified"])
        self.assertFalse(inbox["human_review_decisions_recorded"])
        self.assertFalse(inbox["immutable_graph_snapshot_verified"])
        self.assertFalse(inbox["source_text_exported"])
        self.assertEqual(inbox["research_release_status"], "HOLD")
        result = verify_research_review_inbox(
            receipt, [second, first], secret=self.secret,
        )
        self.assertTrue(result["review_inbox_hmac_verified"])
        self.assertEqual(result["graph_reads_during_verification"], 0)
        self.assertEqual(self.store.calls, [])
        self.assertEqual(
            receipt, build_research_review_inbox(
                [second, first], secret=self.secret,
            ),
        )

    def test_observed_rights_edition_and_review_variants_are_warnings_only(self):
        first = self.signed_run("source_context")
        row = self.store.data["analysis_source_links"][0]
        row["version_id"] = "later-edition"
        row["rights_tag"] = "RIGHTS_NOT_CLEARED"
        row["evidence_review_status"] = "disputed"
        second = self.signed_run("compare_contexts")
        self.store.calls.clear()
        report = build_research_review_inbox(
            [first, second], secret=self.secret,
        )["inbox"]
        candidate = report["evidence"][0]
        self.assertEqual(report["metadata_warning_evidence_count"], 1)
        self.assertIn("VERSION_ID_DIVERGENCE", candidate["triage_warnings"])
        self.assertIn("RIGHTS_TAG_DIVERGENCE", candidate["triage_warnings"])
        self.assertIn(
            "OBSERVED_REVIEW_STATUS_DIVERGENCE",
            candidate["triage_warnings"],
        )
        self.assertIn(
            "CONTESTED_REVIEW_LABEL_OBSERVED",
            candidate["triage_warnings"],
        )
        self.assertFalse(candidate["scholarly_conflict_verified"])
        self.assertFalse(candidate["licensed_source_rights_verified"])
        self.assertEqual(self.store.calls, [])

    def test_duplicate_inputs_wrong_secret_and_forged_status_fail_closed(self):
        first = self.signed_run("source_context")
        second = self.signed_run("compare_contexts")
        with self.assertRaises(ValueError):
            build_research_review_inbox([first, first], secret=self.secret)
        with self.assertRaises(ValueError):
            build_research_review_inbox(
                [first, second], secret="x" * 64,
            )
        receipt = build_research_review_inbox(
            [first, second], secret=self.secret,
        )
        for field, value in (
            ("human_review_decisions_recorded", True),
            ("research_release_status", "PASS"),
            ("distinct_evidence_count", 80),
        ):
            forged = deepcopy(receipt)
            forged["inbox"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify_research_review_inbox(
                    forged, [first, second], secret=self.secret,
                )
        forged = deepcopy(second)
        forged["execution"]["evidence_cards"][0]["rights_tag"] = "APPROVED"
        with self.assertRaises(ValueError):
            build_research_review_inbox(
                [first, forged], secret=self.secret,
            )
        forged = deepcopy(receipt)
        forged["inbox_hmac_sha256"] = "a" * 64
        with self.assertRaises(ValueError):
            verify_research_review_inbox(
                forged, [first, second], secret=self.secret,
            )

    def test_empty_second_run_retains_no_match_uncertainty(self):
        matched = self.signed_run("source_context")
        no_match = self.signed_run(
            "compare_contexts", query="unmatched-reference",
        )
        inbox = build_research_review_inbox(
            [matched, no_match], secret=self.secret,
        )["inbox"]
        self.assertEqual(inbox["run_count"], 2)
        self.assertEqual(inbox["observed_card_count"], 1)
        self.assertEqual(inbox["distinct_evidence_count"], 1)
        self.assertEqual(
            sorted(s["observed_evidence_card_count"] for s in
                   inbox["run_summaries"]), [0, 1],
        )
        self.assertFalse(inbox["historical_graph_changes_proven"])

    def test_owner_only_cli_build_verify_and_no_overwrite(self):
        first = self.signed_run("source_context")
        second = self.signed_run("review_dossier")
        paths = []
        for idx, run in enumerate([first, second]):
            p = self.folder / f"run-{idx}.json"
            p.write_text(json.dumps(run), encoding="utf-8")
            p.chmod(0o600)
            paths.append(p)
        args = [
            "--run", str(paths[0]), "--run", str(paths[1]),
            "--token-path", str(self.key),
        ]
        output = self.folder / "inbox.json"
        self.store.calls.clear()
        self.assertEqual(inbox_cli([
            "build", *args, "--output", str(output),
        ]), 0)
        self.assertEqual(inbox_cli([
            "verify", *args, "--report", str(output),
        ]), 0)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.calls, [])
        self.assertEqual(inbox_cli([
            "build", *args, "--output", str(output),
        ]), 1)
        paths[1].chmod(0o644)
        self.assertEqual(inbox_cli([
            "verify", *args, "--report", str(output),
        ]), 1)


if __name__ == "__main__":
    unittest.main()
