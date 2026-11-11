"""v0.8.15: S3 HEAD + retention metadata checks with NO AWS network access.

Fake S3 responses test request shapes and precise rejection semantics.
They do not prove a genuine account/object or simulate AWS trust.
"""
from __future__ import annotations

import base64
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.live_s3_version_verify import (
    S3VerificationError, observe_s3_version, verify_observation,
    live_s3_client, main,
)
from tests.test_external_archive_attestation import (
    ExternalArchiveAttestationTests, synthetic_signed_envelope,
)
from scripts.search_capture import digest, encode

CSV = (Path(__file__).resolve().parent / "fixtures" /
       "sefaria_links_synthetic.csv")
TEST_NOW = datetime(2026, 11, 11, 13, 0, tzinfo=timezone.utc)
EXPIRES = datetime(2028, 1, 1, tzinfo=timezone.utc)
ACCOUNT = "123456789012"
REGION = "il-central-1"


class FakeS3:
    def __init__(self, archive_report, *, expires=EXPIRES):
        self.report = archive_report
        self.calls = []
        self.head = {
            "ResponseMetadata": {
                "HTTPStatusCode": 200,
                "RequestId": "SYNTHETIC_HEAD_REQUEST",
            },
            "VersionId": archive_report["version_id"],
            "ContentLength": archive_report["content_length"],
            "ChecksumSHA256": base64.b64encode(
                bytes.fromhex(archive_report["content_sha256"])).decode("ascii"),
            "ChecksumType": "FULL_OBJECT",
            "ObjectLockMode": "COMPLIANCE",
            "ObjectLockRetainUntilDate": expires,
        }
        self.lock = {
            "ResponseMetadata": {
                "HTTPStatusCode": 200,
                "RequestId": "SYNTHETIC_RETENTION_REQUEST",
            },
            "Retention": {
                "Mode": "COMPLIANCE",
                "RetainUntilDate": expires,
            },
        }

    def head_object(self, **kwargs):
        self.calls.append(("head_object", kwargs))
        return copy.deepcopy(self.head)

    def get_object_retention(self, **kwargs):
        self.calls.append(("get_object_retention", kwargs))
        return copy.deepcopy(self.lock)


class LiveS3VersionTests(unittest.TestCase):
    def setUp(self):
        self.fx = ExternalArchiveAttestationTests(
            "test_valid_ephemeral_key_proves_only_pinned_signature")
        self.fx.setUp()
        self.signed = synthetic_signed_envelope(
            self.fx.policy, self.fx.statement, self.fx.signer)
        self.client = FakeS3(self.fx.report)

    def call(self, *, client=None, policy=None, report=None,
             statement=None, witness=None, receipt=None, source_file=CSV,
             account=ACCOUNT, region=REGION, now=TEST_NOW, key=None):
        return observe_s3_version(
            self.client if client is None else client,
            policy=self.fx.policy if policy is None else policy,
            report=self.fx.report if report is None else report,
            statement=self.signed if statement is None else statement,
            record=self.fx.record,
            receipt=self.fx.receipt if receipt is None else receipt,
            witness=self.fx.witness if witness is None else witness,
            capture=self.fx.capture,
            source_file=source_file,
            local_key=self.fx.check.__globals__["KEY"] if key is None else key,
            account=account, region=region, observed_at=now)

    def verify_offline(self, obj, *, key=None, account=ACCOUNT, region=REGION):
        return verify_observation(
            obj, policy=self.fx.policy, report=self.fx.report,
            statement=self.signed, record=self.fx.record,
            receipt=self.fx.receipt, witness=self.fx.witness,
            capture=self.fx.capture, source_file=CSV,
            local_key=self.fx.check.__globals__["KEY"] if key is None else key,
            account=account, region=region)

    def test_complete_version_pinned_reads_match_full_object_sha_and_compliance(self):
        result = self.call()
        self.assertTrue(result["aws_full_object_sha256_matched"])
        self.assertTrue(result["aws_versioned_head_observed"])
        self.assertTrue(result["aws_compliance_retention_read_observed"])
        self.assertFalse(result["external_archive_immutability_end_to_end_verified"])
        self.assertFalse(result["signed_provider_identity_independently_verified"])
        self.assertEqual(result["research_release_status"], "HOLD")
        self.assertEqual(result["head_sha256"],
                         self.fx.receipt["observed_raw_file_sha256"])
        self.verify_offline(result)
        self.assertEqual(len(self.client.calls), 2)
        self.assertEqual(self.client.calls[0][0], "head_object")
        self.assertEqual(self.client.calls[1][0], "get_object_retention")
        args = self.client.calls[0][1]
        self.assertEqual(args["Bucket"], self.fx.report["bucket"])
        self.assertEqual(args["Key"], self.fx.report["object_key"])
        self.assertEqual(args["VersionId"], self.fx.report["version_id"])
        self.assertEqual(args["ExpectedBucketOwner"], ACCOUNT)
        self.assertEqual(args["ChecksumMode"], "ENABLED")
        self.assertEqual(self.client.calls[1][1], {
            k: args[k] for k in ("Bucket", "Key", "VersionId",
                                  "ExpectedBucketOwner")
        })
        data = json.dumps(result)
        self.assertNotIn(self.fx.report["bucket"], data)
        self.assertNotIn(self.fx.report["object_key"], data)
        self.assertNotIn(self.fx.report["version_id"], data)
        self.assertNotIn(ACCOUNT, data)

    def test_wrong_object_version_or_delete_marker_rejected(self):
        for change in ({"VersionId": "other-version"},
                       {"DeleteMarker": True},
                       {"VersionId": None},
                       {"ContentLength": self.fx.report["content_length"] + 1}):
            with self.subTest(change=change):
                fake = FakeS3(self.fx.report)
                fake.head.update(change)
                with self.assertRaises(S3VerificationError):
                    self.call(client=fake)

    def test_no_etag_fallback_or_multipart_composite_checksum(self):
        for change in (
            {"ChecksumType": "COMPOSITE"},
            {"ChecksumType": None},
            {"ChecksumSHA256": None},
            {"ChecksumSHA256": "not_base64"},
            {"ChecksumSHA256": base64.b64encode(b"wrong").decode()},
            {"ChecksumSHA256": base64.b64encode(b"\x00"*32).decode()},
        ):
            with self.subTest(change=change):
                fake = FakeS3(self.fx.report)
                fake.head.update({"ETag": self.fx.report["content_sha256"]})
                fake.head.update(change)
                with self.assertRaises(S3VerificationError):
                    self.call(client=fake)

    def test_get_retention_and_head_must_match_compliance_and_expiry(self):
        for head_mod, lock_mod in (
            ({"ObjectLockMode": "GOVERNANCE"}, {}),
            ({}, {"Retention": {"Mode": "GOVERNANCE",
                               "RetainUntilDate": EXPIRES}}),
            ({"ObjectLockRetainUntilDate": datetime(
                2027, 1, 1, tzinfo=timezone.utc)}, {}),
            ({}, {"Retention": {"Mode": "COMPLIANCE",
                               "RetainUntilDate": datetime(
                                   2027, 1, 1, tzinfo=timezone.utc)}}),
            ({}, {"Retention": {}}),
            ({"ObjectLockMode": None}, {}),
        ):
            fake = FakeS3(self.fx.report)
            fake.head.update(head_mod)
            fake.lock.update(lock_mod)
            with self.subTest(head=head_mod, lock=lock_mod):
                with self.assertRaises(S3VerificationError):
                    self.call(client=fake)

    def test_undated_expired_and_unauthenticated_provider_errors_fail_closed(self):
        fake = FakeS3(self.fx.report)
        fake.head["ResponseMetadata"]["HTTPStatusCode"] = 403
        with self.assertRaises(S3VerificationError):
            self.call(client=fake)
        fake = FakeS3(self.fx.report)
        fake.lock["ResponseMetadata"]["RequestId"] = ""
        with self.assertRaises(S3VerificationError):
            self.call(client=fake)
        fake = FakeS3(self.fx.report)
        fake.lock["Retention"]["RetainUntilDate"] = "2028-01-01T00:00:00Z"
        with self.assertRaises(S3VerificationError):
            self.call(client=fake)
        with self.assertRaises(S3VerificationError):
            self.call(now=datetime(2028, 1, 2, tzinfo=timezone.utc))

    def test_aws_client_exception_without_leaking_bucket(self):
        class Denied:
            def head_object(self, **kwargs):
                raise RuntimeError("private bucket should stay private")
        with self.assertRaises(S3VerificationError) as x:
            self.call(client=Denied())
        self.assertNotIn(self.fx.report["bucket"], str(x.exception))

    def test_no_s3_requests_if_signed_source_chain_invalid(self):
        altered = copy.deepcopy(self.fx.witness)
        altered["source_record_id"] = "source:" + "0"*64
        with self.assertRaises(S3VerificationError):
            self.call(witness=altered)
        self.assertEqual(self.client.calls, [])
        altered = copy.deepcopy(self.signed)
        altered["signature_b64"] = base64.b64encode(b"\x00"*64).decode()
        with self.assertRaises(S3VerificationError):
            self.call(statement=altered)
        self.assertEqual(self.client.calls, [])

    def test_governance_claim_cannot_be_promoted_to_compliance(self):
        report = copy.deepcopy(self.fx.report)
        report["object_lock_mode"] = "GOVERNANCE"
        # v0.8.14 signature explicitly signs the original report SHA, so
        # wrong report is already rejected even before the AWS request.
        with self.assertRaises(S3VerificationError):
            self.call(report=report)
        self.assertEqual(self.client.calls, [])

    def test_offline_replay_hmac_and_scope_tampering_rejected(self):
        saved = self.call()
        for key, val in (
            ("head_sha256", "0"*64),
            ("aws_region", "us-east-1"),
            ("research_release_status", "APPROVED"),
            ("external_archive_immutability_end_to_end_verified", True),
            ("observation_hmac", "f"*64),
            ("observed_version_id_sha256", "0"*64),
        ):
            changed = copy.deepcopy(saved)
            changed[key] = val
            with self.subTest(key=key), self.assertRaises(S3VerificationError):
                self.verify_offline(changed)
        with self.assertRaises(S3VerificationError):
            self.verify_offline(saved, account="000000000000")
        with self.assertRaises(S3VerificationError):
            self.verify_offline(saved, key="wrong-local-hmac-"+"x"*55)

    def test_account_and_region_are_pinned(self):
        for kwargs in ({"account": "invalid"},
                       {"region": "http://localhost"},
                       {"region": "il-central-1.attacker.example"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(S3VerificationError):
                self.call(**kwargs)

    def test_sdk_endpoint_is_fixed_https_and_profile_is_explicit(self):
        class Client:
            pass
        class Session:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
            def client(self, service, **kwargs):
                Session.request = (service, kwargs)
                return Client()
        # boto3 is imported within live_s3_client, yet there is no
        # actual AWS HTTP call because Session is mocked.
        with patch("boto3.Session", Session):
            live_s3_client(profile="research-archive",
                           region=REGION, account=ACCOUNT)
        service, kwargs = Session.request
        self.assertEqual(service, "s3")
        self.assertEqual(kwargs["endpoint_url"],
                         "https://s3.il-central-1.amazonaws.com")
        self.assertEqual(kwargs["region_name"], REGION)
        self.assertEqual(kwargs["config"].signature_version, "s3v4")
        with self.assertRaises(S3VerificationError):
            live_s3_client(profile="bad/profile", region=REGION, account=ACCOUNT)

    def test_cli_requires_explicit_authorization_before_reading_any_file(self):
        self.assertEqual(main(["inspect"]), 2) if False else None
        # argparse requires all args; use a fully formed invocation so the
        # acknowledgement gate, not parsing, causes the expected rejection.
        base = [
            "--source-file", str(CSV),
            "--source-record", "/does/not/exist",
            "--receipt", "/does/not/exist",
            "--witness", "/does/not/exist",
            "--capture-manifest", "/does/not/exist",
            "--trusted-policy", "/does/not/exist",
            "--archive-report", "/does/not/exist",
            "--signed-statement", "/does/not/exist",
            "--aws-region", REGION,
            "--expected-bucket-owner", ACCOUNT,
            "--aws-profile", "synthetic-ci",
            "--output", "/does/not/exist",
        ]
        self.assertEqual(main(["inspect", *base]), 2)

    def test_private_observation_reverification_cli(self):
        result = self.call()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            files = {
                "record.json": self.fx.record,
                "receipt.json": self.fx.receipt,
                "witness.json": self.fx.witness,
                "capture.json": self.fx.capture,
                "policy.json": self.fx.policy,
                "report.json": self.fx.report,
                "signed.json": self.signed,
                "observation.json": result,
            }
            for filename, content in files.items():
                (root / filename).write_text(
                    json.dumps(content, ensure_ascii=False), encoding="utf-8")
            keyfile = root / "local.key"
            keyfile.write_text(self.fx.check.__globals__["KEY"])
            os.chmod(keyfile, 0o600)
            args = [
                "--source-file", str(CSV),
                "--source-record", str(root/"record.json"),
                "--receipt", str(root/"receipt.json"),
                "--witness", str(root/"witness.json"),
                "--capture-manifest", str(root/"capture.json"),
                "--trusted-policy", str(root/"policy.json"),
                "--archive-report", str(root/"report.json"),
                "--signed-statement", str(root/"signed.json"),
                "--aws-region", REGION,
                "--expected-bucket-owner", ACCOUNT,
                "--local-key-file", str(keyfile),
                "--observation", str(root/"observation.json"),
            ]
            self.assertEqual(main(["verify", *args]), 0)
            changed = copy.deepcopy(result)
            changed["aws_full_object_sha256_matched"] = False
            (root/"observation.json").write_text(json.dumps(changed))
            self.assertEqual(main(["verify", *args]), 2)


if __name__ == "__main__":
    unittest.main()
