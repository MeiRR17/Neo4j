"""v0.9.4 deterministic metadata receipt: tamper, replay and bounded fixture."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from services.research_api.app import create_app
from services.research_api.config import bootstrap_token, load_token
from services.research_api.db import DatabaseUnavailable
from services.research_api.comparison_receipts import (
    CANONICALIZATION, canonical_bytes, comparison_receipt,
    query_templates_sha256,
)
from services.research_api.queries import READ_OPERATIONS
from tests.test_work_comparison import LEFT, RIGHT, FakeStore, edge


class ComparisonReceipts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        token = Path(self.tmp.name) / "token"
        bootstrap_token(token)
        self.auth = {"Authorization": "Bearer " + load_token(token)}
        self.store = FakeStore()
        self.client = TestClient(create_app(backend=self.store, token_path=token))
        self.params = {
            "left_work_id": LEFT, "right_work_id": RIGHT, "limit": 2,
        }

    def get(self):
        return self.client.get("/v1/analysis/works/compare/receipt",
                               params=self.params, headers=self.auth)

    def test_receipt_hashes_exact_typed_bounded_observation(self):
        result = self.get()
        self.assertEqual(result.status_code, 200, result.text)
        data = result.json()
        self.assertEqual(data["schema_version"], "0.9.4")
        self.assertEqual(data["canonicalization"], CANONICALIZATION)
        self.assertEqual(data["comparison"]["schema_version"], "0.9.3")
        self.assertEqual(data["observed_link_count"], 3)
        self.assertFalse(data["sample_window_truncated"])
        self.assertEqual(data["observation_sha256"],
                         sha256(canonical_bytes(data["comparison"])).hexdigest())
        self.assertEqual(data["fixed_query_templates_sha256"],
                         query_templates_sha256())
        self.assertFalse(data["comparison_snapshot_verified"])
        self.assertFalse(data["verified_corpus_coverage"])
        self.assertFalse(data["receipt_digitally_signed"])
        self.assertFalse(data["source_rights_verified"])
        self.assertFalse(data["historical_influence_proven"])
        self.assertEqual(data["research_release_status"], "HOLD")

    def test_repeatability_and_different_graph_metadata_change_digest(self):
        first = self.get().json()
        second = self.get().json()
        self.assertEqual(first["observation_sha256"],
                         second["observation_sha256"])
        self.store.forward[0]["evidence_review_status"] = "rejected"
        third = self.get().json()
        self.assertNotEqual(first["observation_sha256"],
                            third["observation_sha256"])
        self.assertEqual(third["fixed_query_templates_sha256"],
                         first["fixed_query_templates_sha256"])

    def test_key_insertion_order_does_not_change_canonical_json(self):
        first = self.get().json()
        self.store.works[LEFT] = dict(reversed(
            list(self.store.works[LEFT].items())))
        self.store.forward[0] = dict(reversed(
            list(self.store.forward[0].items())))
        second = self.get().json()
        self.assertEqual(first["observation_sha256"],
                         second["observation_sha256"])
        self.assertEqual(first["comparison"], second["comparison"])

    def test_window_truncation_included_in_receipt(self):
        self.params["limit"] = 1
        data = self.get().json()
        self.assertTrue(data["comparison"]["left_to_right"]["has_more"])
        self.assertTrue(data["sample_window_truncated"])
        self.assertEqual(data["observed_link_count"], 2)
        self.assertFalse(data["verified_corpus_coverage"])

    def test_template_digest_reacts_to_fixed_cypher_changes(self):
        original = query_templates_sha256()
        with patch.dict(READ_OPERATIONS, {
            "analysis_work_descriptor":
            READ_OPERATIONS["analysis_work_descriptor"] + " "
        }):
            self.assertNotEqual(original, query_templates_sha256())
        self.assertEqual(original, query_templates_sha256())
        self.assertIn("ORDER BY p.id", READ_OPERATIONS["analysis_work_descriptor"])

    def test_twenty_distinct_synthetic_cases_are_repeatable(self):
        signatures = set()
        states = ("approved", "unreviewed", "disputed", "rejected")
        for number in range(20):
            store = FakeStore()
            store.forward = [edge("case-" + str(number),
                                  link_status=states[number % 4],
                                  evidence_status=states[(number + 1) % 4])]
            store.reverse = []
            first = comparison_receipt(
                store, left_work_id=LEFT, right_work_id=RIGHT, limit=3)
            second = comparison_receipt(
                store, left_work_id=LEFT, right_work_id=RIGHT, limit=3)
            self.assertEqual(first["observation_sha256"],
                             second["observation_sha256"])
            signatures.add(first["observation_sha256"])
        self.assertEqual(len(signatures), 20)

    def test_bad_input_never_queries_backend(self):
        unauth = self.client.get(
            "/v1/analysis/works/compare/receipt", params=self.params)
        self.assertEqual(unauth.status_code, 401)
        self.assertEqual(self.store.calls, [])
        bad_urls = [
            "/v1/analysis/works/compare/receipt?left_work_id=BAD&right_work_id=" + RIGHT,
            "/v1/analysis/works/compare/receipt?left_work_id=" + LEFT +
            "&right_work_id=" + LEFT,
            "/v1/analysis/works/compare/receipt?left_work_id=" + LEFT +
            "&right_work_id=" + RIGHT + "&limit=11",
            "/v1/analysis/works/compare/receipt?left_work_id=" + LEFT +
            "&right_work_id=" + RIGHT + "&limit=1&limit=2",
            "/v1/analysis/works/compare/receipt?left_work_id=" + LEFT +
            "&right_work_id=" + RIGHT + "&approved=true",
        ]
        for url in bad_urls:
            with self.subTest(url=url):
                before = len(self.store.calls)
                response = self.client.get(url, headers=self.auth)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(len(self.store.calls), before)

    def test_unsafe_graph_rows_cannot_be_fingerprinted_as_valid(self):
        self.store.forward[0]["private_source_text"] = "HIDDEN"
        response = self.get()
        self.assertEqual(response.status_code, 503, response.text)
        self.assertNotIn("HIDDEN", response.text)
        with self.assertRaises(DatabaseUnavailable):
            canonical_bytes({"invalid": float("nan")})

    def test_missing_work_returns_404(self):
        self.store.works.pop(RIGHT)
        response = self.get()
        self.assertEqual(response.status_code, 404)
        self.assertEqual([call[0] for call in self.store.calls],
                         ["analysis_work_descriptor", "analysis_work_descriptor"])


if __name__ == "__main__":
    unittest.main()
