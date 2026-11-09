"""Offline v0.6 DvirOS BFF contract checks (no live corpus/credentials)."""
from __future__ import annotations
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts/dviros-research/v1/contract.json"
FIXTURE = ROOT / "contracts/dviros-research/v1/synthetic-fixture.json"

class DvirOSContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_version_and_policy(self):
        self.assertEqual(self.contract["contract_version"], "1.0.0")
        self.assertEqual(self.contract["upstream_api_schema_version"], "0.5.0")
        self.assertEqual(self.contract["methods"], ["GET"])
        self.assertFalse(self.contract["auth"]["anonymous_live_access"])
        self.assertFalse(self.contract["auth"]["live_default_enabled"])
        self.assertLessEqual(self.contract["limits"]["graph_depth_max"], 2)

    def test_all_paths_are_constrained_to_public_read_endpoints(self):
        from services.research_api.app import create_app
        routes = set(create_app().openapi()["paths"])
        self.assertEqual(len(self.contract["resources"]), 12)
        self.assertEqual(len({item["path"] for item in self.contract["resources"]}), 12)
        for route in self.contract["resources"]:
            self.assertIn(route["upstream"], routes)
            self.assertEqual(list(create_app().openapi()["paths"][route["upstream"]]), ["get"])
            self.assertNotIn("cypher", route["upstream"])

    def test_synthetic_data_cannot_imply_rights_or_approved_research(self):
        data = self.fixture
        self.assertTrue(data["synthetic"])
        self.assertEqual(data["work_page"]["schema_version"], "0.5.0")
        self.assertEqual(data["data_status"]["schema_version"], "0.5.0")
        self.assertFalse(data["data_status"]["human_quality_release_approved"])
        self.assertFalse(data["data_status"]["texts_available"])
        self.assertEqual(data["work_page"]["corpus_status"], "unreviewed_metadata_only")
        self.assertTrue(all(record["provider"] == "fixture" for record in data["work_page"]["items"]))
        self.assertEqual(data["source_trail"]["review_status"], "unreviewed")

if __name__ == "__main__":
    unittest.main()
