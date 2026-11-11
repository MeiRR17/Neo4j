"""v0.8.11 private provenance API and HMAC capture safeguards.

All records here are invented IDs and metadata; no real source material,
rights decisions or independent reviewer approvals are created.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from research_graph.ontology import stable_id
from scripts.search_capture import (
    CaptureError, SignedLoopbackClient, collect, digest, encode, verify,
)
from scripts.search_provenance import (
    checked_page, observe_provenance, target, validate_provenance_observation,
)
from scripts.search_revision import observe_projection
from services.research_api.app import create_app
from services.research_api.config import bootstrap_token, load_token
from services.research_api.db import DatabaseUnavailable
from services.research_api.provenance import (
    provenance_page, safe_provenance_item,
)
from tests.test_search_revision import FakeSignedPages
from scripts.search_quality_eval import read_evidence

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CATALOG = FIXTURES / "search_review_questions_synthetic.json"
SEARCH = FIXTURES / "search_quality_responses_synthetic.json"
KEY = "synthetic-provenance-key-" + "x" * 50
SRC = stable_id("source", "fixture", "source-1")
WORK = stable_id("work", "fixture", "work-1")
ED = stable_id("edition", "fixture", "edition-1")
EVID = stable_id("evidence", "fixture", "evidence-1")


def rows():
    return {
        "sources": [{
            "id": SRC, "provider": "synthetic", "source_uri": "SYNTHETIC:SOURCE",
            "version_id": "source-fixture-1", "rights_tag": "NOT_ASSESSED",
            "checksum_sha256": "a" * 64,
        }],
        "editions": [{
            "id": ED, "work_id": WORK, "version_id": "synthetic-version-1",
            "language": "he", "rights_tag": "NOT_ASSESSED",
            "rights_review_status": None,
            "allowed_text_redistribution": False,
        }],
        "evidence": [{
            "id": EVID, "source_record_id": SRC,
            "version_id": "synthetic-record", "rights_tag": "NOT_ASSESSED",
            "claim_kind": "OBSERVED_SOURCE_LINK", "review_status": "unreviewed",
        }],
    }


class Store:
    def __init__(self):
        self.rows = rows()
        self.calls = []

    def query(self, op, params=None):
        self.calls.append((op, params))
        if not op.startswith("provenance_"):
            return []
        kind = op.removeprefix("provenance_")
        cur = params["cursor"]
        lim = params["fetch_limit"]
        return [dict(x) for x in sorted(self.rows[kind], key=lambda x: x["id"])
                if not cur or x["id"] > cur][:lim]


class CombinedAPI:
    def __init__(self, search_data, *, mutate=False):
        self.search = FakeSignedPages(search_data)
        self.store = Store()
        self.mutate = mutate
        self.probes = 0

    def __call__(self, raw_target):
        if raw_target.startswith("/v1/provenance/metadata?"):
            params = parse_qs(urlsplit(raw_target).query)
            kind = params["kind"][0]
            if kind == "editions":
                self.probes += 1
                if self.mutate and self.probes == 2:
                    self.store.rows["editions"][0]["version_id"] = "changed-during-capture"
            return provenance_page(
                self.store, kind=kind,
                cursor=params.get("cursor", [None])[0],
                limit=int(params["limit"][0]))
        return self.search(raw_target)


class ProvenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog, cls.catalog_sha = read_evidence(CATALOG)
        cls.search_data, _ = read_evidence(SEARCH)

    def _capture(self, api):
        return collect(
            self.catalog, api, mode="scan", catalog_sha=self.catalog_sha,
            key=KEY,
            revision_probe=lambda: observe_projection(
                self.catalog, api, mode="scan"),
            provenance_probe=lambda: observe_provenance(api))

    def test_bounded_sanitized_three_kind_observation(self):
        api = CombinedAPI(self.search_data)
        obs = observe_provenance(api)
        validate_provenance_observation(obs)
        self.assertEqual([x["kind"] for x in obs["observations"]],
                         ["editions", "evidence", "sources"])
        self.assertEqual([x["records"] for x in obs["observations"]],
                         [1, 1, 1])
        self.assertFalse(obs["source_bytes_verified"])
        self.assertFalse(obs["source_rights_verified"])
        self.assertFalse(obs["graph_relationships_covered"])
        self.assertNotIn("SYNTHETIC:SOURCE", json.dumps(obs))
        self.assertNotIn("synthetic-version-1", json.dumps(obs))

    def test_edited_version_causes_fail_closed_capture_without_manifest(self):
        api = CombinedAPI(self.search_data, mutate=True)
        with self.assertRaises(CaptureError):
            self._capture(api)

    def test_hmac_manifest_is_backward_compatible_and_tamper_evident(self):
        api = CombinedAPI(self.search_data)
        snapshots, manifest = self._capture(api)
        self.assertEqual(manifest["schema_version"], "0.8.11")
        self.assertEqual(manifest["release_status"], "HOLD")
        self.assertEqual(verify(
            self.catalog, snapshots, manifest, catalog_sha=self.catalog_sha,
            snapshot_sha=digest(encode(snapshots)), key=KEY), 2)
        tampered = copy.deepcopy(manifest)
        tampered["provenance_observation"]["observations"][1]["records"] = 50
        with self.assertRaises(CaptureError):
            verify(self.catalog, snapshots, tampered,
                   catalog_sha=self.catalog_sha,
                   snapshot_sha=digest(encode(snapshots)), key=KEY)
        with self.assertRaises(CaptureError):
            verify(self.catalog, snapshots, manifest,
                   catalog_sha=self.catalog_sha,
                   snapshot_sha=digest(encode(snapshots)),
                   key="wrong-" + "k" * 80)

    def test_no_provenance_without_existing_search_revision_pin(self):
        api = CombinedAPI(self.search_data)
        with self.assertRaises(CaptureError):
            collect(self.catalog, api, mode="scan", catalog_sha=self.catalog_sha,
                    key=KEY, provenance_probe=lambda: observe_provenance(api))

    def test_api_authentication_allowlist_and_safe_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            token_file = Path(tmp) / "token"
            bootstrap_token(token_file)
            store = Store()
            client = TestClient(create_app(backend=store, token_path=token_file))
            target_url = "/v1/provenance/metadata?kind=sources&limit=20"
            self.assertEqual(client.get(target_url).status_code, 401)
            auth = {"Authorization": "Bearer " + load_token(token_file)}
            r = client.get(target_url, headers=auth)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["schema_version"], "0.8.11")
            self.assertFalse(r.json()["source_bytes_verified"])
            self.assertEqual(len(r.json()["items"]), 1)
            self.assertNotIn("excerpt", json.dumps(r.json()))
            for q in (
                target_url + "&text=1", target_url + "&kind=editions",
                "/v1/provenance/metadata?kind=unknown",
                "/v1/provenance/metadata?kind=sources&limit=21",
                "/v1/provenance/metadata?kind=editions&cursor=" + SRC,
            ):
                with self.subTest(url=q):
                    self.assertEqual(client.get(q, headers=auth).status_code, 422)

    def test_pagination_is_sorted_and_resume_exactly(self):
        store = Store()
        store.rows["sources"] = sorted([
            {"id": stable_id("source", "synth", str(i)),
             "provider": "synthetic", "source_uri": None, "version_id": None,
             "rights_tag": None, "checksum_sha256": None}
            for i in range(22)
        ], key=lambda x: x["id"])
        p1 = provenance_page(store, kind="sources", cursor=None, limit=20)
        self.assertEqual(len(p1["items"]), 20)
        self.assertTrue(p1["has_more"])
        self.assertEqual(p1["next_cursor"], p1["items"][-1]["id"])
        p2 = provenance_page(store, kind="sources",
                             cursor=p1["next_cursor"], limit=20)
        self.assertEqual(len(p2["items"]), 2)
        self.assertTrue(p2["search_complete"])
        self.assertIsNone(p2["next_cursor"])

    def test_malformed_projections_and_rights_promotion_fail(self):
        for changed in (
            {"checksum_sha256": "not-sha"},
            {"source_text": "UNLICENSED"},
        ):
            source = rows()["sources"][0]
            source.update(changed)
            with self.assertRaises(DatabaseUnavailable):
                safe_provenance_item(source, "sources")
        ed = rows()["editions"][0]
        ed["allowed_text_redistribution"] = True
        with self.assertRaises(DatabaseUnavailable):
            safe_provenance_item(ed, "editions")
        ev = rows()["evidence"][0]
        ev["claim_kind"] = "FAKE_HUMAN_APPROVAL"
        with self.assertRaises(DatabaseUnavailable):
            safe_provenance_item(ev, "evidence")

    def test_client_only_accepts_exact_provenance_targets(self):
        class FakeResponse:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *unused): return False
            def read(self, n): return encode(provenance_page(Store(), kind="sources",
                                                               cursor=None, limit=20))[:n]
        class FakeTransport:
            def open(self, req, timeout): return FakeResponse()
        with patch("scripts.search_capture.load_token", side_effect=[
            "bearer-" + "b" * 70, KEY
        ]):
            client = SignedLoopbackClient(
                "http://127.0.0.1:8000", opener=FakeTransport())
        self.assertEqual(client.fetch(target("sources"))["kind"], "sources")
        for value in (
            target("sources") + "&export_text=true",
            "/v1/provenance/metadata?kind=sources&limit=21",
            "/v1/provenance/metadata?kind=works&limit=20",
        ):
            with self.assertRaises(CaptureError):
                client.fetch(value)

    def test_cursor_injection_and_foreign_type_denied(self):
        self.assertIn("kind=sources", target("sources"))
        with self.assertRaises(CaptureError):
            target("sources", WORK)
        with self.assertRaises(ValueError):
            provenance_page(Store(), kind="editions", cursor=SRC, limit=20)
