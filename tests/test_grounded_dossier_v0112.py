"""v0.11.2 Evidence-dossier API, replay and refusal checks (synthetic-only)."""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from research_graph.ontology import stable_id
from services.research_api.app import create_app
from services.research_api.config import bootstrap_token, load_token
from services.research_api.db import DatabaseUnavailable
from services.research_api.grounded_dossier_v0112 import (
    build_grounded_evidence_dossier,
    parse_selected_evidence_ids,
    verify_grounded_evidence_dossier,
)
from tests.test_analytics import Stub, FOCUS, TARGET, EVIDENCE


class GroundedDossierTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        token_path = Path(self.tmp.name) / "token"
        bootstrap_token(token_path)
        self.store = Stub()
        self.auth = {"Authorization": "Bearer " + load_token(token_path)}
        self.client = TestClient(
            create_app(backend=self.store, token_path=token_path)
        )
        gate = patch.dict(
            os.environ, {"DVIROS_ENABLE_GROUNDED_CONTEXT": "1"}
        )
        gate.start()
        self.addCleanup(gate.stop)
        self.scopes = ",".join(sorted((FOCUS, TARGET)))

    def request(self, **overrides):
        params = {
            "passage_ids": self.scopes,
            "query": "Synthetic Multiword",
            "evidence_ids": EVIDENCE,
        }
        params.update(overrides)
        return self.client.get(
            "/v1/research/grounded-context/dossier",
            params=params, headers=self.auth,
        )

    def build(self, **overrides):
        params = {
            "passage_ids": self.scopes,
            "query": "Synthetic Multiword",
            "evidence_ids": EVIDENCE,
        }
        params.update(overrides)
        return build_grounded_evidence_dossier(self.store, **params)

    def test_selected_observed_evidence_has_complete_draft_provenance(self):
        response = self.request()
        self.assertEqual(response.status_code, 200, response.text)
        output = response.json()
        dossier = output["dossier"]
        self.assertEqual(dossier["schema_version"], "0.11.2")
        self.assertEqual(dossier["selected_evidence_ids"], [EVIDENCE])
        self.assertEqual(dossier["selection_count"], 1)
        self.assertEqual(len(dossier["observed_windows"]), 2)
        self.assertEqual(len(dossier["selected_items"]), 1)
        item = dossier["selected_items"][0]
        self.assertEqual(item["evidence_id"], EVIDENCE)
        self.assertEqual(item["source_ref"], "Synthetic Multiword Work 1:1")
        self.assertEqual(item["version_id"], "fixture-only")
        self.assertEqual(
            item["observed_in_passage_ids"], sorted((FOCUS, TARGET))
        )
        self.assertTrue(item["source_metadata_complete"])
        self.assertFalse(item["human_review_approved"])
        self.assertFalse(item["quote_verified_against_edition"])
        self.assertFalse(dossier["human_approval_recorded"])
        self.assertFalse(dossier["graph_snapshot_verified"])
        self.assertIsNone(dossier["generated_claim"])
        self.assertFalse(output["dossier_digitally_signed"])
        self.assertEqual(len(output["dossier_sha256"]), 64)
        self.assertEqual(dossier["research_release_status"], "HOLD")
        self.assertEqual(
            self.store.calls,
            [
                ("analysis_source_links", {"id": pid, "fetch_limit": 21})
                for pid in sorted((FOCUS, TARGET))
            ],
        )

    def test_deterministic_sha_and_exact_live_source_replay(self):
        first = self.build()
        second = self.build()
        self.assertEqual(first, second)
        proof = verify_grounded_evidence_dossier(
            first, self.store,
            passage_ids=self.scopes,
            query="Synthetic Multiword", evidence_ids=EVIDENCE,
        )
        self.assertTrue(proof["dossier_recomputed"])
        self.assertFalse(proof["dossier_digitally_signed"])
        modified = deepcopy(first)
        modified["dossier"]["human_approval_recorded"] = True
        with self.assertRaises(ValueError):
            verify_grounded_evidence_dossier(
                modified, self.store,
                passage_ids=self.scopes, query="Synthetic Multiword",
                evidence_ids=EVIDENCE,
            )
        # A changed version invalidates the previous, unsigned observation.
        self.store.data["analysis_source_links"][0]["version_id"] = "later-edition"
        with self.assertRaises(ValueError):
            verify_grounded_evidence_dossier(
                first, self.store,
                passage_ids=self.scopes, query="Synthetic Multiword",
                evidence_ids=EVIDENCE,
            )

    def test_bad_selection_and_bad_passage_scope_denied_before_graph_read(self):
        other = stable_id("evidence", "dossier", "other")
        for selection in (
            "", "wrong", FOCUS, EVIDENCE + "," + EVIDENCE,
            ",".join(reversed(sorted((EVIDENCE, other)))),
            ",".join([EVIDENCE] * 9),
        ):
            with self.subTest(selection=selection), self.assertRaises(
                ValueError
            ):
                parse_selected_evidence_ids(selection)
        for params in (
            {"evidence_ids": FOCUS},
            {"evidence_ids": EVIDENCE + "," + EVIDENCE},
            {"passage_ids": FOCUS},
            {"passage_ids": self.scopes + "," + FOCUS},
            {"query": "ab\ncd"},
        ):
            with self.subTest(params=params):
                self.assertEqual(self.request(**params).status_code, 422)
        self.assertEqual(self.store.calls, [])

    def test_absent_and_out_of_scope_evidence_is_not_invented(self):
        missing = stable_id("evidence", "v0112", "missing")
        response = self.request(evidence_ids=missing)
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(missing, response.text)
        response = self.request(query="unmatched-bibliography")
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(EVIDENCE, response.text)

    def test_feature_gate_and_missing_auth_never_access_graph(self):
        with patch.dict(os.environ, {"DVIROS_ENABLE_GROUNDED_CONTEXT": "0"}):
            self.assertEqual(self.request().status_code, 404)
        with patch.dict(os.environ, {"DVIROS_ENABLE_GROUNDED_CONTEXT": "no"}):
            self.assertEqual(self.request().status_code, 503)
        unauthenticated = self.client.get(
            "/v1/research/grounded-context/dossier",
            params={
                "passage_ids": self.scopes,
                "query": "Synthetic",
                "evidence_ids": EVIDENCE,
            },
        )
        self.assertEqual(unauthenticated.status_code, 401)
        self.assertEqual(self.store.calls, [])

    def test_extra_and_duplicate_filters_denied_before_graph_read(self):
        base = (
            "/v1/research/grounded-context/dossier?"
            f"passage_ids={self.scopes}&query=Synthetic"
            f"&evidence_ids={EVIDENCE}"
        )
        for suffix in (
            "&rights=approved",
            "&query=override",
            "&evidence_ids=override",
            "&limit=100",
        ):
            with self.subTest(suffix=suffix):
                result = self.client.get(base + suffix, headers=self.auth)
                self.assertEqual(result.status_code, 422, result.text)
        self.assertEqual(self.store.calls, [])

    def test_multi_selection_retains_review_warnings_without_approval(self):
        original = deepcopy(self.store.data["analysis_source_links"][0])
        another = stable_id("evidence", "v0112", "second")
        self.store.data["analysis_source_links"].append({
            **original,
            "id": stable_id("edge", "v0112", "second"),
            "evidence_id": another,
            "version_id": "new-edition",
            "rights_tag": None,
            "review_status": "disputed",
        })
        ids = ",".join(sorted([EVIDENCE, another]))
        response = self.request(evidence_ids=ids)
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()["dossier"]
        self.assertEqual(payload["selection_count"], 2)
        self.assertEqual(
            payload["selected_evidence_ids"], sorted([EVIDENCE, another])
        )
        for item in payload["selected_items"]:
            self.assertIn(
                "OBSERVED_VERSION_ID_DIVERGENCE", item["triage_flags"]
            )
            self.assertIn(
                "CONTESTED_REVIEW_STATUS_OBSERVED", item["triage_flags"]
            )
            self.assertFalse(item["human_review_approved"])
        self.assertFalse(payload["selected_items"][1][
            "source_rights_independently_verified"
        ])

    def test_malformed_projection_fails_without_leaking_unlicensed_text(self):
        self.store.data["analysis_source_links"][0]["source_text"] = (
            "UNLICENSED_PRIVATE_BODY"
        )
        result = self.request()
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("UNLICENSED_PRIVATE_BODY", result.text)
        with self.assertRaises(DatabaseUnavailable):
            self.build()


if __name__ == "__main__":
    unittest.main()
