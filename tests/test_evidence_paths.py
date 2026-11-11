"""Synthetic v0.9.1 bounded evidence-path tests: service, HTTP, security."""
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
from services.research_api.evidence_paths import evidence_path_page
from services.research_api.queries import READ_OPERATIONS

A = stable_id("passage", "synthetic-path", "A")
B = stable_id("passage", "synthetic-path", "B")
C = stable_id("passage", "synthetic-path", "C")
D = stable_id("passage", "synthetic-path", "D")
E1 = stable_id("evidence", "synthetic-path", "E1")
E2 = stable_id("evidence", "synthetic-path", "E2")
R1 = stable_id("edge", "synthetic-path", "R1")
R2 = stable_id("edge", "synthetic-path", "R2")


def edge(source, target, evidence, relation):
    return {
        "edge_id": relation, "from_passage_id": source,
        "to_passage_id": target, "evidence_id": evidence,
        "claim_kind": "OBSERVED_SOURCE_LINK",
        "edge_review_status": "unreviewed",
        "evidence_review_status": "unreviewed",
        "source_ref": "Synthetic Multiword Work 1:1",
        "version_id": "synthetic-version", "rights_tag": "TEST_UNREVIEWED",
    }


class MemoryStore:
    def __init__(self):
        self.calls = []
        self.direct = [{
            "passage_ids": [A, C], "edges": [edge(A, C, E1, R1)],
            "hop_count": 1,
        }]
        self.two_hop = [{
            "passage_ids": [A, B, C],
            "edges": [edge(A, B, E1, R1), edge(B, C, E2, R2)],
            "hop_count": 2,
        }]

    def query(self, operation, params):
        self.calls.append((operation, params))
        if operation == "analysis_path_direct":
            return deepcopy(self.direct)
        if operation == "analysis_path_two_hop":
            return deepcopy(self.two_hop)
        return []


class EvidencePaths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        token = Path(self.tmp.name) / "api-token"
        bootstrap_token(token)
        self.auth = {"Authorization": "Bearer " + load_token(token)}
        self.store = MemoryStore()
        self.client = TestClient(create_app(backend=self.store, token_path=token))

    def request(self, **params):
        values = {"source_id": A, "target_id": C}
        values.update(params)
        return self.client.get("/v1/graph/evidence-path", params=values,
                               headers=self.auth)

    def test_direct_path_wins_and_retains_evidence(self):
        r = self.request()
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertEqual(data["observed_shortest_hops"], 1)
        self.assertEqual(data["paths"][0]["passage_ids"], [A, C])
        self.assertEqual(data["paths"][0]["edges"][0]["evidence_id"], E1)
        self.assertEqual(data["paths"][0]["edges"][0]["source_ref"],
                         "Synthetic Multiword Work 1:1")
        self.assertEqual([x[0] for x in self.store.calls], ["analysis_path_direct"])
        self.assertFalse(data["historical_influence_proven"])
        self.assertFalse(data["source_rights_verified"])
        self.assertFalse(data["whole_graph_shortest_path_proven"])
        self.assertFalse(data["graph_snapshot_isolation_verified"])
        self.assertEqual(data["research_release_status"], "HOLD")

    def test_two_hop_path_has_both_independent_trails(self):
        self.store.direct = []
        r = self.request(limit=1)
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertEqual(data["observed_shortest_hops"], 2)
        self.assertEqual(data["paths"][0]["passage_ids"], [A, B, C])
        self.assertEqual([e["evidence_id"] for e in data["paths"][0]["edges"]],
                         [E1, E2])
        self.assertEqual([x[0] for x in self.store.calls],
                         ["analysis_path_direct", "analysis_path_two_hop"])
        self.assertEqual(self.store.calls[-1][1]["fetch_limit"], 2)

    def test_bounded_lookahead_and_empty_result(self):
        self.store.direct.append({
            "passage_ids": [A, C],
            "edges": [edge(A, C, E2, R2)], "hop_count": 1,
        })
        r = self.request(limit=1)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["has_more"])
        self.assertEqual(len(r.json()["paths"]), 1)
        self.store.direct = []
        self.store.two_hop = []
        r = self.request()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["paths"], [])
        self.assertIsNone(r.json()["observed_shortest_hops"])
        self.assertFalse(r.json()["has_more"])

    def test_missing_auth_and_bad_params_do_not_query(self):
        n = len(self.store.calls)
        self.assertEqual(self.client.get("/v1/graph/evidence-path",
                         params={"source_id": A, "target_id": C}).status_code, 401)
        self.assertEqual(len(self.store.calls), n)
        for route in [
            "/v1/graph/evidence-path?source_id=bad&target_id=" + C,
            "/v1/graph/evidence-path?source_id=" + A + "&target_id=" + A,
            "/v1/graph/evidence-path?source_id=" + A + "&target_id=" + E1,
            "/v1/graph/evidence-path?source_id=" + A + "&target_id=" + C + "&limit=11",
            "/v1/graph/evidence-path?source_id=" + A + "&target_id=" + C + "&depth=999",
            "/v1/graph/evidence-path?source_id=" + A + "&target_id=" + C + "&source_id=" + A,
        ]:
            with self.subTest(route=route):
                n = len(self.store.calls)
                r = self.client.get(route, headers=self.auth)
                self.assertEqual(r.status_code, 422, r.text)
                self.assertEqual(len(self.store.calls), n)

    def test_mismatched_path_direction_or_provenance_fail_closed(self):
        edits = [
            lambda row: row.update(hop_count=2),
            lambda row: row.update(passage_ids=[B, C]),
            lambda row: row["edges"][0].update(source_ref="INJECT\nTEXT"),
            lambda row: row["edges"][0].update(claim_kind="HUMAN_INTERPRETATION"),
            lambda row: row["edges"][0].update(edge_review_status="rejected"),
            lambda row: row["edges"][0].update(evidence_review_status="disputed"),
            lambda row: row["edges"][0].update(from_passage_id=D),
            lambda row: row["edges"][0].update(source_text="UNLICENSED"),
        ]
        for change in edits:
            with self.subTest(change=str(change)):
                self.store.direct = MemoryStore().direct
                change(self.store.direct[0])
                response = self.request()
                self.assertEqual(response.status_code, 503, response.text)
                self.assertNotIn("UNLICENSED", response.text)

    def test_no_duplicate_support_self_cycle_or_window_inflation(self):
        self.store.direct = []
        self.store.two_hop[0]["edges"][1]["evidence_id"] = E1
        with self.assertRaises(DatabaseUnavailable):
            evidence_path_page(self.store, source_id=A, target_id=C)
        self.store = MemoryStore()
        self.store.direct *= 2
        with self.assertRaises(DatabaseUnavailable):
            evidence_path_page(self.store, source_id=A, target_id=C, limit=2)
        self.store = MemoryStore()
        self.store.direct *= 12
        with self.assertRaises(DatabaseUnavailable):
            evidence_path_page(self.store, source_id=A, target_id=C, limit=10)

    def test_static_queries_are_read_only_and_openapi_is_typed(self):
        for name in ("analysis_path_direct", "analysis_path_two_hop"):
            statement = READ_OPERATIONS[name].upper()
            self.assertIn("LIMIT $FETCH_LIMIT", statement)
            self.assertIn("EVIDENCE", statement)
            for forbidden in ("MERGE ", "DELETE ", "CREATE ", "SET ", "CALL ",
                              "DROP ", "LOAD CSV", "APOC."):
                with self.subTest(name=name, forbidden=forbidden):
                    self.assertNotIn(forbidden, statement)
        schema = self.client.get("/openapi.json").json()
        self.assertIn("/v1/graph/evidence-path", schema["paths"])
        self.assertIn("EvidencePathPage", schema["components"]["schemas"])


if __name__ == "__main__":
    unittest.main()
