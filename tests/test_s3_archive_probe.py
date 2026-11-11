"""v0.8.15: synthetic-only, zero-network checks of AWS metadata boundaries."""
from __future__ import annotations

import base64
import copy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.s3_archive_probe import S3ProbeError, _aws_client, verify_s3_metadata
from tests.test_external_archive_attestation import ExternalArchiveAttestationTests


class FakeS3:
    def __init__(self, report, receipt):
        self.calls = []
        self.head = {
            "ResponseMetadata": {"HTTPStatusCode": 200},
            "VersionId": report["version_id"],
            "ContentLength": receipt["observed_file_size_bytes"],
            "ChecksumType": "FULL_OBJECT",
            "ChecksumSHA256": base64.b64encode(
                bytes.fromhex(receipt["observed_raw_file_sha256"])).decode(),
            "ObjectLockMode": report["object_lock_mode"],
            "ObjectLockRetainUntilDate": datetime(2028, 1, 1, tzinfo=timezone.utc),
        }
        self.retention = {
            "ResponseMetadata": {"HTTPStatusCode": 200},
            "Retention": {"Mode": report["object_lock_mode"],
                          "RetainUntilDate": datetime(2028, 1, 1, tzinfo=timezone.utc)},
        }

    def head_object(self, **kwargs):
        self.calls.append(("head", kwargs))
        return self.head

    def get_object_retention(self, **kwargs):
        self.calls.append(("retention", kwargs))
        return self.retention


class VersionedS3EvidenceTests(unittest.TestCase):
    def setUp(self):
        # Exercise the real 0.8.14 signed/witness path with disposable data,
        # then test the NEW S3 response boundary with a fake SDK client.
        previous = ExternalArchiveAttestationTests()
        previous.setUp()
        self.assertTrue(previous.check()["pinned_key_signature_valid"])
        self.receipt = previous.receipt
        self.report = previous.report
        self.client = FakeS3(self.report, self.receipt)
        self.now = datetime(2026, 11, 11, tzinfo=timezone.utc)

    def verify(self, report=None, receipt=None, owner="123456789012", now=None):
        return verify_s3_metadata(
            self.client, self.report if report is None else report,
            self.receipt if receipt is None else receipt,
            expected_bucket_owner=owner, now_utc=self.now if now is None else now)

    def test_valid_version_scoped_checks_and_no_elevation(self):
        result = self.verify()
        self.assertTrue(result["s3_full_object_sha256_matched"])
        self.assertTrue(result["s3_independent_retention_api_matched"])
        self.assertFalse(result["external_archive_immutability_verified"])
        self.assertEqual(result["research_release_status"], "HOLD")
        self.assertNotIn(self.report["bucket"], str(result))
        self.assertEqual(len(self.client.calls), 2)
        a, b = self.client.calls
        self.assertEqual(a[0], "head")
        self.assertEqual(b[0], "retention")
        self.assertEqual(a[1]["ChecksumMode"], "ENABLED")
        for request in (a[1], b[1]):
            self.assertEqual(request["VersionId"], self.report["version_id"])
            self.assertEqual(request["ExpectedBucketOwner"], "123456789012")
            self.assertEqual(request["Key"], self.report["object_key"])

    def test_sha256_composite_missing_or_wrong_denied(self):
        for change in ({"ChecksumType": "COMPOSITE"},
                       {"ChecksumType": None}, {"ChecksumSHA256": ""},
                       {"ChecksumSHA256": base64.b64encode(b"\x00"*32).decode()},
                       {"ChecksumSHA256": "!not-base64!"}):
            with self.subTest(change=change):
                self.client.head.update(FakeS3(self.report, self.receipt).head)
                self.client.head.update(change)
                with self.assertRaises(ValueError):
                    self.verify()

    def test_wrong_version_size_delete_marker_and_status_denied(self):
        for change in ({"VersionId": "another"}, {"VersionId": None},
                       {"ContentLength": self.receipt["observed_file_size_bytes"]+1},
                       {"ContentLength": True}, {"DeleteMarker": True},
                       {"ResponseMetadata": {"HTTPStatusCode": 403}}):
            with self.subTest(change=change):
                self.client.head = FakeS3(self.report, self.receipt).head
                self.client.head.update(change)
                with self.assertRaises(ValueError):
                    self.verify()

    def test_lock_retention_consistency_expiration_denied(self):
        altered = FakeS3(self.report, self.receipt)
        altered.head.pop("ObjectLockMode")
        self.client = altered
        with self.assertRaises(ValueError):
            self.verify()
        for change in (
            {"Retention": {"Mode": "GOVERNANCE", "RetainUntilDate": datetime(2028, 1, 1, tzinfo=timezone.utc)}},
            {"Retention": {"Mode": "COMPLIANCE", "RetainUntilDate": datetime(2029, 1, 1, tzinfo=timezone.utc)}},
            {"Retention": {}}, {"ResponseMetadata": {"HTTPStatusCode": 403}},
        ):
            with self.subTest(change=change):
                self.client = FakeS3(self.report, self.receipt)
                self.client.retention.update(change)
                with self.assertRaises(ValueError):
                    self.verify()
        self.client = FakeS3(self.report, self.receipt)
        with self.assertRaises(ValueError):
            self.verify(now=datetime(2029, 1, 1, tzinfo=timezone.utc))
        self.client.head["ObjectLockRetainUntilDate"] = datetime(2028, 1, 1)
        with self.assertRaises(ValueError):
            self.verify()

    def test_wrong_claim_or_bucket_owner_denied_before_remote_read(self):
        with self.assertRaises(ValueError):
            self.verify(owner="not-an-account")
        self.assertEqual(self.client.calls, [])
        altered = copy.deepcopy(self.report)
        altered["content_sha256"] = "0"*64
        with self.assertRaises(ValueError):
            self.verify(report=altered)
        self.client = FakeS3(self.report, self.receipt)
        wrong = copy.deepcopy(self.receipt)
        wrong["observed_raw_file_sha256"] = "f"*64
        with self.assertRaises(ValueError):
            self.verify(receipt=wrong)

    def test_custom_endpoint_or_region_rejected(self):
        class FakeClient:
            class meta:
                endpoint_url = "https://attacker.example.com"
        with patch("boto3.client", return_value=FakeClient()):
            with self.assertRaises(S3ProbeError):
                _aws_client("us-east-1")
        with self.assertRaises(S3ProbeError):
            _aws_client("http://127.0.0.1")


if __name__ == "__main__":
    unittest.main()
