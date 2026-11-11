"""v0.8.9 bounded signed capture and manifest-integrity regression tests."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib import error, parse

from scripts.search_capture import (
    CaptureError, SignedLoopbackClient, check_page, collect,
    digest, encode, loopback_origin, main, save_private_pair, target_for, verify,
)
from scripts.search_quality_eval import read_evidence
from scripts.search_review_workflow import prepare_packet

ROOT = Path(__file__).resolve().parent / "fixtures"
CATALOG = ROOT / "search_review_questions_synthetic.json"
RESPONSES = ROOT / "search_quality_responses_synthetic.json"
KEY = "synthetic-hmac-" + "x" * 55


class SignedCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog, cls.catalog_sha = read_evidence(CATALOG)
        cls.baseline, _ = read_evidence(RESPONSES)

    def get_pages(self, mode="scan", *, split=False):
        records = copy.deepcopy(self.baseline)
        for record in records["responses"]:
            p = record["pages"][0]
            p["schema_version"] = "0.8.2" if mode == "scan" else "0.8.3"
            p.update({
                "source_trail_verified": False,
                "text_available": False,
                "full_text_indexed": False,
                "corpus_status": "unreviewed_metadata_only",
            })
            if mode == "scan":
                p.update({"candidate_window_limit": 50,
                          "match_order": "canonical_id_scan_not_relevance_ranked"})
            else:
                p.update({"index_version": "search_key_v1",
                          "alias_matching_available": False,
                          "match_order": "indexed_title_prefix_canonical_id"})
            if split and record["id"] == "q-he-001":
                first = copy.deepcopy(p)
                first["items"] = p["items"][:2]
                first["has_more"] = True
                first["search_complete"] = False
                first["next_cursor"] = first["items"][-1]["id"]
                second = copy.deepcopy(p)
                second["items"] = p["items"][2:]
                record["pages"] = [first, second]
        return records

    def collect_fixture(self, mode="scan", split=False):
        source = self.get_pages(mode, split=split)
        def fetch(target):
            q = parse.parse_qs(parse.urlsplit(target).query)
            ident = "q-he-001" if q["query"][0] == "ספר סינתטי" else "q-en-001"
            matching = next(r for r in source["responses"] if r["id"] == ident)
            number = 1 if q.get("cursor") else 0
            return copy.deepcopy(matching["pages"][number])
        return collect(self.catalog, fetch, mode=mode,
                       catalog_sha=self.catalog_sha, key=KEY)

    def test_scan_and_indexed_work_with_existing_review_packet(self):
        for mode in ("scan", "indexed"):
            with self.subTest(mode=mode):
                snap, manifest = self.collect_fixture(mode)
                self.assertEqual(manifest["request_count"], 2)
                self.assertEqual(manifest["release_status"], "HOLD")
                self.assertFalse(manifest["independent_server_attestation"])
                self.assertEqual(verify(
                    self.catalog, snap, manifest, catalog_sha=self.catalog_sha,
                    snapshot_sha=digest(encode(snap)), key=KEY), 2)
                packet = prepare_packet(
                    self.catalog, snap, catalog_hash=self.catalog_sha,
                    captures_hash=digest(encode(snap)))
                self.assertEqual([len(x["hits"]) for x in packet["questions"]], [5, 5])
                self.assertNotIn("SYNTHETIC WORK", json.dumps(manifest))

    def test_cursor_chain_preserved_and_offline_verified(self):
        snap, manifest = self.collect_fixture("scan", split=True)
        self.assertEqual(manifest["request_count"], 3)
        cursor = snap["responses"][0]["pages"][0]["next_cursor"]
        self.assertEqual(manifest["trace"][0]["steps"][1]["input_cursor_sha256"],
                         digest(cursor.encode("utf-8")))
        verify(self.catalog, snap, manifest, catalog_sha=self.catalog_sha,
               snapshot_sha=digest(encode(snap)), key=KEY)

    def test_manifest_and_snapshot_mutations_fail_hmac(self):
        snap, manifest = self.collect_fixture()
        edited = copy.deepcopy(manifest)
        edited["trace"][0]["steps"][0]["returned"] = 100
        with self.assertRaises(CaptureError):
            verify(self.catalog, snap, edited, catalog_sha=self.catalog_sha,
                   snapshot_sha=digest(encode(snap)), key=KEY)
        changed = copy.deepcopy(snap)
        changed["responses"][0]["pages"][0]["items"][0]["title"] = "MODIFIED"
        with self.assertRaises(CaptureError):
            verify(self.catalog, changed, manifest, catalog_sha=self.catalog_sha,
                   snapshot_sha=digest(encode(changed)), key=KEY)
        with self.assertRaises(CaptureError):
            verify(self.catalog, snap, manifest, catalog_sha=self.catalog_sha,
                   snapshot_sha=digest(encode(snap)), key="wrong-" + "z"*60)

    def test_remote_hosts_credentials_redirect_targets_blocked(self):
        for url in ("https://127.0.0.1:8000", "http://localhost:8000",
                    "http://example.com:8000", "http://127.0.0.2:8000",
                    "http://u@127.0.0.1:8000", "http://127.0.0.1:8000/evil",
                    "http://127.0.0.1:8000?redirect=1"):
            with self.subTest(url=url), self.assertRaises(CaptureError):
                loopback_origin(url)
        self.assertEqual(loopback_origin("http://127.0.0.1:8000"),
                         "http://127.0.0.1:8000")

    def test_malformed_page_never_saved(self):
        p = self.get_pages()["responses"][0]["pages"][0]
        case = self.catalog["questions"][0]
        changes = [
            {"items": [{**p["items"][0], "excerpt": "UNLICENSED"}]},
            {"has_more": True, "search_complete": True},
            {"has_more": True, "search_complete": False,
             "next_cursor": "work:" + "0"*64},
            {"kind": "persons"}, {"sensitive_unknown": "text"},
        ]
        for change in changes:
            bad = copy.deepcopy(p)
            bad.update(change)
            with self.subTest(keys=list(change)), self.assertRaises(CaptureError):
                check_page(bad, case, "scan", "", "")

    def test_private_output_created_once_mode_0600(self):
        s, m = self.collect_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            p, q = Path(tmp)/"result.json", Path(tmp)/"manifest.json"
            save_private_pair(p, q, s, m)
            self.assertEqual(os.stat(p).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(q).st_mode & 0o777, 0o600)
            before = p.read_bytes()
            with self.assertRaises(CaptureError):
                save_private_pair(p, q, s, m)
            self.assertEqual(before, p.read_bytes())

    def test_no_ack_fails_before_credentials_or_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = main(["capture", "--questions", str(CATALOG),
                           "--output", str(Path(tmp)/"out"),
                           "--manifest", str(Path(tmp)/"proof")])
        self.assertEqual(result, 2)

    def test_hmac_headers_and_sanitized_denial(self):
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, size): return encode({"status": "synthetic"})[:size]
        class Opener:
            last = None
            def open(self, req, timeout):
                self.last = req
                self.timeout = timeout
                return Response()
        op = Opener()
        with patch("scripts.search_capture.load_token", side_effect=[
            "bearer-" + "a"*60, KEY
        ]):
            client = SignedLoopbackClient("http://127.0.0.1:8000", opener=op)
        t = target_for(self.catalog["questions"][0], "scan", "")
        self.assertEqual(client.fetch(t), {"status": "synthetic"})
        self.assertEqual(op.last.get_method(), "GET")
        self.assertEqual(op.last.full_url, "http://127.0.0.1:8000" + t)
        self.assertEqual(op.timeout, 8)
        self.assertEqual(len(op.last.get_header("X-dviros-signature")), 64)
        self.assertEqual(op.last.get_header("Authorization"),
                         "Bearer bearer-" + "a"*60)
        class Forbidden:
            def open(self, req, timeout):
                raise error.HTTPError(req.full_url, 403, "private", {}, None)
        client.opener = Forbidden()
        with self.assertRaises(CaptureError):
            client.fetch(t)


if __name__ == "__main__":
    unittest.main()
