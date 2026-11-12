"""v0.10.0 evidence-bounded DvirOS study packet preview and safe CSV tests."""
from __future__ import annotations

from copy import deepcopy
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from research_graph.ontology import stable_id
from scripts.verify_study_packet_v0100 import (
    citation_csv, main as cli,
)
from services.research_api.app import create_app
from services.research_api.config import bootstrap_token, load_token
from services.research_api.db import DatabaseUnavailable
from services.research_api.study_packets_v0100 import (
    MAX_SELECT, StudyPacketError, parse_evidence_selector,
    preview_study_packet, verify_study_packet,
)
from tests.test_work_comparison import LEFT, RIGHT, edge
from tests.test_work_link_audit_v099 import AuditStore


class StudyPacketTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.key = Path(temp.name) / "token"
        bootstrap_token(self.key)
        self.secret = load_token(self.key)
        self.store = AuditStore()
        self.client = TestClient(create_app(
            backend=self.store, token_path=self.key,
        ))
        self.auth = {"Authorization": "Bearer " + self.secret}
        self.ids = ",".join(sorted(
            row["evidence_id"] for row in self.store.forward[:2]
        ))

    def get(self, *, evidence_ids=None, **changes):
        params = {
            "source_work_id": LEFT,
            "target_work_id": RIGHT,
            "evidence_ids": self.ids if evidence_ids is None else evidence_ids,
        }
        params.update(changes)
        return self.client.get(
            "/v1/research/study-packets/preview",
            params=params, headers=self.auth,
        )

    def test_two_citations_and_exact_audit_provenance(self):
        response = self.get()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        packet = body["packet"]
        self.assertEqual(packet["schema_version"], "0.10.0")
        self.assertEqual(packet["citation_count"], 2)
        self.assertEqual(packet["selected_evidence_ids"], self.ids.split(","))
        self.assertEqual(packet["audit_manifest_sha256"],
                         body["audit_export"]["manifest_sha256"])
        self.assertEqual(packet["research_release_status"], "HOLD")
        self.assertEqual(packet["annotation_write_status"],
                         "PREVIEW_ONLY_DVIROS_OWNED")
        self.assertEqual(packet["review_decision_status"],
                         "NO_DECISION_RECORDED")
        self.assertFalse(packet["dviros_postgres_record_created"])
        self.assertFalse(packet["graph_snapshot_verified"])
        self.assertFalse(packet["licensed_source_rights_verified"])
        for citation in packet["citations"]:
            self.assertEqual(citation["claim_kind"], "OBSERVED_SOURCE_LINK")
            self.assertEqual(citation["citation_scope"],
                             "metadata_reference_only")
            self.assertFalse(citation["interpretation_human_approved"])
            self.assertFalse(citation["source_rights_verified"])
            self.assertEqual(citation["rights_tag"], "UNREVIEWED")
        proof = verify_study_packet(body, secret=self.secret)
        self.assertTrue(proof["all_citations_present_in_signed_audit"])
        self.assertFalse(proof["study_persisted_to_postgres"])
        self.assertEqual([name for name, _ in self.store.calls].count(
            "analysis_work_cross_link_page"), 2)

    def test_offline_replay_does_not_query_database(self):
        bundle = self.get().json()
        self.store.calls.clear()
        checked = verify_study_packet(bundle, secret=self.secret)
        self.assertTrue(checked["service_hmac_verified"])
        self.assertEqual(self.store.calls, [])

    def test_missing_or_other_work_evidence_refuses(self):
        missing = stable_id("evidence", "synthetic", "not-present")
        self.assertEqual(self.get(evidence_ids=missing).status_code, 404)
        reverse = self.get(source_work_id=RIGHT, target_work_id=LEFT)
        self.assertEqual(reverse.status_code, 404)

    def test_untrusted_selection_denied_before_graph(self):
        a, b = self.ids.split(",")
        invalid = (
            "", "not-id", LEFT, a + "," + a,
            b + "," + a,
            "," + a, a + ",",
            ",".join(stable_id("evidence", "v0100", str(i))
                     for i in range(MAX_SELECT + 1)),
        )
        for item in invalid:
            with self.subTest(item=item[:80]):
                self.store.calls.clear()
                self.assertEqual(
                    self.get(evidence_ids=item).status_code, 422)
                self.assertEqual(self.store.calls, [])

    def test_query_key_and_authentication_denials(self):
        self.store.calls.clear()
        raw = "/v1/research/study-packets/preview"
        params = {
            "source_work_id": LEFT, "target_work_id": RIGHT,
            "evidence_ids": self.ids,
        }
        self.assertEqual(
            self.client.get(raw, params=params).status_code, 401)
        self.assertEqual(self.store.calls, [])
        for addition in (
            "&rights=approved", "&source_work_id=" + LEFT,
            "&evidence_ids=" + self.ids, "&save=true",
        ):
            with self.subTest(addition=addition):
                target = (raw + "?source_work_id=" + LEFT +
                          "&target_work_id=" + RIGHT +
                          "&evidence_ids=" + self.ids + addition)
                self.assertEqual(self.client.get(
                    target, headers=self.auth).status_code, 422)
                self.assertEqual(self.store.calls, [])
        self.assertEqual(self.client.post(
            raw, json=params, headers=self.auth).status_code, 405)
        self.assertEqual(self.store.calls, [])

    def test_all_twelve_evidence_links_allowed(self):
        self.store.forward = [
            edge(f"study-{i:03d}") for i in range(MAX_SELECT)
        ]
        ids = ",".join(sorted(row["evidence_id"]
                              for row in self.store.forward))
        response = self.get(evidence_ids=ids)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["packet"]["citation_count"], 12)
        self.assertEqual(len(response.json()["packet"]["annotation_slots"]), 12)

    def test_100_link_audit_with_twelve_selected_is_still_bounded(self):
        self.store.forward = [edge(f"broad-study-{i:03d}")
                              for i in range(100)]
        subset = sorted(x["evidence_id"]
                        for x in self.store.forward)[:12]
        response = self.get(evidence_ids=",".join(subset))
        self.assertEqual(response.status_code, 200, response.text)
        packet = response.json()
        self.assertEqual(packet["packet"]["citation_count"], 12)
        self.assertEqual(
            packet["audit_export"]["manifest"]["observed_link_count"], 100)
        self.assertEqual(sum(
            op == "analysis_work_cross_link_page"
            for op, _ in self.store.calls), 10)

    def test_101_unbounded_work_links_fail_without_packet(self):
        self.store.forward = [edge(f"over-study-{i:03d}") for i in range(101)]
        selection = self.store.forward[0]["evidence_id"]
        self.assertEqual(
            self.get(evidence_ids=selection).status_code, 503)

    def test_changes_between_audit_passes_return_409(self):
        class DriftStore(AuditStore):
            def __init__(self):
                super().__init__()
                self.calls_seen = 0

            def query(self, name, params):
                if name == "analysis_work_cross_link_page":
                    self.calls_seen += 1
                    if self.calls_seen == 2:
                        self.forward[0]["evidence_review_status"] = "disputed"
                return super().query(name, params)
        store = DriftStore()
        client = TestClient(create_app(backend=store, token_path=self.key))
        self.assertEqual(client.get(
            "/v1/research/study-packets/preview",
            params={"source_work_id": LEFT, "target_work_id": RIGHT,
                    "evidence_ids": self.ids},
            headers=self.auth).status_code, 409)

    def test_tamper_evidence_review_and_license_flags_fail(self):
        original = self.get().json()
        for update in (
            ("citations", "edge_review_status", "rejected"),
            ("citations", "rights_tag", "LICENSED"),
            ("citations", "interpretation_human_approved", True),
            ("packet", "dviros_postgres_record_created", True),
            ("packet", "research_release_status", "PASS"),
            ("packet", "review_decision_status", "APPROVED"),
        ):
            with self.subTest(update=update):
                modified = deepcopy(original)
                kind, key, value = update
                if kind == "citations":
                    modified["packet"]["citations"][0][key] = value
                else:
                    modified["packet"][key] = value
                with self.assertRaises(StudyPacketError):
                    verify_study_packet(modified, secret=self.secret)

    def test_wrong_key_missing_evidence_and_extra_fields_fail(self):
        original = self.get().json()
        with self.assertRaises(StudyPacketError):
            verify_study_packet(original, secret="Z" * 48)
        broken = deepcopy(original)
        broken["packet"]["selected_evidence_ids"] = [
            stable_id("evidence", "not-present")
        ]
        with self.assertRaises(StudyPacketError):
            verify_study_packet(broken, secret=self.secret)
        broken = deepcopy(original)
        broken["packet"]["private_user_note"] = "Do not publish"
        with self.assertRaises(StudyPacketError):
            verify_study_packet(broken, secret=self.secret)
        broken = deepcopy(original)
        selected = broken["audit_export"]["manifest"]["ordered_links"][0]
        previous = selected["evidence_review_status"]
        selected["evidence_review_status"] = (
            "rejected" if previous != "rejected" else "approved"
        )
        self.assertNotEqual(selected["evidence_review_status"], previous)
        with self.assertRaises(StudyPacketError):
            verify_study_packet(broken, secret=self.secret)

    def test_csv_formula_hardening_and_minimal_metadata(self):
        bundle = self.get().json()
        draft = deepcopy(bundle["packet"])
        draft["citations"][0]["source_ref"] = "=SUM(A1:A2)"
        draft["citations"][0]["target_ref"] = "@danger"
        csv_bytes = citation_csv(draft)
        parsed = list(csv.DictReader(io.StringIO(csv_bytes.decode("utf-8"))))
        self.assertTrue(parsed[0]["source_ref"].startswith("'="))
        self.assertTrue(parsed[0]["target_ref"].startswith("'@"))
        self.assertIn("evidence_id", parsed[0])
        self.assertNotIn("draft_note", parsed[0])
        self.assertNotIn("reviewer_id", parsed[0])

    def test_offline_cli_verify_and_csv_are_private_create_only(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            packet = folder / "study.json"
            csv_path = folder / "citations.csv"
            packet.write_text(json.dumps(self.get().json()), encoding="utf-8")
            packet.chmod(0o600)
            args = ["--input", str(packet), "--token-path", str(self.key)]
            self.assertEqual(cli(["verify", *args]), 0)
            self.assertEqual(cli(["csv", *args, "--output", str(csv_path)]), 0)
            self.assertEqual(cli(["csv", *args, "--output", str(csv_path)]), 1)
            self.assertTrue(csv_path.read_bytes().startswith(b"edge_id,"))
            self.assertEqual(csv_path.stat().st_mode & 0o777, 0o600)
            symlink = folder / "alias.json"
            symlink.symlink_to(packet)
            self.assertEqual(cli([
                "verify", "--input", str(symlink),
                "--token-path", str(self.key)]), 1)
            packet.chmod(0o644)
            self.assertEqual(cli(["verify", *args]), 1)

    def test_openapi_schema_and_never_store_research_note(self):
        paths = self.client.get("/openapi.json").json()
        self.assertIn("/v1/research/study-packets/preview", paths["paths"])
        self.assertIn("StudyPacketEnvelope", paths["components"]["schemas"])
        self.assertIn("DraftStudyPacket", paths["components"]["schemas"])
        body = self.get().json()
        self.assertTrue(all(
            slot["draft_note"] is None and
            slot["reviewer_id"] is None and
            slot["state"] == "NOT_SAVED"
            for slot in body["packet"]["annotation_slots"]
        ))


if __name__ == "__main__":
    unittest.main()
