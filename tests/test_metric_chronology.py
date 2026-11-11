"""v0.9.2 synthetic-only quantitative observation and chronology tests."""
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
from services.research_api.metric_chronology import link_frequency, author_chronology
from services.research_api.queries import READ_OPERATIONS

A = stable_id("passage", "synthetic-metrics", "A")
B = stable_id("passage", "synthetic-metrics", "B")
C = stable_id("passage", "synthetic-metrics", "C")
WA = stable_id("work", "synthetic-metrics", "A")
WB = stable_id("work", "synthetic-metrics", "B")
PA = stable_id("person", "synthetic-metrics", "A")
PB = stable_id("person", "synthetic-metrics", "B")
EV = stable_id("evidence", "synthetic-metrics", "sample")


def frequency_row(index, source=A, target=B, edge_status="unreviewed",
                  evidence_status="unreviewed"):
    return {
        "edge_id": stable_id("edge", "synthetic-metrics", str(index)),
        "source_passage_id": source,
        "target_passage_id": target,
        "evidence_id": stable_id("evidence", "synthetic-metrics", str(index)),
        "edge_review_status": edge_status,
        "evidence_review_status": evidence_status,
    }


def author_row(start, end, author):
    return {"id": author, "date_from_year": start, "date_to_year": end}


class FakeQueryClient:
    def __init__(self):
        self.calls = []
        self.freq = [
            frequency_row(1, A, B, "approved", "approved"),
            frequency_row(2, C, A, "unreviewed", "approved"),
            frequency_row(3, A, C, "disputed", "approved"),
        ]
        self.chronology = [{
            "edge_id": stable_id("edge", "synthetic-metrics", "direct"),
            "evidence_id": EV,
            "source_passage_id": A, "target_passage_id": B,
            "source_work_id": WA, "target_work_id": WB,
            "source_authors": [author_row(1100, 1160, PA)],
            "target_authors": [author_row(1210, 1270, PB)],
        }]

    def query(self, operation, params=None):
        self.calls.append((operation, params))
        if operation == "analysis_frequency_window":
            return deepcopy(self.freq)
        if operation == "analysis_author_lifetimes":
            return deepcopy(self.chronology)
        return []


class MetricsChronologyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        token = Path(self.temp.name) / "token"
        bootstrap_token(token)
        self.auth = {"Authorization": "Bearer " + load_token(token)}
        self.store = FakeQueryClient()
        self.client = TestClient(create_app(backend=self.store, token_path=token))

    def test_frequency_reports_explicit_sample_denominator(self):
        response = self.client.get("/v1/analysis/metrics/link-frequency",
                                   params={"passage_id": A}, headers=self.auth)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["observed_link_denominator"], 3)
        self.assertEqual(data["outgoing_observed_links"], 2)
        self.assertEqual(data["incoming_observed_links"], 1)
        self.assertEqual(data["joint_approved_status_links"], 1)
        self.assertEqual(data["contested_status_links"], 1)
        self.assertEqual(data["pending_status_links"], 1)
        self.assertAlmostEqual(data["joint_approved_status_fraction"], 1 / 3, places=4)
        self.assertFalse(data["window_truncated"])
        self.assertFalse(data["whole_graph_centrality_verified"])
        self.assertFalse(data["historical_influence_proven"])
        self.assertEqual(data["research_release_status"], "HOLD")
        self.assertEqual(self.store.calls[-1], ("analysis_frequency_window",
                         {"passage_id": A, "fetch_limit": 51}))

    def test_empty_and_fifty_plus_lookahead_are_not_false_precision(self):
        self.store.freq = []
        data = self.client.get("/v1/analysis/metrics/link-frequency",
                               params={"passage_id": A}, headers=self.auth).json()
        self.assertEqual(data["observed_link_denominator"], 0)
        self.assertIsNone(data["joint_approved_status_fraction"])
        self.store.freq = [frequency_row(i) for i in range(51)]
        data = self.client.get("/v1/analysis/metrics/link-frequency",
                               params={"passage_id": A}, headers=self.auth).json()
        self.assertTrue(data["window_truncated"])
        self.assertEqual(data["observed_link_denominator"], 50)
        self.assertEqual(data["outgoing_observed_links"], 50)
        self.assertEqual(data["pending_status_links"], 50)
        self.assertFalse(data["whole_graph_centrality_verified"])

    def test_injected_and_duplicate_frequency_records_fail_closed(self):
        original = self.store.freq
        corruptions = [
            [dict(original[0], edge_review_status="auto_approved")],
            [dict(original[0], target_passage_id=A)],
            [dict(original[0], source_passage_id=B, target_passage_id=C)],
            [dict(original[0], edge_id="bad")],
            [dict(original[0], source_text="UNLICENSED RAW CORPUS")],
            [original[0], original[0]],
            [original[0], dict(original[1], evidence_id=original[0]["evidence_id"])],
            [frequency_row(i) for i in range(52)],
        ]
        for rows in corruptions:
            with self.subTest(rows=str(rows)[:70]):
                self.store.freq = deepcopy(rows)
                response = self.client.get("/v1/analysis/metrics/link-frequency",
                                           params={"passage_id": A},
                                           headers=self.auth)
                self.assertEqual(response.status_code, 503, response.text)
                self.assertNotIn("UNLICENSED RAW CORPUS", response.text)
        self.store.freq = original

    def test_chronology_is_lifetime_metadata_only(self):
        response = self.client.get("/v1/analysis/chronology/author-lifetimes",
                                   params={"source_id": A, "target_id": B},
                                   headers=self.auth)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["metadata_status"],
                         "author_lifetime_intervals_compared")
        self.assertEqual(data["author_lifetime_relation"],
                         "target_author_lifetime_later")
        self.assertEqual(data["source_authors"][0]["id"], PA)
        self.assertFalse(data["source_years_independently_verified"])
        self.assertFalse(data["composition_or_publication_order_verified"])
        self.assertFalse(data["historical_influence_proven"])
        self.assertEqual(data["research_release_status"], "HOLD")

    def test_chronology_missing_ambiguous_and_same_work_remain_unknown(self):
        self.store.chronology = []
        out = author_chronology(self.store, source_id=A, target_id=B)
        self.assertEqual(out["metadata_status"], "no_eligible_observed_link_or_work")
        self.assertEqual(out["author_lifetime_relation"], "unknown")
        baseline = FakeQueryClient().chronology[0]
        for edit, expected in [
            ({"source_work_id": WB}, "same_work"),
            ({"source_authors": []}, "missing_author_metadata"),
            ({"target_authors": [author_row(None, 1270, PB)]},
             "incomplete_year_metadata"),
            ({"source_authors": [author_row(1100, 1160, PA),
                                 author_row(1120, 1160, PB)]},
             "ambiguous_author_metadata"),
        ]:
            self.store.chronology = [dict(deepcopy(baseline), **edit)]
            out = author_chronology(self.store, source_id=A, target_id=B)
            self.assertEqual(out["metadata_status"], expected)
            self.assertEqual(out["author_lifetime_relation"], "unknown")

    def test_chronology_distinguishes_source_after_target_and_overlap(self):
        baseline = FakeQueryClient().chronology[0]
        self.store.chronology = [dict(deepcopy(baseline),
            source_authors=[author_row(1400, 1460, PA)])]
        self.assertEqual(author_chronology(self.store, source_id=A, target_id=B)
                         ["author_lifetime_relation"], "source_author_lifetime_later")
        self.store.chronology = [dict(deepcopy(baseline),
            source_authors=[author_row(1220, 1260, PA)])]
        self.assertEqual(author_chronology(self.store, source_id=A, target_id=B)
                         ["author_lifetime_relation"], "lifetimes_overlap")

    def test_invalid_author_years_and_untrusted_evidence_fail_closed(self):
        baseline = FakeQueryClient().chronology[0]
        for change in [
            {"edge_id": "bad"},
            {"target_passage_id": C},
            {"source_authors": "not-a-list"},
            {"target_authors": [author_row(True, 1220, PB)]},
            {"target_authors": [author_row(1280, 1220, PB)]},
            {"target_authors": [author_row(1300, 2200, PB)]},
            {"source_authors": [author_row(1100, 1160, PA),
                                author_row(1100, 1160, PA)]},
            {"source_authors": [author_row(1100, 1160, PA),
                                author_row(1100, 1160, PB),
                                author_row(1100, 1160, PA)]},
            {"source_text": "PRIVATE"},
        ]:
            with self.subTest(change=str(change)[:60]):
                self.store.chronology = [dict(deepcopy(baseline), **change)]
                response = self.client.get(
                    "/v1/analysis/chronology/author-lifetimes",
                    params={"source_id": A, "target_id": B}, headers=self.auth)
                self.assertEqual(response.status_code, 503, response.text)
                self.assertNotIn("PRIVATE", response.text)
        self.store.chronology = [baseline, deepcopy(baseline)]
        with self.assertRaises(DatabaseUnavailable):
            author_chronology(self.store, source_id=A, target_id=B)

    def test_security_blocks_unauthorized_and_unrecognized_inputs(self):
        n = len(self.store.calls)
        self.assertEqual(self.client.get("/v1/analysis/metrics/link-frequency",
                         params={"passage_id": A}).status_code, 401)
        self.assertEqual(len(self.store.calls), n)
        invalid_urls = [
            "/v1/analysis/metrics/link-frequency?passage_id=bad",
            "/v1/analysis/metrics/link-frequency?passage_id=" + A + "&limit=100",
            "/v1/analysis/metrics/link-frequency?passage_id=" + A + "&passage_id=" + A,
            "/v1/analysis/chronology/author-lifetimes?source_id=" + A,
            "/v1/analysis/chronology/author-lifetimes?source_id=" + A + "&target_id=" + A,
            "/v1/analysis/chronology/author-lifetimes?source_id=" + A + "&target_id=" + EV,
            "/v1/analysis/chronology/author-lifetimes?source_id=" + A + "&target_id=" + B + "&scope=all",
            "/v1/analysis/chronology/author-lifetimes?source_id=" + A + "&target_id=" + B + "&source_id=" + A,
        ]
        for url in invalid_urls:
            with self.subTest(url=url):
                before = len(self.store.calls)
                r = self.client.get(url, headers=self.auth)
                self.assertEqual(r.status_code, 422, r.text)
                self.assertEqual(len(self.store.calls), before)

    def test_static_registry_is_read_only_and_openapi_typed(self):
        for name in ("analysis_frequency_window", "analysis_author_lifetimes"):
            cypher = READ_OPERATIONS[name].upper()
            self.assertIn("EVIDENCE", cypher)
            self.assertIn("LIMIT ", cypher)
            if name == "analysis_frequency_window":
                self.assertIn("WITH P\nCALL (P) {", cypher)
                self.assertIn("RETURN R\n}", cypher)
                self.assertEqual(cypher.count("CALL (P) {"), 1)
                cypher = cypher.replace("CALL (P) {", "")
            for forbidden in ("CREATE ", "MERGE ", "DELETE ", "SET ",
                              "CALL ", "LOAD CSV", "APOC."):
                self.assertNotIn(forbidden, cypher)
        paths = self.client.get("/openapi.json").json()["paths"]
        self.assertIn("/v1/analysis/metrics/link-frequency", paths)
        self.assertIn("/v1/analysis/chronology/author-lifetimes", paths)


if __name__ == "__main__":
    unittest.main()
