"""v0.8.16 STS and S3 bucket-governance auditing with synthetic responses only.

No AWS credentials or outbound requests. Cryptographic upstream proofs
are recomputed from the existing synthetic source/capture/receipt fixtures.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.s3_governance import (
    GovernanceError, observe_governance, verify_governance,
    compare_governance, verify_comparison, live_clients, main,
)
from tests.test_external_archive_attestation import KEY
from tests.test_live_s3_version_verify import (
    LiveS3VersionTests, FakeS3, ACCOUNT, REGION, TEST_NOW,
)

SECOND = datetime(2026, 11, 12, 14, 0, tzinfo=timezone.utc)
CSV = Path(__file__).resolve().parent / "fixtures" / "sefaria_links_synthetic.csv"


class FakeGovernanceS3(FakeS3):
    def __init__(self, report, *, tag="A"):
        super().__init__(report)
        self.tag = tag
        self.head["ResponseMetadata"]["RequestId"] += tag
        self.lock["ResponseMetadata"]["RequestId"] += tag
        self.versioning = {
            "ResponseMetadata": {
                "HTTPStatusCode": 200, "RequestId": tag + "BUCKET_VERSIONING"},
            "Status": "Enabled",
        }
        self.public = {
            "ResponseMetadata": {
                "HTTPStatusCode": 200, "RequestId": tag + "BUCKET_PUBLIC"},
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            },
        }
        self.policy = {
            "ResponseMetadata": {
                "HTTPStatusCode": 200, "RequestId": tag + "BUCKET_POLICY"},
            "PolicyStatus": {"IsPublic": False},
        }
        self.lock_config = {
            "ResponseMetadata": {
                "HTTPStatusCode": 200, "RequestId": tag + "BUCKET_LOCK"},
            "ObjectLockConfiguration": {"ObjectLockEnabled": "Enabled"},
        }

    def _bucket(self, method, response, kwargs):
        self.calls.append((method, kwargs))
        if kwargs != {
            "Bucket": self.report["bucket"], "ExpectedBucketOwner": ACCOUNT
        }:
            raise RuntimeError("Unpinned mock S3 owner or bucket.")
        return copy.deepcopy(response)

    def get_bucket_versioning(self, **kwargs):
        return self._bucket("get_bucket_versioning", self.versioning, kwargs)

    def get_public_access_block(self, **kwargs):
        return self._bucket("get_public_access_block", self.public, kwargs)

    def get_bucket_policy_status(self, **kwargs):
        return self._bucket("get_bucket_policy_status", self.policy, kwargs)

    def get_object_lock_configuration(self, **kwargs):
        return self._bucket("get_object_lock_configuration",
                            self.lock_config, kwargs)


class FakeSTS:
    def __init__(self, *, tag="A", account=ACCOUNT):
        self.calls = 0
        self.response = {
            "ResponseMetadata": {
                "HTTPStatusCode": 200, "RequestId": tag + "STS_REQUEST"},
            "Account": account,
            "Arn": "arn:aws:sts::" + account + ":assumed-role/research/ci-" + tag,
            "UserId": "AROAEXAMPLE:" + tag,
        }

    def get_caller_identity(self):
        self.calls += 1
        return copy.deepcopy(self.response)


class GovernanceTests(unittest.TestCase):
    def setUp(self):
        fx = LiveS3VersionTests(
            "test_complete_version_pinned_reads_match_full_object_sha_and_compliance")
        fx.setUp()
        self.fx = fx

    def common(self):
        return dict(
            policy=self.fx.fx.policy,
            report=self.fx.fx.report,
            statement=self.fx.signed,
            record=self.fx.fx.record,
            receipt=self.fx.fx.receipt,
            witness=self.fx.fx.witness,
            capture=self.fx.fx.capture,
            source_file=CSV,
            local_key=KEY,
            account=ACCOUNT, region=REGION,
        )

    def observe(self, *, s3=None, sts=None, when=TEST_NOW):
        return observe_governance(
            s3 or FakeGovernanceS3(self.fx.fx.report),
            sts or FakeSTS(), **self.common(), observed_at=when)

    def test_positive_real_code_checks_six_s3_reads_one_sts(self):
        s3 = FakeGovernanceS3(self.fx.fx.report)
        sts = FakeSTS()
        result = self.observe(s3=s3, sts=sts)
        verify_governance(result, **self.common())
        self.assertEqual(sts.calls, 1)
        self.assertEqual([name for name, kwargs in s3.calls], [
            "head_object", "get_object_retention", "get_bucket_versioning",
            "get_public_access_block", "get_bucket_policy_status",
            "get_object_lock_configuration",
        ])
        self.assertEqual(result["research_release_status"], "HOLD")
        self.assertTrue(result["aws_bucket_versioning_enabled"])
        self.assertTrue(result["aws_bucket_object_lock_enabled"])
        self.assertFalse(result["full_iam_scp_access_points_policy_verified"])
        self.assertFalse(result["archive_continuously_immutable_verified"])
        text = json.dumps(result)
        for secret in (self.fx.fx.report["bucket"],
                       self.fx.fx.report["object_key"],
                       self.fx.fx.report["version_id"], ACCOUNT):
            self.assertNotIn(secret, text)

    def test_all_s3_bucket_calls_include_expected_owner(self):
        s3 = FakeGovernanceS3(self.fx.fx.report)
        self.observe(s3=s3)
        self.assertEqual(len(s3.calls), 6)
        for method, kwargs in s3.calls[2:]:
            self.assertEqual(kwargs, {
                "Bucket": self.fx.fx.report["bucket"],
                "ExpectedBucketOwner": ACCOUNT,
            })

    def test_sts_account_mismatch_or_bad_role_rejected(self):
        for update in (
            {"Account": "000000000000"},
            {"Arn": "arn:aws:sts::999999999999:assumed-role/research/ci"},
            {"Arn": "arn:aws:iam::"+ACCOUNT+":root"},
            {"UserId": ""},
            {"ResponseMetadata": {
                "HTTPStatusCode": 403, "RequestId": "ERROR"}},
        ):
            with self.subTest(update=update):
                sts = FakeSTS()
                sts.response.update(update)
                with self.assertRaises(GovernanceError):
                    self.observe(sts=sts)

    def test_missing_or_suspended_versioning_rejected(self):
        for value in ("Suspended", None, ""):
            s3 = FakeGovernanceS3(self.fx.fx.report)
            s3.versioning["Status"] = value
            with self.assertRaises(GovernanceError):
                self.observe(s3=s3)

    def test_missing_one_block_public_access_flag_rejected(self):
        for flag in (
            "BlockPublicAcls", "IgnorePublicAcls",
            "BlockPublicPolicy", "RestrictPublicBuckets",
        ):
            with self.subTest(flag=flag):
                s3 = FakeGovernanceS3(self.fx.fx.report)
                s3.public["PublicAccessBlockConfiguration"][flag] = False
                with self.assertRaises(GovernanceError):
                    self.observe(s3=s3)
                s3.public["PublicAccessBlockConfiguration"].pop(flag)
                with self.assertRaises(GovernanceError):
                    self.observe(s3=s3)

    def test_public_policy_or_indeterminate_status_rejected(self):
        for status in (True, None, "false"):
            s3 = FakeGovernanceS3(self.fx.fx.report)
            s3.policy["PolicyStatus"]["IsPublic"] = status
            with self.assertRaises(GovernanceError):
                self.observe(s3=s3)

    def test_missing_bucket_object_lock_rejected(self):
        for state in (None, "Disabled", False):
            s3 = FakeGovernanceS3(self.fx.fx.report)
            s3.lock_config["ObjectLockConfiguration"]["ObjectLockEnabled"] = state
            with self.assertRaises(GovernanceError):
                self.observe(s3=s3)

    def test_denied_bucket_read_fails_closed_without_leaking_private_bucket(self):
        class Rejected(FakeGovernanceS3):
            def get_bucket_versioning(self, **kwargs):
                raise RuntimeError("private bucket: " + self.report["bucket"])
        with self.assertRaises(GovernanceError) as e:
            self.observe(s3=Rejected(self.fx.fx.report))
        self.assertNotIn(self.fx.fx.report["bucket"], str(e.exception))
        s3 = FakeGovernanceS3(self.fx.fx.report)
        s3.policy["ResponseMetadata"]["HTTPStatusCode"] = 403
        with self.assertRaises(GovernanceError):
            self.observe(s3=s3)

    def test_invalid_source_chain_causes_zero_sdk_calls(self):
        s3 = FakeGovernanceS3(self.fx.fx.report)
        sts = FakeSTS()
        args = self.common()
        args["receipt"] = {**args["receipt"],
                           "observed_file_size_bytes": 5000000}
        with self.assertRaises(GovernanceError):
            observe_governance(s3, sts, **args, observed_at=TEST_NOW)
        self.assertEqual(s3.calls, [])
        self.assertEqual(sts.calls, 0)

    def test_offline_tampering_and_approval_promotion_denied(self):
        snapshot = self.observe()
        for key, value in (
            ("aws_sts_caller_account_matches_expected_owner", False),
            ("archive_continuously_immutable_verified", True),
            ("research_release_status", "APPROVED"),
            ("observation_hmac", "0"*64),
            ("observed_at_utc", "2027-01-01T00:00:00Z"),
            ("bucket_read_request_ids_sha256", {}),
        ):
            other = copy.deepcopy(snapshot)
            other[key] = value
            with self.subTest(key=key), self.assertRaises(GovernanceError):
                verify_governance(other, **self.common())
        with self.assertRaises(GovernanceError):
            other = copy.deepcopy(snapshot)
            other["live_version_observation"]["head_content_length"] += 1
            verify_governance(other, **self.common())

    def test_two_separated_reads_verify_stability_but_not_continuity(self):
        previous = self.observe(
            s3=FakeGovernanceS3(self.fx.fx.report, tag="A"),
            sts=FakeSTS(tag="A"), when=TEST_NOW)
        current = self.observe(
            s3=FakeGovernanceS3(self.fx.fx.report, tag="B"),
            sts=FakeSTS(tag="B"), when=SECOND)
        comparison = compare_governance(previous, current, **self.common())
        verify_comparison(comparison, previous, current, **self.common())
        self.assertEqual(comparison["minimum_interval_seconds"], 86400)
        self.assertEqual(comparison["observed_interval_seconds"], 25 * 3600)
        self.assertTrue(comparison["same_exact_source_and_object_version"])
        self.assertFalse(comparison["continuous_retention_independently_proven"])
        self.assertFalse(comparison["trusted_external_timestamp_verified"])
        self.assertEqual(comparison["research_release_status"], "HOLD")
        altered = copy.deepcopy(comparison)
        altered["continuous_retention_independently_proven"] = True
        with self.assertRaises(GovernanceError):
            verify_comparison(altered, previous, current, **self.common())

    def test_interval_less_than_24h_or_reused_request_ids_denied(self):
        previous = self.observe()
        too_soon = self.observe(
            s3=FakeGovernanceS3(self.fx.fx.report, tag="B"),
            sts=FakeSTS(tag="B"),
            when=datetime(2026, 11, 11, 14, 0, tzinfo=timezone.utc))
        with self.assertRaises(GovernanceError):
            compare_governance(previous, too_soon, **self.common())
        same_ids = self.observe(when=SECOND)
        with self.assertRaises(GovernanceError):
            compare_governance(previous, same_ids, **self.common())

    def test_compare_rejects_different_metadata_source_chain(self):
        previous = self.observe()
        current = self.observe(
            s3=FakeGovernanceS3(self.fx.fx.report, tag="B"),
            sts=FakeSTS(tag="B"), when=SECOND)
        current["live_version_observation"]["source_witness_sha256"] = "0"*64
        with self.assertRaises(GovernanceError):
            compare_governance(previous, current, **self.common())

    def test_live_sdk_two_fixed_https_endpoints_same_credential_session(self):
        class Session:
            last = None
            def __init__(self, **kw):
                self.kw = kw
                self.clients = []
                Session.last = self
            def client(self, name, **kw):
                self.clients.append((name, kw))
                return object()
        with patch("boto3.Session", Session):
            s3, sts = live_clients(profile="research-ci",
                                   region=REGION, account=ACCOUNT)
        self.assertEqual(Session.last.kw["profile_name"], "research-ci")
        self.assertEqual(len(Session.last.clients), 2)
        self.assertEqual(
            Session.last.clients[0][1]["endpoint_url"],
            "https://sts.il-central-1.amazonaws.com")
        self.assertEqual(
            Session.last.clients[1][1]["endpoint_url"],
            "https://s3.il-central-1.amazonaws.com")
        with self.assertRaises(GovernanceError):
            live_clients(profile="../bad", region=REGION, account=ACCOUNT)
        with self.assertRaises(GovernanceError):
            live_clients(profile="research-ci", region="localhost",
                         account=ACCOUNT)

    def test_cli_has_explicit_ack_and_offline_verify_and_compare(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            items = {
                "record.json": self.fx.fx.record,
                "receipt.json": self.fx.fx.receipt,
                "witness.json": self.fx.fx.witness,
                "capture.json": self.fx.fx.capture,
                "policy.json": self.fx.fx.policy,
                "report.json": self.fx.fx.report,
                "signed.json": self.fx.signed,
            }
            for file, obj in items.items():
                (root/file).write_text(
                    json.dumps(obj, ensure_ascii=False), encoding="utf-8")
            keyfile = root/"key"
            keyfile.write_text(KEY)
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
                "--local-key-file", str(keyfile),
                "--aws-region", REGION,
                "--expected-bucket-owner", ACCOUNT,
            ]
            self.assertEqual(main(["inspect", *args,
                                   "--aws-profile", "research-ci",
                                   "--output", str(root/"out.json")]), 2)
            first = self.observe()
            second = self.observe(
                s3=FakeGovernanceS3(self.fx.fx.report, tag="B"),
                sts=FakeSTS(tag="B"), when=SECOND)
            (root/"first.json").write_text(json.dumps(first))
            (root/"second.json").write_text(json.dumps(second))
            self.assertEqual(main(["verify", *args,
                                   "--observation", str(root/"first.json")]), 0)
            comparison_path = root/"comparison.json"
            self.assertEqual(main([
                "compare", *args,
                "--previous", str(root/"first.json"),
                "--current", str(root/"second.json"),
                "--output", str(comparison_path)]), 0)
            self.assertEqual(comparison_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(main([
                "compare", *args,
                "--previous", str(root/"first.json"),
                "--current", str(root/"second.json"),
                "--output", str(comparison_path)]), 2)


if __name__ == "__main__":
    unittest.main()
