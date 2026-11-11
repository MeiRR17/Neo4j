"""Fast deterministic API security, contracts and Cypher safelist tests."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from research_graph.ontology import stable_id
from services.research_api.app import create_app
from services.research_api.config import bootstrap_token, load_token
from services.research_api.db import DatabaseUnavailable, ReadOnlyQueryClient
from services.research_api.queries import READ_OPERATIONS


WID = stable_id("work", "fixture", "research-api-work")
PID = stable_id("passage", "fixture", "research-api-passage")
EID = stable_id("edge", "fixture", "research-api-edge")


class FakeStore:
    def __init__(self):
        self.calls = []
        self.fail = False

    def query(self, name: str, params: dict | None = None) -> list[dict]:
        self.calls.append((name, params or {}))
        if self.fail:
            raise DatabaseUnavailable("private Neo4j endpoint details must not leak")
        if name == "ready":
            from scripts.migrate import load_migrations
            return [{"id": m.id, "checksum": m.checksum} for m in load_migrations()]
        if name == "works":
            if params["cursor"]:
                return []
            return [
                {"id": WID, "title": "Fixture Research Work",
                 "provider_ref": "fixture", "provider": "fixture"},
            ]
        if name == "work":
            return [{"id": WID, "title": "Fixture Research Work",
                     "provider_ref": "fixture", "provider": "fixture",
                     "edition_count": 1}] if params["id"] == WID else []
        if name == "passage":
            return [{"id": PID, "source_ref": "Fixture Multiword Work 1:1",
                     "work_id": WID, "edition_id": None,
                     "version_id": None, "rights_tag": "UNREVIEWED"}]
        if name == "data_status":
            return [{"works": 1, "passages": 0, "evidence_records": 0, "editions": 0}]
        if name == "neighborhood_1":
            return [{"nodes": [{"id": WID, "label": "Work", "title": "Fixture"}],
                     "edges": []}]
        return []


class ApiContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "research_api_token.txt"
        bootstrap_token(self.path)
        self.store = FakeStore()
        self.client = TestClient(create_app(backend=self.store, token_path=self.path))
        self.auth = {"Authorization": "Bearer " + load_token(self.path)}

    def test_liveness_is_process_only(self):
        r = self.client.get("/health/live")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "alive")
        self.assertTrue(r.headers.get("x-request-id"))
        self.assertEqual(r.headers.get("cache-control"), "no-store")

    def test_missing_and_wrong_auth_fail_closed(self):
        before = len(self.store.calls)
        self.assertEqual(self.client.get("/v1/works").status_code, 401)
        response = self.client.get("/v1/works", headers={"Authorization": "Bearer wrong"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(before, len(self.store.calls))
        self.assertEqual(response.json()["error"]["code"], "FORBIDDEN")

    def test_good_auth_returns_typed_work_and_pagination(self):
        page = self.client.get("/v1/works?limit=1", headers=self.auth)
        self.assertEqual(page.status_code, 200, page.text)
        self.assertEqual(page.json()["items"][0]["id"], WID)
        self.assertEqual(page.json()["corpus_status"], "unreviewed_metadata_only")
        detail = self.client.get(f"/v1/works/{WID}", headers=self.auth)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["edition_count"], 1)

    def test_path_id_mismatch_is_400(self):
        r = self.client.get(f"/v1/works/{PID}", headers=self.auth)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["code"], "BAD_REQUEST")

    def test_missing_entity_is_explicit_404(self):
        unknown = stable_id("work", "fixture", "unknown")
        r = self.client.get(f"/v1/works/{unknown}", headers=self.auth)
        self.assertEqual(r.status_code, 404)

    def test_cursors_and_limits_are_bounded(self):
        for url in [
            "/v1/works?limit=51",
            "/v1/works?limit=0",
            "/v1/works?cursor=not-a-canonical-id",
            f"/v1/works?cursor={PID}",
            "/v1/works?language=cypher",
            "/v1/links?claim_kind=FAKE_INFLUENCE",
        ]:
            with self.subTest(url=url):
                self.assertIn(self.client.get(url, headers=self.auth).status_code, (400, 422))

    def test_bounded_neighborhood_and_allowlisted_edge_types(self):
        response = self.client.get(
            f"/v1/graph/neighborhood?entity_id={WID}&depth=1", headers=self.auth
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["paths"][0]["nodes"][0]["id"], WID)
        for url in [
            f"/v1/graph/neighborhood?entity_id={WID}&depth=3",
            f"/v1/graph/neighborhood?entity_id={WID}&edge_types=DELETE",
            f"/v1/graph/neighborhood?entity_id={WID}&edge_types=SOURCE_LINK,SOURCE_LINK",
        ]:
            self.assertEqual(self.client.get(url, headers=self.auth).status_code, 422)

    def test_no_arbitrary_cypher_post_or_query_parameter(self):
        for url in ["/v1/cypher", "/v1/query", "/v1/execute"]:
            self.assertEqual(self.client.post(url, json={"cypher": "MATCH (n) DETACH DELETE n"},
                                              headers=self.auth).status_code, 404)
        r = self.client.get("/v1/works", params={"query":"CREATE (n) DELETE n"},
                            headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.store.calls[-1][0], "works")
        self.assertEqual(self.store.calls[-1][1]["query"], "CREATE (n) DELETE n")

    def test_readiness_requires_actual_schema(self):
        r = self.client.get("/health/ready")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["research_corpus_status"], "human_review_pending")
        self.store.fail = True
        r = self.client.get("/health/ready")
        self.assertEqual(r.status_code, 503)
        self.assertNotIn("private Neo4j endpoint details", r.text)

    def test_passage_response_never_exposes_unlicensed_text(self):
        r = self.client.get(f"/v1/passages/{PID}", headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(r.json()["excerpt"])
        self.assertNotIn("text", r.json())

    def test_status_does_not_fabricate_approved_corpus(self):
        r = self.client.get("/v1/data/status", headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["human_quality_release_approved"])
        self.assertFalse(r.json()["texts_available"])

    def test_openapi_exposes_bearer_auth_and_expected_paths(self):
        r = self.client.get("/openapi.json")
        self.assertEqual(r.status_code, 200)
        paths = r.json()["paths"]
        for endpoint in ["/v1/works", "/v1/links", "/v1/graph/neighborhood",
                         "/health/live", "/health/ready"]:
            self.assertIn(endpoint, paths)
        self.assertIn("HTTPBearer", r.json()["components"]["securitySchemes"])


class BackendPolicyTests(unittest.TestCase):
    def test_operation_names_not_user_supplied_cypher(self):
        client = ReadOnlyQueryClient()
        for input_text in ["MATCH (n) RETURN n", "DELETE", "works; CREATE (n)"]:
            with self.subTest(value=input_text), self.assertRaises(ValueError):
                client.query(input_text)

    def test_all_allowlisted_statements_are_read_only(self):
        self.assertGreaterEqual(len(READ_OPERATIONS), 12)
        for name, statement in READ_OPERATIONS.items():
            upper = statement.upper()
            # The two fixed Work-link templates contain exactly one
            # correlated read-only subquery. All other CALL forms remain
            # prohibited across the complete allowlisted registry.
            if name in ("analysis_work_cross_links",
                        "analysis_work_cross_link_page"):
                self.assertIn("WITH A\nCALL (A) {", upper)
                self.assertIn("RETURN R, B\n}", upper)
                self.assertEqual(upper.count("CALL (A) {"), 1)
                upper = upper.replace("CALL (A) {", "")
            elif name == "analysis_frequency_window":
                self.assertIn("WITH P\nCALL (P) {", upper)
                self.assertIn("RETURN R\n}", upper)
                self.assertEqual(upper.count("CALL (P) {"), 1)
                upper = upper.replace("CALL (P) {", "")
            for forbidden in ["DELETE ", "MERGE ", "CREATE ", "SET ", "LOAD CSV",
                              "APOC.", "CALL ", "DROP ", "REMOVE "]:
                with self.subTest(name=name, forbidden=forbidden):
                    self.assertNotIn(forbidden, upper)

    def test_token_bootstrap_idempotent_and_rejects_weak_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "token"
            bootstrap_token(path)
            first = load_token(path)
            bootstrap_token(path)
            self.assertEqual(first, load_token(path))
            path.write_text("weak-token\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_token(path)


if __name__ == "__main__":
    unittest.main()
