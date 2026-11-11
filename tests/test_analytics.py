"""v0.9.0 synthetic evidence analytics contract and denial tests."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from research_graph.ontology import stable_id
from services.research_api.analytics import analysis_page
from services.research_api.app import create_app
from services.research_api.config import bootstrap_token, load_token
from services.research_api.db import DatabaseUnavailable
from services.research_api.queries import READ_OPERATIONS

FOCUS = stable_id("passage", "synthetic", "focus")
TARGET = stable_id("passage", "synthetic", "target")
CANDIDATE = stable_id("passage", "synthetic", "candidate")
EDGE = stable_id("edge", "synthetic", "edge")
EVIDENCE = stable_id("evidence", "synthetic", "source a")
OTHER = stable_id("evidence", "synthetic", "source b")


class Stub:
    def __init__(self):
        self.calls = []
        self.data = {
            "analysis_source_links": [{
                "id": EDGE, "source_passage_id": FOCUS,
                "target_passage_id": TARGET, "evidence_id": EVIDENCE,
                "claim_kind": "OBSERVED_SOURCE_LINK",
                "review_status": "unreviewed",
                "evidence_review_status": "unreviewed",
                "source_ref": "Synthetic Multiword Work 1:1",
                "version_id": "fixture-only", "rights_tag": "UNREVIEWED",
            }],
            "analysis_shared_targets": [{
                "candidate_passage_id": CANDIDATE,
                "shared_target_passage_id": TARGET,
                "focus_evidence_id": EVIDENCE, "candidate_evidence_id": OTHER,
                "focus_review_status": "unreviewed",
                "candidate_review_status": "disputed",
                "focus_evidence_review_status": "unreviewed",
                "candidate_evidence_review_status": "disputed",
                "focus_source_ref": "Synthetic Work A 1:1",
                "candidate_source_ref": "Synthetic Work B 2:1",
            }],
        }

    def query(self, operation, params=None):
        self.calls.append((operation, params))
        return self.data.get(operation, [])


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        token = Path(self.tmp.name) / "token"
        bootstrap_token(token)
        self.auth = {"Authorization": "Bearer " + load_token(token)}
        self.store = Stub()
        self.client = TestClient(create_app(backend=self.store, token_path=token))

    def test_source_link_trace_is_explicit_and_not_release_approval(self):
        r = self.client.get("/v1/analysis/source-links",
                            params={"passage_id": FOCUS}, headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["items"][0]["evidence_id"], EVIDENCE)
        self.assertEqual(body["items"][0]["source_ref"],
                         "Synthetic Multiword Work 1:1")
        self.assertFalse(body["corpus_completeness_verified"])
        self.assertFalse(body["source_rights_verified"])
        self.assertFalse(body["historical_influence_proven"])
        self.assertEqual(body["research_release_status"], "HOLD")
        self.assertEqual(self.store.calls[-1],
                         ("analysis_source_links", {"id": FOCUS, "fetch_limit": 11}))

    def test_shared_targets_are_not_confirmed_co_citation(self):
        r = self.client.get("/v1/analysis/shared-targets",
                            params={"passage_id": FOCUS}, headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["items"][0]["candidate_evidence_id"], OTHER)
        self.assertIn("not verified co-citation", r.json()["note"])

    def test_has_more_is_bounded_and_never_proves_corpus_completeness(self):
        extra = dict(self.store.data["analysis_source_links"][0])
        extra["id"] = stable_id("edge", "synthetic", "another")
        self.store.data["analysis_source_links"].append(extra)
        r = self.client.get("/v1/analysis/source-links",
                            params={"passage_id": FOCUS, "limit": 1},
                            headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["has_more"])
        self.assertEqual(len(r.json()["items"]), 1)
        self.assertFalse(r.json()["corpus_completeness_verified"])

    def test_auth_and_input_denials_happen_before_database(self):
        n = len(self.store.calls)
        self.assertEqual(self.client.get("/v1/analysis/source-links",
                         params={"passage_id": FOCUS}).status_code, 401)
        self.assertEqual(len(self.store.calls), n)
        for url in [
            "/v1/analysis/source-links?passage_id=bad",
            f"/v1/analysis/shared-targets?passage_id={EVIDENCE}",
            f"/v1/analysis/unsupported?passage_id={FOCUS}",
            f"/v1/analysis/source-links?passage_id={FOCUS}&limit=21",
            f"/v1/analysis/source-links?passage_id={FOCUS}&rights=approved",
            f"/v1/analysis/source-links?passage_id={FOCUS}&passage_id={FOCUS}",
        ]:
            with self.subTest(url=url):
                n = len(self.store.calls)
                self.assertEqual(self.client.get(url, headers=self.auth).status_code, 422)
                self.assertEqual(len(self.store.calls), n)

    def test_untrusted_projection_and_inflated_evidence_fail_closed(self):
        for key, invalid in [
            ("claim_kind", "MODEL_SUGGESTION"),
            ("source_passage_id", CANDIDATE),
            ("review_status", "automatically-approved"),
            ("source_ref", "bad\ntext"),
        ]:
            row = self.store.data["analysis_source_links"][0]
            old = row[key]
            row[key] = invalid
            try:
                r = self.client.get("/v1/analysis/source-links",
                                    params={"passage_id": FOCUS}, headers=self.auth)
                self.assertEqual(r.status_code, 503, r.text)
                self.assertNotIn("bad", r.text)
            finally:
                row[key] = old
        self.store.data["analysis_source_links"][0]["source_text"] = "UNLICENSED"
        r = self.client.get("/v1/analysis/source-links",
                            params={"passage_id": FOCUS}, headers=self.auth)
        self.assertEqual(r.status_code, 503)
        self.assertNotIn("UNLICENSED", r.text)
        stub = Stub()
        stub.data["analysis_source_links"] *= 2
        with self.assertRaises(DatabaseUnavailable):
            analysis_page(stub, kind="source-links", passage_id=FOCUS, limit=2)

    def test_bad_shared_target_candidate_and_readonly_registry(self):
        stub = Stub()
        stub.data["analysis_shared_targets"][0]["candidate_passage_id"] = FOCUS
        with self.assertRaises(DatabaseUnavailable):
            analysis_page(stub, kind="shared-targets", passage_id=FOCUS)
        for name in ("analysis_source_links", "analysis_shared_targets"):
            cypher = READ_OPERATIONS[name].upper()
            self.assertIn("LIMIT $FETCH_LIMIT", cypher)
            for forbidden in ("CREATE ", "MERGE ", "DELETE ", "SET ", "CALL "):
                self.assertNotIn(forbidden, cypher)
        self.assertIn("/v1/analysis/{kind}",
                      self.client.get("/openapi.json").json()["paths"])


if __name__ == "__main__":
    unittest.main()
