"""v0.9.10 HMAC checkpoint, changed prior window and client denial cases."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from research_graph.ontology import stable_id
from services.research_api.app import create_app
from services.research_api.audit_checkpoint import (
    AuditWindowDrift, TOKEN_TTL_SECONDS, checked_audit_page,
)
from services.research_api.config import bootstrap_token, load_token
from services.research_api.queries import READ_OPERATIONS
from tests.test_work_link_audit_v099 import AuditStore
from tests.test_work_comparison import LEFT, RIGHT, edge


class CheckedAuditTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        key = Path(tmp.name) / "bearer"
        bootstrap_token(key)
        self.secret = load_token(key)
        self.headers = {"Authorization": "Bearer " + self.secret}
        self.store = AuditStore()
        self.client = TestClient(create_app(backend=self.store, token_path=key))

    def call(self, **params):
        query = {"source_work_id": LEFT, "target_work_id": RIGHT, "limit": 2}
        query.update(params)
        return self.client.get(
            "/v1/analysis/works/links/audit/checked",
            params=query, headers=self.headers,
        )

    def test_two_pages_checked_with_signed_window_witness(self):
        first = self.call()
        self.assertEqual(first.status_code, 200, first.text)
        obj = first.json()
        self.assertEqual(obj["schema_version"], "0.9.10")
        self.assertFalse(obj["previous_page_reverified"])
        self.assertTrue(obj["page"]["has_more"])
        self.assertTrue(obj["page"]["sampled_window_only"])
        self.assertEqual(obj["drift_detection_scope"],
                         "immediately_previous_bounded_page_only")
        self.assertFalse(obj["snapshot_consistency_verified"])
        self.assertFalse(obj["entire_audit_chain_reverified"])
        self.assertEqual(obj["research_release_status"], "HOLD")
        checkpoint = obj["checkpoint_token"]
        self.assertIsInstance(checkpoint, str)
        self.assertLessEqual(len(checkpoint), 1400)
        self.assertNotIn("Synthetic Work Alpha 1:1", checkpoint)
        self.assertNotIn("source_ref", checkpoint)
        second = self.call(checkpoint=checkpoint)
        self.assertEqual(second.status_code, 200, second.text)
        continued = second.json()
        self.assertTrue(continued["previous_page_reverified"])
        self.assertFalse(continued["page"]["has_more"])
        self.assertIsNone(continued["checkpoint_token"])
        self.assertEqual(len(continued["page"]["links"]), 2)
        edges = [x["edge_id"] for x in obj["page"]["links"]]
        edges += [x["edge_id"] for x in continued["page"]["links"]]
        self.assertEqual(edges, sorted(edges))
        self.assertEqual(len(set(edges)), 4)

    def test_changing_prior_review_metadata_fails_closed_409(self):
        first = self.call().json()
        checkpoint = first["checkpoint_token"]
        prior = {x["edge_id"] for x in first["page"]["links"]}
        index = next(i for i, e in enumerate(self.store.forward)
                     if e["edge_id"] in prior)
        self.store.forward[index]["evidence_review_status"] = "approved" if (
            self.store.forward[index]["evidence_review_status"] != "approved"
        ) else "unreviewed"
        got = self.call(checkpoint=checkpoint)
        self.assertEqual(got.status_code, 409, got.text)
        self.assertEqual(got.json()["error"]["code"], "AUDIT_DRIFT")
        self.assertNotIn("Synthetic Work", got.text)

    def test_deletion_from_prior_page_detected_before_advance(self):
        first = self.call().json()
        prior = first["page"]["links"][0]["edge_id"]
        self.store.forward = [x for x in self.store.forward if x["edge_id"] != prior]
        got = self.call(checkpoint=first["checkpoint_token"])
        self.assertEqual(got.status_code, 409)
        self.assertNotIn("source_ref", got.text)

    def test_insertion_inside_previous_window_detected(self):
        first = self.call().json()
        items = sorted(self.store.forward, key=lambda x: x["edge_id"])
        first_id, next_id = items[0]["edge_id"], items[1]["edge_id"]
        # Synthesized canonical Edge whose SHA key falls strictly between
        # the previously returned first two edge IDs.
        candidate = None
        for i in range(3000):
            row = edge(f"extra-link-{i}")
            if first_id < row["edge_id"] < next_id:
                candidate = row
                break
        self.assertIsNotNone(candidate)
        self.store.forward.append(candidate)
        got = self.call(checkpoint=first["checkpoint_token"])
        self.assertEqual(got.status_code, 409)

    def test_tampered_checkpoint_denied_without_db_calls(self):
        checkpoint = self.call().json()["checkpoint_token"]
        self.store.calls.clear()
        bad = checkpoint[:-1] + ("a" if checkpoint[-1] != "a" else "b")
        response = self.call(checkpoint=bad)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.store.calls, [])
        self.assertNotIn(self.secret, response.text)

    def test_scope_and_page_size_rebinding_fail_before_db(self):
        token = self.call().json()["checkpoint_token"]
        for params in (
            {"checkpoint": token, "source_work_id": RIGHT,
             "target_work_id": LEFT},
            {"checkpoint": token, "limit": 3},
            {"checkpoint": token, "source_work_id": stable_id(
                "work", "unrelated-work")},
            {"checkpoint": ""},
            {"checkpoint": "invalid.token"},
        ):
            with self.subTest(params=str(params)[:45]):
                self.store.calls.clear()
                res = self.call(**params)
                self.assertEqual(res.status_code, 422, res.text)
                self.assertEqual(self.store.calls, [])

    def test_expired_token_rejected_and_local_secret_rotation_invalidates(self):
        first = checked_audit_page(
            self.store, source_work_id=LEFT, target_work_id=RIGHT,
            limit=2, secret=self.secret, now=1000,
        )
        self.store.calls.clear()
        with self.assertRaises(ValueError):
            checked_audit_page(
                self.store, source_work_id=LEFT, target_work_id=RIGHT,
                limit=2, checkpoint=first["checkpoint_token"],
                secret=self.secret, now=1000 + TOKEN_TTL_SECONDS + 1,
            )
        self.assertEqual(self.store.calls, [])
        with self.assertRaises(ValueError):
            checked_audit_page(
                self.store, source_work_id=LEFT, target_work_id=RIGHT,
                limit=2, checkpoint=first["checkpoint_token"],
                secret="Z" * 45, now=1001,
            )
        self.assertEqual(self.store.calls, [])

    def test_unmodified_page_stable_but_not_snapshot_claim(self):
        first = self.call().json()
        # Change only a not-yet-visited page: prior page remains stable.
        excluded = {x["edge_id"] for x in first["page"]["links"]}
        index = next(i for i,e in enumerate(self.store.forward)
                     if e["edge_id"] not in excluded)
        self.store.forward[index]["evidence_review_status"] = "approved"
        second = self.call(checkpoint=first["checkpoint_token"])
        self.assertEqual(second.status_code, 200)
        data = second.json()
        self.assertTrue(data["previous_page_reverified"])
        self.assertFalse(data["snapshot_consistency_verified"])
        self.assertFalse(data["entire_audit_chain_reverified"])
        self.assertFalse(data["source_rights_verified"])

    def test_missing_work_remains_404_and_invalid_arguments_422(self):
        del self.store.works[RIGHT]
        response = self.call()
        self.assertEqual(response.status_code, 404)
        self.store.calls.clear()
        self.assertEqual(self.call(limit=21).status_code, 422)
        self.assertEqual(self.store.calls, [])

    def test_auth_extra_and_duplicate_query_keys_rejected(self):
        target = ("/v1/analysis/works/links/audit/checked?"
                  "source_work_id=" + LEFT + "&target_work_id=" + RIGHT)
        self.assertEqual(self.client.get(target).status_code, 401)
        for extra in ("&limit=2&limit=2", "&approval=verified",
                      "&checkpoint=a&checkpoint=b"):
            self.store.calls.clear()
            res = self.client.get(target+extra, headers=self.headers)
            self.assertEqual(res.status_code, 422)
            self.assertEqual(self.store.calls, [])

    def test_returned_page_has_exact_legacy_evidence_projection(self):
        obj = self.call().json()
        page = obj["page"]
        self.assertEqual(len(page["links"]), 2)
        for link in page["links"]:
            self.assertEqual(set(link), {
                "edge_id", "source_work_id", "target_work_id",
                "source_passage_id", "target_passage_id", "evidence_id",
                "edge_review_status", "evidence_review_status",
                "source_ref", "target_ref", "evidence_source_ref",
                "version_id", "rights_tag",
            })
        self.assertFalse(obj["historical_influence_proven"])
        self.assertEqual(page["research_release_status"], "HOLD")

    def test_page_size_one_witness_chains_until_exhaustion(self):
        first = self.call(limit=1).json()
        seen = [x["edge_id"] for x in first["page"]["links"]]
        token = first["checkpoint_token"]
        while token:
            next_page = self.call(limit=1, checkpoint=token)
            self.assertEqual(next_page.status_code, 200, next_page.text)
            item = next_page.json()
            self.assertTrue(item["previous_page_reverified"])
            seen += [x["edge_id"] for x in item["page"]["links"]]
            token = item["checkpoint_token"]
            self.assertLessEqual(len(seen), 4)
        self.assertEqual(seen, sorted(seen))
        self.assertEqual(len(seen), 4)

    def test_incident_frequency_expands_before_evidence_lookup(self):
        # This separation is necessary for large unrelated-Work
        # distractors; preserve the previously bounded read shape.
        stmt = READ_OPERATIONS["analysis_frequency_window"]
        self.assertIn("USING INDEX p:Passage(id)", stmt)
        self.assertIn(
            "MATCH (p)-[r:SOURCE_LINK]-(q:Passage)\nWITH r\n"
            "MATCH (ev:Evidence {id:r.evidence_id})", stmt)
        self.assertIn("ORDER BY edge_id", stmt)
        self.assertIn("LIMIT $fetch_limit", stmt)
        for keyword in ("MERGE ", "DELETE ", "CREATE ", "SET ", "APOC."):
            self.assertNotIn(keyword, stmt.upper())

    def test_openapi_route_and_typed_response_registered(self):
        schema = self.client.get("/openapi.json").json()
        self.assertIn("/v1/analysis/works/links/audit/checked", schema["paths"])
        self.assertIn("CheckedWorkLinkAuditPage", schema["components"]["schemas"])
        self.assertFalse(self.call().json()["snapshot_consistency_verified"])


if __name__ == "__main__":
    unittest.main()
