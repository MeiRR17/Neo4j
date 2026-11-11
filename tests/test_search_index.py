"""v0.8.3 indexed title-prefix search, operator backfill and rights gates."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from research_graph.ontology import stable_id
from scripts.search_index_backfill import (
    KINDS, APPLY, READ, COVERAGE, prepare_row, collect_plan, audit,
)
from services.research_api.app import create_app
from services.research_api.config import bootstrap_token, load_token
from services.research_api.db import DatabaseUnavailable
from services.research_api.queries import READ_OPERATIONS
from services.research_api.search_index import (
    INDEX_SCHEMA, verify_online_index, verify_coverage, search_indexed_metadata,
)

A = stable_id("work", "fixture", "a")
B = stable_id("work", "fixture", "b")
C = stable_id("work", "fixture", "c")
P = stable_id("passage", "fixture", "passage")
IDENTS = sorted([A, B, C])


def hit(identifier, title):
    return {"id": identifier, "title": title,
            "source_anchor": "SYNTHETIC:SOURCE", "aliases": []}


class FakeStore:
    def __init__(self):
        self.calls = []
        self.coverage = {"total": 3, "covered": 3}
        self.index_rows = [{
            "name": "work_search_key_v1", "type": "RANGE",
            "entityType": "NODE", "labelsOrTypes": ["Work"],
            "properties": ["search_key_v1"], "state": "ONLINE",
        }]
        self.data = [
            hit(IDENTS[0], "מֹורֶה נבוכים א"),
            hit(IDENTS[1], "מֹורֶה נבוכים ב"),
            hit(IDENTS[2], "חכמת ישראל"),
        ]

    def query(self, operation, params=None):
        params = params or {}
        self.calls.append((operation, params))
        if operation == "index_state":
            return [dict(row) for row in self.index_rows]
        if operation == "index_coverage_works":
            return [dict(self.coverage)]
        if operation == "indexed_works":
            from services.research_api.metadata_search import fold_metadata
            return [
                row for row in self.data
                if fold_metadata(row["title"]).startswith(params["prefix"])
                and (not params["cursor"] or row["id"] > params["cursor"])
            ][:params["fetch_limit"]]
        return []


class IndexSearchTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()

    def test_index_requires_fresh_full_coverage(self):
        self.assertEqual(verify_coverage(self.store, "works")["covered"], 3)
        for counts in (
            {"total": 0, "covered": 0},
            {"total": 3, "covered": 2},
            {"total": 3, "covered": 4},
            {"total": "3", "covered": 3},
            {"total": True, "covered": 1},
        ):
            with self.subTest(counts=counts):
                self.store.coverage = counts
                with self.assertRaises(DatabaseUnavailable):
                    verify_coverage(self.store, "works")

    def test_physical_index_missing_invalid_or_offline_blocks_search(self):
        baseline = dict(self.store.index_rows[0])
        invalid = [
            [], [baseline, baseline],
            [{**baseline, "state": "POPULATING"}],
            [{**baseline, "state": "FAILED"}],
            [{**baseline, "type": "FULLTEXT"}],
            [{**baseline, "name": "other_index"}],
            [{**baseline, "entityType": "RELATIONSHIP"}],
            [{**baseline, "labelsOrTypes": ["Passage"]}],
            [{**baseline, "properties": ["title"]}],
            [{**baseline, "properties": "search_key_v1"}],
            [{key: value for key, value in baseline.items() if key != "state"}],
            [{**baseline, "secret": "unexpected"}],
        ]
        for rows in invalid:
            with self.subTest(rows=rows):
                self.store.calls.clear()
                self.store.index_rows = rows
                with self.assertRaises(DatabaseUnavailable):
                    search_indexed_metadata(self.store, kind="works", query="מורה")
                self.assertEqual([op for op, _ in self.store.calls], ["index_state"])
        self.store.index_rows = [baseline]
        verify_online_index(self.store, "works")

    def test_nonempty_prefix_only_and_pagination(self):
        page = search_indexed_metadata(self.store, kind="works",
                                       query="מורה", limit=1)
        self.assertEqual(page["schema_version"], INDEX_SCHEMA)
        self.assertEqual(page["index_version"], "search_key_v1")
        self.assertFalse(page["full_text_indexed"])
        self.assertFalse(page["alias_matching_available"])
        self.assertEqual(len(page["items"]), 1)
        self.assertTrue(page["has_more"])
        self.assertFalse(page["search_complete"])
        self.assertEqual(page["match_order"], "indexed_title_prefix_canonical_id")
        cursor = page["next_cursor"]
        page2 = search_indexed_metadata(self.store, kind="works",
                                        query="מוֹרֶה", cursor=cursor, limit=1)
        self.assertEqual(len(page2["items"]), 1)
        self.assertNotEqual(page["items"][0]["id"], page2["items"][0]["id"])
        self.assertTrue(page2["search_complete"])
        self.assertIsNone(page2["next_cursor"])
        self.assertEqual(page["index_coverage"]["complete"], True)
        self.assertTrue(all(item["text_available"] is False
                            and item["review_status"] == "unreviewed"
                            for item in [*page["items"], *page2["items"]]))

    def test_no_alias_or_substring_pretended(self):
        self.assertEqual(search_indexed_metadata(
            self.store, kind="works", query="נבוכים")["items"], [])
        self.assertEqual(search_indexed_metadata(
            self.store, kind="works", query="nonexistent")["items"], [])

    def test_rejects_blank_control_or_wrong_cursor(self):
        for bad in ("", " ", "\n", "\x00", "x" * 101):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                search_indexed_metadata(self.store, kind="works", query=bad)
        with self.assertRaises(ValueError):
            search_indexed_metadata(self.store, kind="works",
                                    query="מורה", cursor=P)
        with self.assertRaises(ValueError):
            search_indexed_metadata(self.store, kind="works",
                                    query="מורה", limit=21)

    def test_malformed_or_unlicensed_result_is_rejected(self):
        sample = hit(A, "מורה נבוכים")
        for mutated in (
            {**sample, "text": "Copyrighted content"},
            {**sample, "source_uri": "https://private.example"},
            {**sample, "review_status": "approved"},
            {**sample, "aliases": ["Invented"]},
            {**sample, "id": P},
            {**sample, "title": "מורה" + "א" * 301},
        ):
            with self.subTest(mutated=mutated):
                self.store.data = [mutated]
                with self.assertRaises(DatabaseUnavailable):
                    search_indexed_metadata(self.store, kind="works",
                                            query="מורה")
        self.store.data = [sample, sample]
        with self.assertRaises(DatabaseUnavailable):
            search_indexed_metadata(self.store, kind="works", query="מורה")

    def test_index_statements_are_statically_allowlisted_and_read_only(self):
        self.assertIn("SHOW INDEXES", READ_OPERATIONS["index_state"])
        self.assertIn("name = $index_name", READ_OPERATIONS["index_state"])
        self.assertNotIn("CREATE INDEX", READ_OPERATIONS["index_state"])
        for kind in KINDS:
            for prefix in ("index_candidates_", "index_coverage_", "indexed_"):
                statement = READ_OPERATIONS[prefix + kind]
                self.assertIn("MATCH (n:", statement)
                self.assertNotIn(" DELETE ", statement.upper())
                self.assertNotIn(" MERGE ", statement.upper())
                self.assertNotIn(" SET ", statement.upper())
            self.assertIn("STARTS WITH $prefix",
                          READ_OPERATIONS["indexed_" + kind])
            self.assertIn("ORDER BY id",
                          READ_OPERATIONS["index_candidates_" + kind])


class BackfillSafetyTests(unittest.TestCase):
    def test_preparation_preserves_ids_and_never_creates_source_text(self):
        title = "מוֹרֶה — נְבוּכִים"
        row = prepare_row([A, title, None, None], "works")
        self.assertEqual(row, {"id": A, "source": title, "key": "מורה נבוכים"})
        self.assertNotIn("excerpt", row)
        self.assertNotIn("rights_status", row)
        self.assertEqual(prepare_row([A, title, row["key"], title], "works"), row)

    def test_preflight_rejects_stale_partial_or_oversized_metadata(self):
        for broken in (
            [P, "Title", None, None],
            [A, "", None, None],
            [A, "a" * 501, None, None],
            [A, "Original", "wrong", "Original"],
            [A, "Changed", "changed", "Original"],
            [A, "Orphan", "orphan", None],
            [A, "Orphan", None, "Orphan"],
            [A, "NUL\x00value", None, None],
        ):
            with self.subTest(row=broken), self.assertRaises(RuntimeError):
                prepare_row(broken, "works")

    def test_backfill_queries_are_static_metadata_only_without_graph_exposure(self):
        for kind in KINDS:
            self.assertIn("SET n.search_key_v1 = row.key", APPLY[kind])
            self.assertIn("n.search_source_v1 = row.source", APPLY[kind])
            self.assertNotIn("text_body", APPLY[kind])
            self.assertNotIn("DELETE", APPLY[kind])
            self.assertIn("LIMIT $fetch_limit", READ[kind])
            self.assertIn("count(n) AS total", COVERAGE[kind])

    def test_malformed_candidate_order_or_duplicates_are_rejected(self):
        class FakeBackfill:
            def query(self, statement, params=None):
                del statement, params
                return [[A, "A", None, None], [A, "A", None, None]]
        with self.assertRaises(RuntimeError):
            collect_plan(FakeBackfill(), "works")


class IndexedHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name) / "api-token"
        bootstrap_token(path)
        self.store = FakeStore()
        self.client = TestClient(create_app(backend=self.store, token_path=path))
        self.auth = {"Authorization": "Bearer " + load_token(path)}

    def test_private_endpoint_auth_and_no_unlicensed_fields(self):
        target = "/v1/search/metadata/indexed?kind=works&query=מורה&limit=2"
        self.assertEqual(self.client.get(target).status_code, 401)
        self.assertEqual(self.store.calls, [])
        result = self.client.get(target, headers=self.auth)
        self.assertEqual(result.status_code, 200, result.text)
        payload = result.json()
        self.assertEqual(payload["schema_version"], "0.8.3")
        self.assertEqual(payload["index_coverage"]["total"], 3)
        self.assertEqual(len(payload["items"]), 2)
        self.assertFalse(payload["full_text_indexed"])
        self.assertTrue(all("excerpt" not in item for item in payload["items"]))
        self.assertEqual(result.headers["Cache-Control"], "no-store")

    def test_incomplete_index_returns_sanitized_503(self):
        self.store.coverage = {"total": 3, "covered": 2}
        result = self.client.get(
            "/v1/search/metadata/indexed?kind=works&query=מורה",
            headers=self.auth)
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("covered", result.text)

    def test_new_endpoint_rejects_unsupported_facet_and_duplicate_param(self):
        for query in ("kind=works&query=מורה&author=approved",
                      "kind=works&query=מורה&kind=persons",
                      "kind=works&query=",
                      "kind=persons&query=author&language=he"):
            with self.subTest(query=query):
                result = self.client.get(
                    "/v1/search/metadata/indexed?" + query, headers=self.auth)
                self.assertEqual(result.status_code, 422)
        self.assertEqual(self.store.calls, [])


if __name__ == "__main__":
    unittest.main()
