"""v0.8.2 deterministic metadata search and service-auth regression tests."""
from __future__ import annotations

from pathlib import Path
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from research_graph.ontology import stable_id
from services.research_api.app import create_app
from services.research_api.config import bootstrap_token, load_token
from services.research_api.db import DatabaseUnavailable
from services.research_api.signature import CLIENT_ID, sign_request
from services.research_api.metadata_search import (
    ALLOWED_KINDS, SCAN_LIMIT, fold_metadata, search_metadata, validate_search,
)
from services.research_api.queries import READ_OPERATIONS


WORK = stable_id("work", "fixture", "Guide of Thoughts")
PASSAGE = stable_id("passage", "fixture", "Part 1:1")
PERSON = stable_id("person", "fixture", "Invented Author")
CONCEPT = stable_id("concept", "fixture", "Invented Concept")


def row(kind: str, suffix: int, title: str = "Unmatched metadata") -> dict:
    ident = f"{kind}:{suffix:064x}"
    return {"id": ident, "title": title,
            "source_anchor": "SYNTHETIC:source", "aliases": []}


class MetadataStore:
    def __init__(self, data=None):
        self.data = data or {}
        self.calls: list[tuple[str, dict]] = []

    def query(self, operation: str, params=None):
        params = params or {}
        self.calls.append((operation, params))
        rows = self.data.get(operation, [])
        return [r for r in rows if not params.get("cursor") or
                r["id"] > params["cursor"]][:params.get("fetch_limit", 51)]


class NormalizationAndPaging(unittest.TestCase):
    def test_unicode_nfkd_niqqud_cantillation_and_punctuation(self):
        self.assertEqual(fold_metadata("מַחְבֵּר"), "מחבר")
        self.assertEqual(fold_metadata("חֹכְמַת־יִשְׂרָאֵל"), "חכמת ישראל")
        self.assertEqual(fold_metadata("Gúide — For, The Pérplexed"), "guide for the perplexed")
        self.assertEqual(fold_metadata("רַבִּי  מֹשֶׁה"), "רבי משה")
        with self.assertRaises(ValueError):
            fold_metadata("unsafe\nlabel")

    def test_exact_canonical_ids_preserved_not_normalized(self):
        store = MetadataStore({"metadata_works":[{
            "id": WORK, "title": "מורה נבוכים",
            "source_anchor": "SYNTHETIC:REF", "aliases": [],
        }]})
        result = search_metadata(store, kind="works", query=WORK)
        self.assertEqual(result["items"][0]["id"], WORK)
        self.assertEqual(result["items"][0]["match_basis"], "canonical_id")
        self.assertEqual(result["items"][0]["source_verification"], "NOT_VERIFIED")
        self.assertFalse(result["items"][0]["text_available"])

    def test_hebrew_and_english_alias_matching_without_source_text(self):
        store = MetadataStore({"metadata_works":[{
            "id": WORK, "title": "מֹורֶה הַנְּבוּכִים",
            "source_anchor": "SYNTHETIC:WORK", "aliases": ["Guide for the Perplexed"],
        }]})
        hebrew = search_metadata(store, kind="works", query="מורה הנבוכים")
        english = search_metadata(store, kind="works", query="guide for the perplexed")
        self.assertEqual(hebrew["items"][0]["match_basis"], "title")
        self.assertEqual(english["items"][0]["match_basis"], "alias")
        for result in (hebrew, english):
            self.assertFalse(result["full_text_indexed"])
            self.assertFalse(result["source_trail_verified"])
            self.assertEqual(result["items"][0]["rights_status"], "NOT_ASSESSED")
            self.assertNotIn("aliases", result["items"][0])
            self.assertNotIn("excerpt", result["items"][0])

    def test_50_candidate_windows_resume_with_last_scanned_id(self):
        data = [row("work", k, "filler") for k in range(1, 61)]
        data[-1] = row("work", 60, "לְמִידָה")
        store = MetadataStore({"metadata_works": data})
        first = search_metadata(store, kind="works", query="למידה")
        self.assertEqual(first["items"], [])
        self.assertEqual(first["scanned_candidates"], 50)
        self.assertTrue(first["has_more"])
        self.assertFalse(first["search_complete"])
        self.assertEqual(first["next_cursor"], data[49]["id"])
        second = search_metadata(store, kind="works", query="למידה",
                                 cursor=first["next_cursor"])
        self.assertEqual(second["items"][0]["id"], data[59]["id"])
        self.assertTrue(second["search_complete"])
        self.assertIsNone(second["next_cursor"])
        self.assertEqual(store.calls[-1][0], "metadata_works")
        self.assertEqual(store.calls[-1][1]["fetch_limit"], SCAN_LIMIT + 1)

    def test_limit_matches_never_skips_eligible_following_ids(self):
        data = [row("concept", k, "חכמָה") for k in range(1, 5)]
        store = MetadataStore({"metadata_concepts": data})
        first = search_metadata(store, kind="concepts", query="חכמה", limit=2)
        self.assertEqual(len(first["items"]), 2)
        self.assertEqual(first["next_cursor"], data[1]["id"])
        second = search_metadata(store, kind="concepts", query="חכמה",
                                 cursor=first["next_cursor"], limit=2)
        self.assertEqual([r["id"] for r in second["items"]],
                         [data[2]["id"], data[3]["id"]])
        self.assertTrue(second["search_complete"])

    def test_invalid_kind_cursor_language_and_query_budgets(self):
        for args in [
            {"kind": "edges"}, {"kind": "works", "limit": 21},
            {"kind": "works", "limit": 0},
            {"kind": "works", "query": "x" * 101},
            {"kind": "works", "query": "hello\nthere"},
            {"kind": "works", "cursor": PASSAGE},
            {"kind": "concepts", "language": "he"},
            {"kind": "works", "language": "xx"},
        ]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                search_metadata(MetadataStore(), **args)

    def test_corrupt_rows_or_surprising_fields_fail_closed(self):
        good = {"id": WORK, "title": "safe", "source_anchor": None, "aliases": []}
        for bad in [
            {**good, "text": "Unlicensed excerpt"},
            {**good, "review_status": "approved"},
            {**good, "source_uri": "https://unapproved.example"},
            {**good, "title": "title\nwith newline"},
            {**good, "aliases": ["foo"] * 9},
            {**good, "aliases": [None]},
            {**good, "id": PASSAGE},
            {**good, "title": None},
        ]:
            with self.subTest(bad=bad), self.assertRaises(DatabaseUnavailable):
                search_metadata(MetadataStore({"metadata_works":[bad]}),
                                kind="works", query="")
        with self.assertRaises(DatabaseUnavailable):
            search_metadata(MetadataStore({"metadata_works":[good, good]}),
                            kind="works", query="")

    def test_query_registry_still_contains_only_server_read_statements(self):
        self.assertEqual(set(ALLOWED_KINDS),
                         {"works", "persons", "passages", "concepts"})
        for operation in ["metadata_works", "metadata_persons",
                          "metadata_passages", "metadata_concepts"]:
            statement = READ_OPERATIONS[operation]
            for keyword in ["CREATE ", "DELETE ", "MERGE ", "SET ",
                            "REMOVE ", "CALL ", "APOC.", "LOAD CSV"]:
                self.assertNotIn(keyword, statement.upper())
            self.assertIn("LIMIT $fetch_limit", statement)
            self.assertIn("ORDER BY id", statement)


class PrivateMetadataEndpoint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        token_file = Path(self.tmp.name) / "private_api_token"
        bootstrap_token(token_file)
        self.hmac_key = Path(self.tmp.name) / "private_hmac_key"
        bootstrap_token(self.hmac_key)
        self.store = MetadataStore({"metadata_works":[{
            "id": WORK, "title": "Synthetically named work",
            "source_anchor": "SYNTHETIC:WORK", "aliases": ["מֹורֶה נְבוּכִים"],
        }]})
        self.client = TestClient(create_app(
            backend=self.store, token_path=token_file,
            signature_path=self.hmac_key,
        ))
        self.auth = {"Authorization": "Bearer " + load_token(token_file)}

    def test_route_requires_backend_auth_before_query(self):
        before = len(self.store.calls)
        self.assertEqual(self.client.get("/v1/search/metadata?kind=works").status_code, 401)
        self.assertEqual(self.client.get("/v1/search/metadata?kind=works",
                           headers={"Authorization": "Bearer wrong"}).status_code, 403)
        self.assertEqual(len(self.store.calls), before)

    def test_route_returns_unapproved_metadata_and_no_text(self):
        result = self.client.get("/v1/search/metadata?kind=works&query=מורה%20נבוכים",
                                 headers=self.auth)
        self.assertEqual(result.status_code, 200, result.text)
        dto = result.json()
        self.assertEqual(dto["schema_version"], "0.8.2")
        self.assertEqual(dto["items"][0]["id"], WORK)
        self.assertTrue(dto["search_complete"])
        self.assertFalse(dto["text_available"])
        self.assertEqual(dto["items"][0]["review_status"], "unreviewed")
        self.assertNotIn("text", dto["items"][0])
        self.assertNotIn("aliases", dto["items"][0])
        self.assertEqual(result.headers["Cache-Control"], "no-store")

    def test_route_refuses_unknown_facet_and_unbounded_request(self):
        for params in [
            {"kind": "works", "author": "unspecified"},
            {"kind": "works", "limit": 21},
            {"kind": "works", "cursor": PASSAGE},
            {"kind": "persons", "language": "he"},
            {"kind": "works", "query": "bad\nquery"},
        ]:
            result = self.client.get("/v1/search/metadata", params=params, headers=self.auth)
            self.assertIn(result.status_code, (400, 422), result.text)
        self.assertEqual(self.store.calls, [])

    def test_signed_search_requires_hmac_binds_query_and_rejects_replay(self):
        target = "/v1/search/metadata?kind=works&query=sample"
        now = int(time.time())
        nonce = "0123456789abcdef0123456789abcdef"
        headers = {
            **self.auth, "X-DvirOS-Client": CLIENT_ID,
            "X-DvirOS-Timestamp": str(now), "X-DvirOS-Nonce": nonce,
            "X-DvirOS-Signature": sign_request(
                load_token(self.hmac_key), "GET", target, now, nonce),
        }
        with patch.dict(os.environ, {"DVIROS_REQUIRE_SIGNED_CALLS": "1"}):
            self.assertEqual(self.client.get(target, headers=self.auth).status_code, 403)
            signed = self.client.get(target, headers=headers)
            self.assertEqual(signed.status_code, 200, signed.text)
            self.assertEqual(self.client.get(target, headers=headers).status_code, 403)
            changed = target + "&limit=2"
            self.assertEqual(self.client.get(changed, headers=headers).status_code, 403)

    def test_search_api_advertised_but_no_cypher_endpoint(self):
        paths = self.client.get("/openapi.json").json()["paths"]
        self.assertIn("/v1/search/metadata", paths)
        self.assertNotIn("/v1/cypher", paths)


if __name__ == "__main__":
    unittest.main()
