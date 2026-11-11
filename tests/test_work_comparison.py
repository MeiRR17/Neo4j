"""v0.9.3 synthetic-only private Work comparison, evidence and denial tests."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from research_graph.ontology import stable_id
from services.research_api.app import create_app
from services.research_api.config import bootstrap_token, load_token
from services.research_api.db import DatabaseUnavailable
from services.research_api.queries import READ_OPERATIONS
from services.research_api.work_comparison import compare_works

LEFT = stable_id("work", "synthetic-v093", "left")
RIGHT = stable_id("work", "synthetic-v093", "right")
P1 = stable_id("passage", "synthetic-v093", "left first")
P2 = stable_id("passage", "synthetic-v093", "right first")
A1 = stable_id("person", "synthetic-v093", "left author")
A2 = stable_id("person", "synthetic-v093", "right author")


def author(identity=A1, start=1100, end=1160):
    return {"id": identity, "date_from_year": start, "date_to_year": end}


def edge(identity="first", source_work=LEFT, target_work=RIGHT,
         source_passage=P1, target_passage=P2,
         link_status="approved", evidence_status="approved"):
    return {
        "edge_id": stable_id("edge", "synthetic-v093", identity),
        "source_work_id": source_work,
        "target_work_id": target_work,
        "source_passage_id": source_passage,
        "target_passage_id": target_passage,
        "evidence_id": stable_id("evidence", "synthetic-v093", identity),
        "edge_review_status": link_status,
        "evidence_review_status": evidence_status,
        "source_ref": "Synthetic Work Alpha 1:1",
        "target_ref": "Synthetic Work Beta 1:1",
        "evidence_source_ref": "SYNTHETIC ONLY",
        "version_id": "synthetic-version",
        "rights_tag": "UNREVIEWED",
    }


class FakeStore:
    def __init__(self):
        self.calls = []
        self.works = {
            LEFT: {
                "id": LEFT, "title": "Synthetic Work Alpha",
                "provider_ref": "synthetic:alpha",
                "author_sample": [author()],
            },
            RIGHT: {
                "id": RIGHT, "title": "Synthetic Work Beta",
                "provider_ref": "synthetic:beta",
                "author_sample": [author(A2, 1210, 1270)],
            },
        }
        self.forward = [
            edge("first"),
            edge("second", link_status="disputed", evidence_status="unreviewed"),
        ]
        self.reverse = [
            edge("reverse", source_work=RIGHT, target_work=LEFT,
                 source_passage=P2, target_passage=P1,
                 link_status="unreviewed", evidence_status="unreviewed")
        ]

    def query(self, name, params):
        self.calls.append((name, deepcopy(params)))
        if name == "analysis_work_descriptor":
            value = self.works.get(params["work_id"])
            return [deepcopy(value)] if value is not None else []
        if name == "analysis_work_cross_links":
            data = (self.forward if params["source_work_id"] == LEFT
                    else self.reverse)
            return deepcopy(data)
        raise AssertionError("Unexpected graph query")


class WorkComparisonTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        token = Path(temp.name) / "api-token"
        bootstrap_token(token)
        self.auth = {"Authorization": "Bearer " + load_token(token)}
        self.store = FakeStore()
        self.client = TestClient(create_app(backend=self.store, token_path=token))

    def get(self, **kwargs):
        params = {"left_work_id": LEFT, "right_work_id": RIGHT, "limit": 2}
        params.update(kwargs)
        return self.client.get("/v1/analysis/works/compare",
                               params=params, headers=self.auth)

    def test_two_work_comparison_preserves_review_and_direction(self):
        response = self.get()
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["schema_version"], "0.9.3")
        self.assertEqual(data["left_work"]["id"], LEFT)
        self.assertEqual(data["right_work"]["id"], RIGHT)
        self.assertEqual(data["left_to_right"]["observed_window_denominator"], 2)
        self.assertEqual(data["right_to_left"]["observed_window_denominator"], 1)
        self.assertEqual(data["left_to_right"]["joint_approved_status_links"], 1)
        self.assertEqual(data["left_to_right"]["contested_status_links"], 1)
        self.assertEqual(data["right_to_left"]["pending_status_links"], 1)
        self.assertEqual(data["author_id_overlap_status"],
                         "different_author_ids_observed")
        self.assertEqual(data["shared_author_ids"], [])
        self.assertFalse(data["all_cross_work_links_examined"])
        self.assertFalse(data["historical_influence_proven"])
        self.assertFalse(data["source_rights_verified"])
        self.assertEqual(data["research_release_status"], "HOLD")
        self.assertEqual([call[0] for call in self.store.calls],
                         ["analysis_work_descriptor", "analysis_work_descriptor",
                          "analysis_work_cross_links", "analysis_work_cross_links"])

    def test_limit_window_and_lookahead_deny_population_claim(self):
        response = self.get(limit=1)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertTrue(data["left_to_right"]["has_more"])
        self.assertEqual(data["left_to_right"]["observed_window_denominator"], 1)
        self.assertEqual(len(data["left_to_right"]["links"]), 1)
        self.assertFalse(data["right_to_left"]["has_more"])
        self.assertEqual(self.store.calls[2][1]["fetch_limit"], 2)

    def test_author_overlap_and_metadata_uncertainty(self):
        self.store.works[RIGHT]["author_sample"] = [author(A1)]
        data = self.get().json()
        self.assertEqual(data["author_id_overlap_status"],
                         "shared_author_id_observed")
        self.assertEqual(data["shared_author_ids"], [A1])
        self.store.works[RIGHT]["author_sample"] = []
        data = self.get().json()
        self.assertEqual(data["author_id_overlap_status"],
                         "insufficient_author_metadata")
        self.assertEqual(data["right_work"]["author_metadata_status"], "missing")
        self.store.works[RIGHT]["author_sample"] = [
            author(A1), author(A2), author(
                stable_id("person", "synthetic-v093", "third author"))
        ]
        data = self.get().json()
        self.assertTrue(data["right_work"]["author_sample_truncated"])
        self.assertEqual(len(data["right_work"]["author_sample"]), 2)
        self.assertEqual(data["author_id_overlap_status"],
                         "insufficient_author_metadata")

    def test_missing_work_returns_404_before_links_are_read(self):
        del self.store.works[RIGHT]
        response = self.get()
        self.assertEqual(response.status_code, 404)
        self.assertEqual([call[0] for call in self.store.calls],
                         ["analysis_work_descriptor", "analysis_work_descriptor"])

    def test_request_auth_and_allowlist_fail_before_database(self):
        before = len(self.store.calls)
        unauthenticated = self.client.get(
            "/v1/analysis/works/compare",
            params={"left_work_id": LEFT, "right_work_id": RIGHT})
        self.assertEqual(unauthenticated.status_code, 401)
        self.assertEqual(len(self.store.calls), before)
        urls = [
            "/v1/analysis/works/compare?left_work_id=BAD&right_work_id=" + RIGHT,
            "/v1/analysis/works/compare?left_work_id=" + LEFT +
            "&right_work_id=" + LEFT,
            "/v1/analysis/works/compare?left_work_id=" + LEFT +
            "&right_work_id=" + P2,
            "/v1/analysis/works/compare?left_work_id=" + LEFT +
            "&right_work_id=" + RIGHT + "&limit=11",
            "/v1/analysis/works/compare?left_work_id=" + LEFT +
            "&right_work_id=" + RIGHT + "&rights=approved",
            "/v1/analysis/works/compare?left_work_id=" + LEFT +
            "&right_work_id=" + RIGHT + "&left_work_id=" + LEFT,
        ]
        for url in urls:
            with self.subTest(url=url):
                before = len(self.store.calls)
                response = self.client.get(url, headers=self.auth)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(len(self.store.calls), before)

    def test_invalid_work_projection_years_and_authors_fail_closed(self):
        baseline = deepcopy(self.store.works[LEFT])
        variants = [
            {"id": RIGHT},
            {"title": "Sensitive\nText"},
            {"unknown_text": "UNLICENSED"},
            {"author_sample": "bad"},
            {"author_sample": [author(start=True)]},
            {"author_sample": [author(start=1700, end=1600)]},
            {"author_sample": [author(A1), author(A1)]},
            {"author_sample": [author(A1)] * 4},
        ]
        for change in variants:
            with self.subTest(change=str(change)[:65]):
                self.store.works[LEFT] = {**deepcopy(baseline), **change}
                response = self.get()
                self.assertEqual(response.status_code, 503, response.text)
                self.assertNotIn("UNLICENSED", response.text)
        self.store.works[LEFT] = baseline

    def test_wrong_work_membership_or_unsafe_evidence_fails_closed(self):
        baseline = deepcopy(self.store.forward[0])
        variants = [
            {"source_work_id": RIGHT},
            {"target_work_id": LEFT},
            {"source_passage_id": "bad"},
            {"target_passage_id": P1},
            {"edge_review_status": "auto_approved"},
            {"evidence_review_status": ["approved"]},
            {"source_ref": "bad\nunsafe"},
            {"source_text": "UNLICENSED_TEXT"},
        ]
        for change in variants:
            with self.subTest(change=str(change)[:65]):
                self.store.forward = [{**deepcopy(baseline), **change}]
                response = self.get()
                self.assertEqual(response.status_code, 503, response.text)
                self.assertNotIn("UNLICENSED_TEXT", response.text)

    def test_repeated_evidence_and_over_budget_fail_closed(self):
        self.store.forward = [edge("same"), edge("same")]
        self.assertRaises(DatabaseUnavailable, compare_works, self.store,
                          left_work_id=LEFT, right_work_id=RIGHT, limit=2)
        self.store.forward = [edge("reverse")]
        self.store.reverse = [edge(
            "reverse", source_work=RIGHT, target_work=LEFT,
            source_passage=P2, target_passage=P1)]
        self.assertRaises(DatabaseUnavailable, compare_works, self.store,
                          left_work_id=LEFT, right_work_id=RIGHT, limit=2)
        self.store.forward = [edge(str(i)) for i in range(12)]
        self.assertRaises(DatabaseUnavailable, compare_works, self.store,
                          left_work_id=LEFT, right_work_id=RIGHT, limit=10)

    def test_read_only_contract_and_typed_openapi(self):
        for operation in ("analysis_work_descriptor", "analysis_work_cross_links"):
            cypher = READ_OPERATIONS[operation].upper()
            self.assertIn("LIMIT ", cypher)
            for forbidden in ("CREATE ", "MERGE ", "DELETE ", "SET ",
                              "CALL ", "APOC.", "LOAD CSV"):
                self.assertNotIn(forbidden, cypher)
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("/v1/analysis/works/compare", response.json()["paths"])
        self.assertIn("WorkComparison", response.json()["components"]["schemas"])


if __name__ == "__main__":
    unittest.main()
