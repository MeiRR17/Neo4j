"""v0.9.11 bounded, twice-observed signed audit export contract."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from research_graph.ontology import stable_id
from services.research_api.app import create_app
from services.research_api.audit_checkpoint import AuditWindowDrift
from services.research_api.audit_export_v0911 import (
    MAX_LINKS, MAX_PAGES, PAGE_SIZE, export_work_link_audit,
    verify_audit_export,
)
from services.research_api.config import bootstrap_token, load_token
from services.research_api.db import DatabaseUnavailable
from scripts.verify_work_audit_export_v0911 import main as verify_cli
from tests.test_work_link_audit_v099 import AuditStore
from tests.test_work_comparison import LEFT, RIGHT, edge


class ExportAuditTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.key = Path(temp.name) / "service-key"
        bootstrap_token(self.key)
        self.secret = load_token(self.key)
        self.headers = {"Authorization": "Bearer " + self.secret}
        self.store = AuditStore()
        self.client = TestClient(create_app(backend=self.store,
                                            token_path=self.key))

    def get(self, **params):
        query = {"source_work_id": LEFT, "target_work_id": RIGHT}
        query.update(params)
        return self.client.get(
            "/v1/analysis/works/links/audit/export",
            params=query, headers=self.headers)

    def test_signed_export_two_full_passes_and_offline_verify(self):
        response = self.get()
        self.assertEqual(response.status_code, 200, response.text)
        bundle = response.json()
        m = bundle["manifest"]
        self.assertEqual(m["schema_version"], "0.9.11")
        self.assertEqual(m["source_work_id"], LEFT)
        self.assertEqual(m["target_work_id"], RIGHT)
        self.assertEqual(m["observed_link_count"], 4)
        self.assertEqual(m["pages_per_pass"], 1)
        self.assertTrue(m["sequential_passes_matched"])
        self.assertFalse(m["graph_snapshot_verified"])
        self.assertFalse(m["corpus_revision_immutable"])
        self.assertFalse(m["independently_licensed_sources_verified"])
        self.assertEqual(m["research_release_status"], "HOLD")
        self.assertEqual(len(bundle["receipt_hmac_sha256"]), 64)
        checked = verify_audit_export(bundle, secret=self.secret)
        self.assertTrue(checked["hmac_verified_with_local_service_secret"])
        self.assertEqual(checked["observed_link_count"], 4)
        self.assertFalse(checked["source_rights_verified"])
        queries = [name for name, _ in self.store.calls]
        self.assertEqual(queries.count("analysis_work_cross_link_page"), 2)
        self.assertEqual(queries.count("analysis_work_descriptor"), 4)

    def test_empty_valid_export_has_one_page_each_pass(self):
        self.store.forward = []
        result = export_work_link_audit(
            self.store, source_work_id=LEFT,
            target_work_id=RIGHT, secret=self.secret, now=1234567890)
        self.assertEqual(result["manifest"]["ordered_links"], [])
        self.assertEqual(result["manifest"]["observed_link_count"], 0)
        self.assertEqual(result["manifest"]["pages_per_pass"], 1)
        self.assertEqual(verify_audit_export(result, secret=self.secret)
                         ["observed_link_count"], 0)

    def test_multi_page_100_link_cap_and_monotonic_evidence(self):
        self.store.forward = [edge(f"full-export-{i}") for i in range(100)]
        exported = export_work_link_audit(
            self.store, source_work_id=LEFT, target_work_id=RIGHT,
            secret=self.secret, now=1234567890)
        m = exported["manifest"]
        self.assertEqual(m["observed_link_count"], MAX_LINKS)
        self.assertEqual(m["pages_per_pass"], MAX_PAGES)
        self.assertEqual([x["edge_id"] for x in m["ordered_links"]],
                         sorted(x["edge_id"] for x in m["ordered_links"]))
        self.assertEqual(len({x["evidence_id"]
                              for x in m["ordered_links"]}), 100)
        self.assertEqual(verify_audit_export(
            exported, secret=self.secret)["observed_link_count"], 100)

    def test_101_links_fail_closed_instead_of_partial_export(self):
        self.store.forward = [edge(f"oversize-export-{i}") for i in range(101)]
        self.assertEqual(self.get().status_code, 503)
        self.assertLessEqual(sum(
            name == "analysis_work_cross_link_page"
            for name, _ in self.store.calls), 5)

    def test_changes_between_passes_return_sanitized_409(self):
        class ChangingStore(AuditStore):
            def __init__(self):
                super().__init__()
                self.read_count = 0

            def query(self, name, params):
                if name == "analysis_work_cross_link_page":
                    self.read_count += 1
                    if self.read_count == 2:
                        self.forward[0]["evidence_review_status"] = "rejected"
                return super().query(name, params)

        store = ChangingStore()
        client = TestClient(create_app(backend=store, token_path=self.key))
        response = client.get("/v1/analysis/works/links/audit/export",
                              params={"source_work_id": LEFT,
                                      "target_work_id": RIGHT},
                              headers=self.headers)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["error"]["code"], "AUDIT_DRIFT")
        self.assertNotIn("source_ref", response.text)
        self.assertEqual(store.read_count, 2)

    def test_tamper_one_status_fails_hmac_even_if_shape_valid(self):
        b = self.get().json()
        b["manifest"]["ordered_links"][0]["evidence_review_status"] = "rejected"
        with self.assertRaises(ValueError):
            verify_audit_export(b, secret=self.secret)

    def test_wrong_secret_and_rewritten_digest_fail(self):
        b = self.get().json()
        with self.assertRaises(ValueError):
            verify_audit_export(b, secret="Z" * 48)
        b["manifest_sha256"] = "f" * 64
        with self.assertRaises(ValueError):
            verify_audit_export(b, secret=self.secret)

    def test_untrusted_extra_fields_and_false_approvals_fail(self):
        original = self.get().json()
        variants = [
            ("manifest", "graph_snapshot_verified", True),
            ("manifest", "research_release_status", "PASS"),
            ("manifest", "corpus_revision_immutable", True),
            ("manifest", "independently_licensed_sources_verified", True),
            ("manifest", "historical_influence_proven", True),
            ("manifest", "pages_per_pass", 5),
        ]
        for field, key, value in variants:
            with self.subTest(key=key):
                b = deepcopy(original)
                b[field][key] = value
                with self.assertRaises(ValueError):
                    verify_audit_export(b, secret=self.secret)
        b = deepcopy(original)
        b["manifest"]["ordered_links"][0]["private_source"] = "UNLICENSED"
        with self.assertRaises(ValueError):
            verify_audit_export(b, secret=self.secret)
        b = deepcopy(original)
        b["graph_snapshot_verified"] = True
        with self.assertRaises(ValueError):
            verify_audit_export(b, secret=self.secret)

    def test_wrong_work_direction_missing_work_and_bad_query_keys(self):
        reverse = self.get(source_work_id=RIGHT, target_work_id=LEFT)
        self.assertEqual(reverse.status_code, 200, reverse.text)
        self.assertEqual(reverse.json()["manifest"]["observed_link_count"], 1)
        self.assertEqual(self.get(target_work_id=LEFT).status_code, 422)
        self.assertEqual(self.get(source_work_id="bad").status_code, 422)
        raw = ("/v1/analysis/works/links/audit/export?source_work_id=" +
               LEFT + "&target_work_id=" + RIGHT)
        for suffix in ("&limit=20", "&source_work_id=" + LEFT,
                       "&rights=approved"):
            with self.subTest(suffix=suffix):
                self.assertEqual(self.client.get(
                    raw + suffix, headers=self.headers).status_code, 422)
        del self.store.works[RIGHT]
        self.assertEqual(self.get().status_code, 404)

    def test_unauthenticated_export_blocked_before_graph(self):
        self.store.calls.clear()
        r = self.client.get("/v1/analysis/works/links/audit/export",
                            params={"source_work_id": LEFT,
                                    "target_work_id": RIGHT})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.store.calls, [])

    def test_offline_cli_verifies_without_database_connection(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / "export.json"
            p.write_text(json.dumps(self.get().json()), encoding="utf-8")
            args = ["--input", str(p), "--token-path", str(self.key)]
            self.assertEqual(verify_cli(args), 0)
            wrong = Path(root) / "symlink.json"
            wrong.symlink_to(p)
            self.assertEqual(verify_cli([
                "--input", str(wrong), "--token-path", str(self.key)
            ]), 1)
            p.write_bytes(b"x" * 260000)
            self.assertEqual(verify_cli(args), 1)

    def test_openapi_declares_typed_export_and_release_boundaries(self):
        openapi = self.client.get("/openapi.json").json()
        self.assertIn("/v1/analysis/works/links/audit/export",
                      openapi["paths"])
        self.assertIn("WorkAuditExportEnvelope",
                      openapi["components"]["schemas"])
        b = self.get().json()
        self.assertEqual(set(b), {
            "manifest", "manifest_sha256", "receipt_hmac_sha256",
        })
        self.assertEqual(
            b["manifest"]["observation_scope"],
            "two_sequential_bounded_reads_only",
        )


if __name__ == "__main__":
    unittest.main()
