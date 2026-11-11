"""v0.9.9 directed, bounded evidence-audit pagination and denial tests."""
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
from services.research_api.work_link_audit import (
    MAX_AUDIT_PAGE, audit_work_link_page,
)
from tests.test_work_comparison import (
    LEFT, RIGHT, P1, P2, FakeStore, edge,
)


class AuditStore(FakeStore):
    def __init__(self):
        super().__init__()
        self.forward = [
            edge("audit-a", link_status="approved", evidence_status="approved"),
            edge("audit-b", link_status="disputed", evidence_status="unreviewed"),
            edge("audit-c", link_status="unreviewed", evidence_status="unreviewed"),
            edge("audit-d", link_status="rejected", evidence_status="approved"),
        ]
        self.reverse = [
            edge("audit-reverse", source_work=RIGHT, target_work=LEFT,
                 source_passage=P2, target_passage=P1),
        ]
        self.overridden = None

    def query(self, name, params):
        if name != "analysis_work_cross_link_page":
            return super().query(name, params)
        self.calls.append((name, deepcopy(params)))
        if self.overridden is not None:
            return deepcopy(self.overridden)
        source = params["source_work_id"]
        data = self.forward if source == LEFT else self.reverse
        sorted_rows = sorted(data, key=lambda x: x["edge_id"])
        return [
            deepcopy(item) for item in sorted_rows
            if item["edge_id"] > params["after_edge_id"]
        ][:params["fetch_limit"]]


class AuditLinkTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        p = Path(temp.name) / "auth-token"
        bootstrap_token(p)
        self.headers = {"Authorization": "Bearer " + load_token(p)}
        self.store = AuditStore()
        self.client = TestClient(create_app(backend=self.store, token_path=p))

    def get(self, **other):
        params = {
            "source_work_id": LEFT, "target_work_id": RIGHT, "limit": 2,
        }
        params.update(other)
        return self.client.get("/v1/analysis/works/links/audit",
                               params=params, headers=self.headers)

    def test_page_chain_preserves_evidence_and_cursor_order(self):
        seen = []
        cursor = None
        for page_number in range(2):
            p = self.get(**({"cursor": cursor} if cursor else {}))
            self.assertEqual(p.status_code, 200, p.text)
            body = p.json()
            self.assertEqual(body["schema_version"], "0.9.9")
            self.assertEqual(body["source_work_id"], LEFT)
            self.assertEqual(body["target_work_id"], RIGHT)
            self.assertEqual(body["observed_window_denominator"], 2)
            self.assertTrue(body["sampled_window_only"])
            self.assertFalse(body["snapshot_consistency_verified"])
            self.assertFalse(body["source_rights_verified"])
            self.assertFalse(body["historical_influence_proven"])
            self.assertEqual(body["research_release_status"], "HOLD")
            self.assertEqual(body["has_more"], page_number == 0)
            if page_number:
                self.assertIsNone(body["next_cursor"])
            else:
                self.assertEqual(body["next_cursor"],
                                 body["links"][-1]["edge_id"])
            for link in body["links"]:
                self.assertEqual(link["source_work_id"], LEFT)
                self.assertEqual(link["target_work_id"], RIGHT)
                self.assertTrue(link["evidence_id"].startswith("evidence:"))
                seen.append(link["edge_id"])
            cursor = body["next_cursor"]
        self.assertEqual(seen, sorted(seen))
        self.assertEqual(len(seen), 4)
        self.assertEqual(len(set(seen)), 4)

    def test_status_counts_only_for_included_page(self):
        records = sorted(self.store.forward, key=lambda x: x["edge_id"])
        values = [
            (x["edge_review_status"], x["evidence_review_status"])
            for x in records[:2]
        ]
        data = self.get().json()
        approved = sum(a == b == "approved" for a,b in values)
        contested = sum(a in ("rejected", "disputed") or
                        b in ("rejected", "disputed") for a,b in values)
        self.assertEqual(data["joint_approved_status_links"], approved)
        self.assertEqual(data["contested_status_links"], contested)
        self.assertEqual(data["pending_status_links"], 2 - approved - contested)
        self.assertEqual(len(data["links"]), 2)
        self.assertEqual(self.store.calls[2][1]["fetch_limit"], 3)

    def test_empty_and_reverse_direction_have_no_next_cursor(self):
        self.store.forward = []
        zero = self.get().json()
        self.assertEqual(zero["links"], [])
        self.assertEqual(zero["observed_window_denominator"], 0)
        self.assertIsNone(zero["next_cursor"])
        self.assertFalse(zero["has_more"])
        backward = self.get(source_work_id=RIGHT,
                            target_work_id=LEFT).json()
        self.assertEqual(len(backward["links"]), 1)
        self.assertEqual(backward["links"][0]["source_work_id"], RIGHT)
        self.assertEqual(backward["links"][0]["target_work_id"], LEFT)

    def test_limits_and_cursor_must_be_canonical(self):
        bad_requests = [
            {"source_work_id": "bad"},
            {"target_work_id": P1},
            {"target_work_id": LEFT},
            {"limit": 0},
            {"limit": 21},
            {"cursor": ""},
            {"cursor": "edge:bad"},
            {"cursor": P2},
        ]
        for request in bad_requests:
            with self.subTest(request=request):
                self.store.calls.clear()
                response = self.get(**request)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(self.store.calls, [])
        self.assertEqual(MAX_AUDIT_PAGE, 20)

    def test_duplicate_or_unsupported_query_keys_and_auth_denied(self):
        raw = ("/v1/analysis/works/links/audit?source_work_id=" + LEFT +
               "&target_work_id=" + RIGHT)
        self.store.calls.clear()
        self.assertEqual(self.client.get(raw).status_code, 401)
        for suffix in ("&rights=approved", "&limit=1&limit=2",
                       "&source_work_id=" + LEFT):
            with self.subTest(suffix=suffix):
                response = self.client.get(raw + suffix,
                                           headers=self.headers)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(self.store.calls, [])

    def test_missing_work_returns_404_without_link_query(self):
        del self.store.works[RIGHT]
        response = self.get()
        self.assertEqual(response.status_code, 404)
        self.assertEqual([x[0] for x in self.store.calls],
                         ["analysis_work_descriptor",
                          "analysis_work_descriptor"])

    def test_bad_link_projection_or_scope_returns_safe_503(self):
        row = deepcopy(self.store.forward[0])
        variants = [
            {"source_work_id": RIGHT},
            {"target_work_id": LEFT},
            {"edge_id": P1},
            {"evidence_id": "UNLICENSED"},
            {"source_passage_id": P2, "target_passage_id": P2},
            {"edge_review_status": "auto-approved"},
            {"evidence_review_status": ["approved"]},
            {"source_ref": "source\nunsafe"},
            {"private_text": "UNLICENSED"},
        ]
        for delta in variants:
            with self.subTest(delta=str(delta)[:45]):
                self.store.overridden = [{**row, **delta}]
                r = self.get()
                self.assertEqual(r.status_code, 503, r.text)
                self.assertNotIn("UNLICENSED", r.text)

    def test_reject_lookahead_duplicate_evidence_and_nonmonotonic_edges(self):
        rows = sorted(self.store.forward, key=lambda x: x["edge_id"])
        first,second = rows[:2]
        pairs = [
            [deepcopy(first), deepcopy(first)],
            [deepcopy(second), deepcopy(first)],
            [deepcopy(first), {**deepcopy(second),
                               "evidence_id": first["evidence_id"]}],
            [deepcopy(first), deepcopy(second), deepcopy(second)],
        ]
        for pair in pairs:
            with self.subTest(rows=len(pair)):
                self.store.overridden = pair
                self.assertEqual(self.get(limit=1).status_code, 503)
        # A canonical edge keyset strictly excludes the supplied cursor.
        self.store.overridden = [deepcopy(first)]
        response = self.get(cursor=first["edge_id"])
        self.assertEqual(response.status_code, 503)

    def test_oversize_backend_and_wrong_container_refused(self):
        self.store.overridden = [
            deepcopy(self.store.forward[0]) for _ in range(22)
        ]
        self.assertEqual(self.get(limit=20).status_code, 503)
        self.store.overridden = {"rows": []}
        self.assertEqual(self.get().status_code, 503)

    def test_cursor_keyset_and_read_only_query_contract(self):
        stmt = READ_OPERATIONS["analysis_work_cross_link_page"]
        self.assertIn("USING INDEX a:Passage(work_id)", stmt)
        self.assertIn("MATCH (a)-[r:SOURCE_LINK]->(b:Passage)", stmt)
        self.assertIn("coalesce(b.work_id, '') = $target_work_id", stmt)
        self.assertIn("r.id > $after_edge_id", stmt)
        self.assertIn("MATCH (ev:Evidence {id:r.evidence_id})", stmt)
        self.assertIn("ORDER BY edge_id", stmt)
        self.assertIn("LIMIT $fetch_limit", stmt)
        # Exactly one fixed, correlated *read-only* CALL subquery is
        # allowed to prevent the planner from rescanning global links.
        # All other CALL/procedure forms and writes remain forbidden.
        self.assertIn("WITH a\nCALL (a) {", stmt)
        self.assertIn("RETURN r, b\n}", stmt)
        self.assertEqual(stmt.upper().count("CALL (A) {"), 1)
        internal_read = stmt.upper().replace("CALL (A) {", "")
        for forbidden in ("CREATE ", "DELETE ", "MERGE ", "LOAD CSV",
                          "CALL ", "APOC."):
            self.assertNotIn(forbidden, internal_read)
        openapi = self.client.get("/openapi.json").json()
        self.assertIn("/v1/analysis/works/links/audit", openapi["paths"])
        self.assertIn("WorkLinkAuditPage", openapi["components"]["schemas"])

    def test_incident_frequency_anchors_canonical_passage_index(self):
        # v0.9.9 also repairs a previously unanchored incident-frequency
        # plan found by the existing v0.9.6 synthetic dbHits regression gate.
        cypher = READ_OPERATIONS["analysis_frequency_window"]
        self.assertIn("MATCH (p:Passage {id:$passage_id})", cypher)
        self.assertIn("USING INDEX p:Passage(id)", cypher)
        self.assertIn("WITH p\nCALL (p) {", cypher)
        self.assertIn("MATCH (p)-[r:SOURCE_LINK]-(q:Passage)", cypher)
        self.assertIn("RETURN r\n}", cypher)
        self.assertIn("MATCH (ev:Evidence {id:r.evidence_id})", cypher)
        self.assertIn("ORDER BY edge_id", cypher)
        self.assertIn("LIMIT $fetch_limit", cypher)

    def test_direct_calls_require_bounded_inputs(self):
        for opts in (
            {"source_work_id": LEFT, "target_work_id": LEFT},
            {"source_work_id": LEFT, "target_work_id": RIGHT, "limit": True},
            {"source_work_id": LEFT, "target_work_id": RIGHT, "limit": 100},
            {"source_work_id": LEFT, "target_work_id": RIGHT,
             "after_edge_id": stable_id("work", "wrong-cursor")},
        ):
            with self.subTest(options=opts):
                self.store.calls.clear()
                with self.assertRaises(ValueError):
                    audit_work_link_page(self.store, **opts)
                self.assertEqual(self.store.calls, [])

    def test_lookahead_drives_next_cursor_only_when_more_rows(self):
        response = self.get(limit=1)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["has_more"])
        self.assertEqual(body["observed_window_denominator"], 1)
        self.assertEqual(body["next_cursor"], body["links"][0]["edge_id"])
        self.assertFalse(body["snapshot_consistency_verified"])


if __name__ == "__main__":
    unittest.main()
