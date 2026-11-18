"""v0.11.3 offline dossier-diff behavior and fail-closed privacy tests."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest

from research_graph.ontology import stable_id
from scripts.grounded_dossier_diff_v0113 import main as diff_cli
from services.research_api.grounded_dossier_v0112 import (
    _digest as dossier_digest,
    build_grounded_evidence_dossier,
)
from services.research_api.grounded_dossier_diff_v0113 import (
    build_grounded_dossier_diff,
    verify_grounded_dossier_diff,
)
from tests.test_analytics import Stub, FOCUS, TARGET, EVIDENCE


class GroundedDossierDiffTests(unittest.TestCase):
    def setUp(self):
        self.store = Stub()
        self.scopes = ",".join(sorted((FOCUS, TARGET)))
        self.query = "Synthetic Multiword"

    def dossier(self, ids=None, query=None, scopes=None):
        return build_grounded_evidence_dossier(
            self.store, passage_ids=scopes or self.scopes,
            query=query or self.query,
            evidence_ids=",".join(sorted(ids or [EVIDENCE])),
        )

    def add_evidence(self):
        second = stable_id("evidence", "v0113", "second")
        edge = stable_id("edge", "v0113", "second")
        source = deepcopy(self.store.data["analysis_source_links"][0])
        self.store.data["analysis_source_links"].append({
            **source,
            "evidence_id": second,
            "id": edge,
            "source_ref": "Synthetic Multiword Work 2:2",
            "version_id": "second-edition",
            "rights_tag": "NEEDS_REVIEW",
            "review_status": "disputed",
        })
        return second

    def test_unchanged_input_reports_no_fabricated_source_events(self):
        before = self.dossier()
        result = build_grounded_dossier_diff(before, before)
        delta = result["comparison"]
        self.assertEqual(delta["schema_version"], "0.11.3")
        self.assertEqual(delta["unchanged_evidence_ids"], [EVIDENCE])
        self.assertEqual(delta["changed_evidence"], [])
        self.assertEqual(delta["newly_selected_evidence_ids"], [])
        self.assertEqual(delta["deselected_evidence_ids"], [])
        self.assertFalse(delta["selection_change_is_graph_mutation"])
        self.assertFalse(delta["input_dossiers_authenticated"])
        self.assertFalse(result["comparison_digitally_signed"])
        self.assertIsNone(delta["generated_claim"])
        self.assertEqual(delta["research_release_status"], "HOLD")
        verified = verify_grounded_dossier_diff(result, before, before)
        self.assertTrue(verified["offline_replay_verified"])
        self.assertEqual(verified["unchanged_count"], 1)

    def test_version_rights_review_changes_have_exact_before_after(self):
        before = self.dossier()
        row = self.store.data["analysis_source_links"][0]
        row["version_id"] = "revised-edition"
        row["rights_tag"] = "RIGHTS_NOT_CLEARED"
        row["review_status"] = "disputed"
        after = self.dossier()
        receipt = build_grounded_dossier_diff(before, after)
        changes = receipt["comparison"]["changed_evidence"]
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["evidence_id"], EVIDENCE)
        fields = {x["field"]: x for x in changes[0]["changed_fields"]}
        self.assertEqual(fields["version_id"]["before"], "fixture-only")
        self.assertEqual(fields["version_id"]["after"], "revised-edition")
        self.assertEqual(fields["rights_tag"]["after"], "RIGHTS_NOT_CLEARED")
        self.assertEqual(fields["edge_review_status"]["after"], "disputed")
        self.assertIn("VERSION_METADATA_CHANGED", changes[0]["review_flags"])
        self.assertIn("RIGHTS_METADATA_CHANGED", changes[0]["review_flags"])
        self.assertIn("REVIEW_STATUS_CHANGED", changes[0]["review_flags"])
        self.assertEqual(receipt["comparison"]["changed_count"], 1)
        self.assertEqual(receipt["comparison"]["unchanged_count"], 0)

    def test_selection_add_remove_not_mislabeled_as_graph_deletion(self):
        before = self.dossier()
        second = self.add_evidence()
        after = self.dossier([EVIDENCE, second])
        delta = build_grounded_dossier_diff(before, after)["comparison"]
        self.assertEqual(delta["newly_selected_evidence_ids"], [second])
        self.assertEqual(delta["deselected_evidence_ids"], [])
        self.assertEqual(delta["unchanged_evidence_ids"], [EVIDENCE])
        self.assertFalse(delta["selection_change_is_graph_mutation"])
        inverse = build_grounded_dossier_diff(after, before)["comparison"]
        self.assertEqual(inverse["deselected_evidence_ids"], [second])
        self.assertEqual(inverse["newly_selected_evidence_ids"], [])
        self.assertFalse(inverse["graph_snapshot_verified"])

    def test_different_query_or_passage_scope_refused(self):
        before = self.dossier()
        different_query = self.dossier(query="Synthetic")
        other_passage = stable_id("passage", "v0113", "extra")
        different_scope = self.dossier(
            scopes=",".join(sorted((FOCUS, other_passage))),
        )
        for other in (different_query, different_scope):
            with self.assertRaises(ValueError):
                build_grounded_dossier_diff(before, other)

    def test_invalid_input_extra_text_and_forged_approval_fail_closed(self):
        before = self.dossier()
        wrong = deepcopy(before)
        wrong["dossier"]["selected_items"][0]["source_text"] = (
            "UNLICENSED_TEXT_NEVER_EXPORTED"
        )
        wrong["dossier_sha256"] = dossier_digest(wrong["dossier"])
        with self.assertRaises(ValueError):
            build_grounded_dossier_diff(wrong, before)
        approval = deepcopy(before)
        approval["dossier"]["human_approval_recorded"] = True
        approval["dossier_sha256"] = dossier_digest(approval["dossier"])
        with self.assertRaises(ValueError):
            build_grounded_dossier_diff(approval, before)
        invalid_selection = deepcopy(before)
        invalid_selection["dossier"]["selected_evidence_ids"] = [
            stable_id("evidence", "v0113", "missing")
        ]
        invalid_selection["dossier_sha256"] = dossier_digest(
            invalid_selection["dossier"]
        )
        with self.assertRaises(ValueError):
            build_grounded_dossier_diff(invalid_selection, before)

    def test_receipt_tampering_even_with_rehashed_delta_refused(self):
        before = self.dossier()
        after = self.dossier()
        receipt = build_grounded_dossier_diff(before, after)
        forged = deepcopy(receipt)
        forged["comparison"]["human_approval_recorded"] = True
        with self.assertRaises(ValueError):
            verify_grounded_dossier_diff(forged, before, after)
        forged = deepcopy(receipt)
        forged["comparison_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            verify_grounded_dossier_diff(forged, before, after)

    def test_private_cli_creates_once_and_refuses_weak_inputs(self):
        before = self.dossier()
        self.add_evidence()
        after = self.dossier()
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            def private(name, value):
                p = folder / name
                p.write_text(json.dumps(value), encoding="utf-8")
                p.chmod(0o600)
                return p
            old = private("before.json", before)
            new = private("after.json", after)
            receipt_path = folder / "delta.json"
            args = ["--before", str(old), "--after", str(new)]
            self.assertEqual(diff_cli([
                "build", *args, "--output", str(receipt_path),
            ]), 0)
            self.assertEqual(diff_cli([
                "verify", *args, "--report", str(receipt_path),
            ]), 0)
            self.assertEqual(receipt_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(diff_cli([
                "build", *args, "--output", str(receipt_path),
            ]), 1)
            new.chmod(0o644)
            self.assertEqual(diff_cli([
                "verify", *args, "--report", str(receipt_path),
            ]), 1)


if __name__ == "__main__":
    unittest.main()
