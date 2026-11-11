"""v0.8.14 Ed25519 pinned archive attestation over synthetic source chain."""
from __future__ import annotations

import base64
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from scripts.external_archive_attestation import (
    AttestationError, DOMAIN, _strict_json, verify_attestation, main,
)
from scripts.search_capture import collect, digest, encode
from scripts.search_quality_eval import read_evidence
from scripts.search_revision import observe_projection
from scripts.search_provenance import observe_provenance
from scripts.source_receipts import MODES, issue_receipt
from scripts.source_membership import issue_witness
from tests.test_source_membership import fixture_record
from tests.test_source_provenance import CombinedAPI

FIX = Path(__file__).resolve().parent / "fixtures"
CSV = FIX / "sefaria_links_synthetic.csv"
CATALOG = FIX / "search_review_questions_synthetic.json"
CAPTURES = FIX / "search_quality_responses_synthetic.json"
KEY = "synthetic-local-capture-hmac-" + "z" * 55


def synthetic_signed_envelope(policy, statement, signer):
    return {
        "statement": statement,
        "signature_b64": base64.b64encode(
            signer.sign(DOMAIN + encode(statement))).decode("ascii"),
    }


class ExternalArchiveAttestationTests(unittest.TestCase):
    def setUp(self):
        catalog, catalog_sha = read_evidence(CATALOG)
        responses, _ = read_evidence(CAPTURES)
        api = CombinedAPI(responses)
        self.record = fixture_record()
        api.store.rows["sources"] = [copy.deepcopy(self.record)]
        _, self.capture = collect(
            catalog, api, mode="scan", catalog_sha=catalog_sha, key=KEY,
            revision_probe=lambda: observe_projection(catalog, api, mode="scan"),
            provenance_probe=lambda: observe_provenance(api))
        self.receipt = issue_receipt(
            self.record, CSV, mode=MODES[0], key=KEY,
            capture_manifest=self.capture)
        self.witness = issue_witness(
            self.record, self.receipt, CSV, self.capture, api, key=KEY)
        self.signer = Ed25519PrivateKey.generate()
        self.public_bytes = self.signer.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw)
        self.policy = {
            "schema_version": "0.8.14",
            "trust_status": "OPERATOR_PINNED_IDENTITY_NOT_ATTESTED",
            "signers": [{
                "signer_id": "synthetic_archive_ci",
                "role": "archive_operator",
                "archive_namespace": "synthetic_archived_sources",
                "ed25519_public_key_b64": base64.b64encode(
                    self.public_bytes).decode("ascii"),
            }],
        }
        self.report = {
            "schema_version": "0.8.14",
            "provider": "s3_object_lock",
            "bucket": "fixture-archive-bucket",
            "object_key": "research/fixtures/link-metadata.csv",
            "version_id": "synthetic-version-id-not-real",
            "content_sha256": self.receipt["observed_raw_file_sha256"],
            "content_length": self.receipt["observed_file_size_bytes"],
            "object_lock_mode": "COMPLIANCE",
            "retain_until_utc": "2028-01-01T00:00:00Z",
            "evidence_origin": "operator_supplied_unverified",
        }
        self.statement = {
            "schema_version": "0.8.14",
            "purpose": "archival_operator_attests_report_claim",
            "signer_id": "synthetic_archive_ci",
            "archive_namespace": "synthetic_archived_sources",
            "source_record_id": self.record["id"],
            "source_receipt_sha256": digest(encode(self.receipt)),
            "source_witness_sha256": digest(encode(self.witness)),
            "capture_manifest_sha256": digest(encode(self.capture)),
            "archive_report_sha256": digest(encode(self.report)),
            "issued_at_utc": "2026-11-11T12:00:00Z",
            "provider_identity_independently_verified": False,
            "source_rights_verified": False,
            "research_release_status": "HOLD",
        }

    def check(self, *, policy=None, report=None, statement=None,
              envelope=None, receipt=None, witness=None, capture=None,
              record=None, source_file=CSV, key=KEY):
        final_policy = self.policy if policy is None else policy
        final_report = self.report if report is None else report
        final_statement = self.statement if statement is None else statement
        signed = (synthetic_signed_envelope(
            final_policy, final_statement, self.signer)
                  if envelope is None else envelope)
        return verify_attestation(
            final_policy, final_report, signed,
            source_record=self.record if record is None else record,
            receipt=self.receipt if receipt is None else receipt,
            witness=self.witness if witness is None else witness,
            capture=self.capture if capture is None else capture,
            source_file=source_file, local_key=key)

    def test_valid_ephemeral_key_proves_only_pinned_signature(self):
        result = self.check()
        self.assertTrue(result["pinned_key_signature_valid"])
        self.assertTrue(result["operator_key_possession_proven"])
        for flag in (
            "signer_organization_identity_independently_verified",
            "remote_object_existence_independently_verified",
            "s3_object_lock_configuration_independently_verified",
            "external_archive_immutability_verified",
            "source_provider_identity_verified", "source_rights_verified",
            "neo4j_snapshot_isolation_verified",
        ):
            self.assertFalse(result[flag])
        self.assertEqual(result["research_release_status"], "HOLD")
        self.assertNotIn("fixture-archive-bucket", json.dumps(result))
        self.assertNotIn("research/fixtures", json.dumps(result))

    def test_real_ed25519_signatures_reject_modified_signed_claim(self):
        envelope = synthetic_signed_envelope(
            self.policy, self.statement, self.signer)
        bad = copy.deepcopy(envelope)
        bad["statement"]["source_witness_sha256"] = "0" * 64
        with self.assertRaises(AttestationError):
            self.check(envelope=bad)
        bad = copy.deepcopy(envelope)
        bad["signature_b64"] = base64.b64encode(b"\x00"*64).decode("ascii")
        with self.assertRaises(AttestationError):
            self.check(envelope=bad)
        bad = copy.deepcopy(envelope)
        bad["statement"]["source_rights_verified"] = True
        with self.assertRaises(AttestationError):
            self.check(envelope=bad)

    def test_untrusted_key_or_signer_scope_is_denied(self):
        alt = Ed25519PrivateKey.generate()
        other = copy.deepcopy(self.policy)
        other["signers"][0]["ed25519_public_key_b64"] = base64.b64encode(
            alt.public_key().public_bytes(
                Encoding.Raw, PublicFormat.Raw)).decode("ascii")
        with self.assertRaises(AttestationError):
            self.check(policy=other)
        other = copy.deepcopy(self.policy)
        other["signers"][0]["archive_namespace"] = "another_archive"
        with self.assertRaises(AttestationError):
            self.check(policy=other)
        other = copy.deepcopy(self.policy)
        other["signers"][0]["role"] = "source_provider"
        with self.assertRaises(AttestationError):
            self.check(policy=other)
        other = copy.deepcopy(self.policy)
        other["signers"].append(copy.deepcopy(other["signers"][0]))
        with self.assertRaises(AttestationError):
            self.check(policy=other)
        other = copy.deepcopy(self.policy)
        other["trust_status"] = "EXTERNAL_PROVIDER_AUTHENTICATED"
        with self.assertRaises(AttestationError):
            self.check(policy=other)

    def test_archive_report_is_data_not_verified_object_lock(self):
        altered = copy.deepcopy(self.report)
        altered["object_lock_mode"] = "DISABLED"
        with self.assertRaises(AttestationError):
            self.check(report=altered)
        altered = copy.deepcopy(self.report)
        altered["content_sha256"] = "f" * 64
        with self.assertRaises(AttestationError):
            self.check(report=altered)
        altered = copy.deepcopy(self.report)
        altered["version_id"] = ""
        with self.assertRaises(AttestationError):
            self.check(report=altered)
        altered = copy.deepcopy(self.report)
        altered["retain_until_utc"] = "2024-01-01T00:00:00Z"
        with self.assertRaises(AttestationError):
            self.check(report=altered)
        altered = copy.deepcopy(self.report)
        altered["evidence_origin"] = "aws_verified"
        with self.assertRaises(AttestationError):
            self.check(report=altered)
        altered = copy.deepcopy(self.report)
        altered["content_length"] = True
        with self.assertRaises(AttestationError):
            self.check(report=altered)

    def test_cross_capture_or_witness_replay_rejected(self):
        changed = copy.deepcopy(self.witness)
        changed["research_release_status"] = "APPROVED"
        with self.assertRaises(AttestationError):
            self.check(witness=changed)
        changed = copy.deepcopy(self.capture)
        changed["request_count"] += 1
        with self.assertRaises(AttestationError):
            self.check(capture=changed)
        changed = copy.deepcopy(self.receipt)
        changed["observed_file_size_bytes"] += 1
        with self.assertRaises(AttestationError):
            self.check(receipt=changed)

    def test_private_file_mode_and_strict_duplicate_json_policy(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path = root / "policy.json"
            path.write_text('{"schema_version":"0.8.14","schema_version":"0.8.14"}')
            with self.assertRaises(AttestationError):
                _strict_json(path, 1024)
            path.write_text(json.dumps(self.policy))
            os.chmod(path, 0o666)
            with self.assertRaises(AttestationError):
                _strict_json(path, 2048)
            os.chmod(path, 0o600)
            self.assertEqual(_strict_json(path, 2048), self.policy)
            alias = root / "alias.json"
            alias.symlink_to(path)
            with self.assertRaises(AttestationError):
                _strict_json(alias, 2048)

    def test_cli_offline_private_report_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            files = {
                "record.json": self.record,
                "receipt.json": self.receipt,
                "witness.json": self.witness,
                "capture.json": self.capture,
                "policy.json": self.policy,
                "report.json": self.report,
                "signed.json": synthetic_signed_envelope(
                    self.policy, self.statement, self.signer),
            }
            for filename, data in files.items():
                (root / filename).write_text(
                    json.dumps(data, ensure_ascii=False), encoding="utf-8")
            secret = root / "local.key"
            secret.write_text(KEY)
            os.chmod(secret, 0o600)
            output = root / "attestation_result.json"
            flags = [
                "--source-file", str(CSV),
                "--source-record", str(root / "record.json"),
                "--receipt", str(root / "receipt.json"),
                "--witness", str(root / "witness.json"),
                "--capture-manifest", str(root / "capture.json"),
                "--trusted-policy", str(root / "policy.json"),
                "--archive-report", str(root / "report.json"),
                "--signed-statement", str(root / "signed.json"),
                "--local-key-file", str(secret),
                "--output", str(output),
            ]
            self.assertEqual(main(flags), 0)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            frozen = output.read_bytes()
            self.assertEqual(main(flags), 2)
            self.assertEqual(output.read_bytes(), frozen)


if __name__ == "__main__":
    unittest.main()
