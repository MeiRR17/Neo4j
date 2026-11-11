"""v0.8.10 observed metadata/index revision pin tests, synthetic-only."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import unittest

from scripts.search_capture import CaptureError, collect, digest, encode, verify
from scripts.search_revision import (
    observe_projection, checked_capability, validate_observation,
)
from scripts.search_quality_eval import read_evidence

FIX = Path(__file__).resolve().parent / "fixtures"
CATALOG = FIX / "search_review_questions_synthetic.json"
RESPONSES = FIX / "search_quality_responses_synthetic.json"
KEY = "fixture-" + "a" * 60


def index_cap(kind: str) -> dict:
    return {
        "schema_version": "0.8.5", "kind": kind,
        "index_version": "search_key_v1", "index_status": "ready",
        "indexed_prefix_ready": True,
        "index_coverage": {"total": 5, "covered": 5, "complete": True},
        "bounded_scan_supported": True, "scan_candidate_window_limit": 50,
        "scan_requires_cursor_completion": True,
        "alias_matching_on_index": False, "full_text_indexed": False,
        "source_trail_verified": False, "text_available": False,
        "corpus_status": "unreviewed_metadata_only",
    }


class FakeSignedPages:
    def __init__(self, baseline, *, corrupt_on_second=False):
        self.records = baseline["responses"]
        self.change = corrupt_on_second
        self.cap_calls = 0
        self.calls = []
    def __call__(self, target):
        self.calls.append(target)
        args = parse_qs(urlsplit(target).query, keep_blank_values=True)
        kind = args["kind"][0]
        if target.startswith("/v1/search/metadata/indexed/capability?"):
            self.cap_calls += 1
            cap = index_cap(kind)
            if self.change and self.cap_calls > 1:
                cap["index_status"] = "not_online"
                cap["indexed_prefix_ready"] = False
            return cap
        if target.startswith("/v1/search/metadata/indexed?"):
            schema = "0.8.3"
        else:
            schema = "0.8.2"
        qid = "q-he-001" if args.get("query", [""])[0] == "ספר סינתטי" else "q-en-001"
        source = next(r for r in self.records if r["id"] == qid)
        page = copy.deepcopy(source["pages"][0])
        page.update({
            "schema_version": schema, "corpus_status": "unreviewed_metadata_only",
            "source_trail_verified": False, "full_text_indexed": False,
            "text_available": False,
        })
        if schema == "0.8.2":
            page.update({"candidate_window_limit": 50,
                         "match_order": "canonical_id_scan_not_relevance_ranked"})
            page.pop("index_version", None)
            page.pop("alias_matching_available", None)
            page.pop("index_coverage", None)
        else:
            page.update({"match_order": "indexed_title_prefix_canonical_id",
                         "alias_matching_available": False, "index_version": "search_key_v1",
                         "index_coverage": {"total": 5, "covered": 5, "complete": True}})
            page.pop("candidate_window_limit", None)
        return page


class RevisionPinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog, cls.catalog_sha = read_evidence(CATALOG)
        cls.source, _ = read_evidence(RESPONSES)

    def test_scan_revision_observation_is_narrow_but_stable(self):
        source = FakeSignedPages(self.source)
        obs = observe_projection(self.catalog, source, mode="scan")
        self.assertEqual(obs["schema_version"], "0.8.10")
        self.assertEqual(len(obs["observations"]), 1)
        self.assertFalse(obs["corpus_immutable_revision_verified"])
        self.assertFalse(obs["snapshot_isolation_guaranteed"])
        self.assertTrue(obs["alias_edition_source_text_not_covered"])
        self.assertEqual(obs["observations"][0]["kind"], "works")
        validate_observation(obs, {"works"}, mode="scan")
        self.assertEqual(obs, observe_projection(self.catalog, source, mode="scan"))

    def test_capture_refuses_index_drift_between_before_after(self):
        api = FakeSignedPages(self.source, corrupt_on_second=True)
        with self.assertRaises(CaptureError):
            collect(self.catalog, api, mode="indexed",
                    catalog_sha=self.catalog_sha, key=KEY,
                    revision_probe=lambda: observe_projection(
                        self.catalog, api, mode="indexed"))

    def test_bound_capture_and_offline_verify_fail_on_forgery(self):
        api = FakeSignedPages(self.source)
        captures, manifest = collect(
            self.catalog, api, mode="scan",
            catalog_sha=self.catalog_sha, key=KEY,
            revision_probe=lambda: observe_projection(
                self.catalog, api, mode="scan"))
        self.assertEqual(manifest["schema_version"], "0.8.10")
        self.assertIn("revision_observation", manifest)
        count = verify(self.catalog, captures, manifest,
                       catalog_sha=self.catalog_sha,
                       snapshot_sha=digest(encode(captures)), key=KEY)
        self.assertEqual(count, 2)
        edited = copy.deepcopy(manifest)
        edited["revision_observation"]["observations"][0]["visible_metadata_records"] = 9
        with self.assertRaises(CaptureError):
            verify(self.catalog, captures, edited, catalog_sha=self.catalog_sha,
                   snapshot_sha=digest(encode(captures)), key=KEY)
        with self.assertRaises(CaptureError):
            verify(self.catalog, captures, manifest, catalog_sha=self.catalog_sha,
                   snapshot_sha=digest(encode(captures)), key="changed-"+"b"*64)

    def test_incomplete_revision_scan_fail_closed(self):
        api = FakeSignedPages(self.source)
        original = api.__call__
        class Broken:
            def __call__(self, target):
                page = original(target)
                if target.startswith("/v1/search/metadata?"):
                    page["has_more"] = True
                    page["search_complete"] = False
                    page["next_cursor"] = "work:" + "f" * 64
                return page
        with self.assertRaises(CaptureError):
            observe_projection(self.catalog, Broken(), mode="scan")

    def test_invalid_capability_and_digest_rejected(self):
        cap = index_cap("works")
        cap["text_available"] = True
        with self.assertRaises(CaptureError):
            checked_capability(cap, "works", "scan")
        api = FakeSignedPages(self.source)
        obs = observe_projection(self.catalog, api, mode="indexed")
        obs["observation_sha256"] = "f" * 64
        with self.assertRaises(CaptureError):
            validate_observation(obs, {"works"}, mode="indexed")
