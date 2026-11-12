"""v0.9.15 synthetic S3/STS governance checks for an Ed25519 audit anchor.

All AWS interfaces are in-memory mocks; no credentials or network calls.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.audit_anchor_governance_v0915 import main as governance_cli
from services.research_api.anchor_governance_v0915 import (
    AnchorGovernanceError, observe_anchor_governance,
    verify_anchor_governance,
)
from services.research_api.config import bootstrap_token
from tests.test_anchor_s3_v0914 import (
    FakeS3, SignedAnchorS3Tests, NOW,
)


class FakeBucketS3(FakeS3):
    def __init__(self, binding):
        super().__init__(binding)
        self.controls = {
            "get_bucket_versioning": {"Status": "Enabled"},
            "get_public_access_block": {
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": True,
                    "IgnorePublicAcls": True,
                    "BlockPublicPolicy": True,
                    "RestrictPublicBuckets": True,
                },
            },
            "get_bucket_policy_status": {
                "PolicyStatus": {"IsPublic": False},
            },
            "get_object_lock_configuration": {
                "ObjectLockConfiguration": {"ObjectLockEnabled": "Enabled"},
            },
        }

    def _control(self, method, **params):
        self.calls.append((method, deepcopy(params)))
        expected = {
            "Bucket": self.binding["bucket"],
            "ExpectedBucketOwner": self.binding["expected_bucket_owner"],
        }
        if params != expected:
            raise RuntimeError("Unexpected bucket control or owner")
        return {
            "ResponseMetadata": {
                "HTTPStatusCode": 200, "RequestId": method + "-mock-request",
            },
            **deepcopy(self.controls[method]),
        }

    def get_bucket_versioning(self, **kwargs):
        return self._control("get_bucket_versioning", **kwargs)

    def get_public_access_block(self, **kwargs):
        return self._control("get_public_access_block", **kwargs)

    def get_bucket_policy_status(self, **kwargs):
        return self._control("get_bucket_policy_status", **kwargs)

    def get_object_lock_configuration(self, **kwargs):
        return self._control("get_object_lock_configuration", **kwargs)


class FakeSts:
    def __init__(self, account):
        self.calls = 0
        self.response = {
            "ResponseMetadata": {
                "HTTPStatusCode": 200,
                "RequestId": "sts-mock-request-789",
            },
            "Account": account,
            "Arn": (
                "arn:aws:sts::" + account +
                ":assumed-role/private-archive/mock-ci"
            ),
            "UserId": "AROATEST:synthetic-ci",
        }

    def get_caller_identity(self):
        self.calls += 1
        return deepcopy(self.response)


class AnchorGovernanceTests(unittest.TestCase):
    def setUp(self):
        fx = SignedAnchorS3Tests(
            "test_exact_version_two_read_only_calls_and_full_sha")
        fx.setUp()
        self.fx = fx
        self.s3 = FakeBucketS3(fx.binding)
        self.sts = FakeSts(fx.binding["expected_bucket_owner"])
        self.common = dict(fx.args)

    def observe(self):
        return observe_anchor_governance(
            self.s3, self.sts, **self.common, observed_at=NOW)

    def verify(self, report):
        return verify_anchor_governance(report, **self.common)

    def test_seven_explicit_read_only_calls_and_offline_hmac(self):
        report = self.observe()
        self.assertEqual(self.sts.calls, 1)
        self.assertEqual([name for name, _ in self.s3.calls], [
            "head_object", "get_object_retention",
            "get_bucket_versioning", "get_public_access_block",
            "get_bucket_policy_status", "get_object_lock_configuration",
        ])
        self.assertTrue(report["aws_sts_caller_account_matches_expected_owner"])
        self.assertTrue(report["aws_bucket_versioning_enabled"])
        self.assertTrue(report["aws_bucket_object_lock_enabled"])
        self.assertTrue(report["read_only_bucket_controls_checked"])
        self.assertFalse(report["external_archive_continuously_immutable_verified"])
        self.assertEqual(report["research_release_status"], "HOLD")
        self.assertTrue(self.verify(report)[
            "offline_version_and_bucket_governance_hmac_verified"])
        self.assertFalse(self.verify(report)["live_aws_state_rechecked"])
        serialized = json.dumps(report)
        for name in (
            self.fx.binding["bucket"], self.fx.binding["object_key"],
            self.fx.binding["version_id"],
            self.fx.binding["expected_bucket_owner"],
        ):
            self.assertNotIn(name, serialized)

    def test_bucket_reads_are_scoped_to_exact_pinned_account(self):
        self.observe()
        for name, kwargs in self.s3.calls[2:]:
            self.assertEqual(kwargs, {
                "Bucket": self.fx.binding["bucket"],
                "ExpectedBucketOwner": self.fx.binding["expected_bucket_owner"],
            }, name)
        self.assertEqual(
            self.s3.calls[0][1]["VersionId"],
            self.fx.binding["version_id"])

    def test_invalid_signature_or_raw_bytes_prevent_all_aws_requests(self):
        self.common["signed_bytes"] = b'{"other":"signed-file"}'
        with self.assertRaises(AnchorGovernanceError):
            self.observe()
        self.assertEqual(self.s3.calls, [])
        self.assertEqual(self.sts.calls, 0)

    def test_invalid_local_observation_key_prevents_aws_calls(self):
        self.common["local_key"] = "short"
        with self.assertRaises(AnchorGovernanceError):
            self.observe()
        self.assertEqual(self.s3.calls, [])
        self.assertEqual(self.sts.calls, 0)

    def test_failed_full_object_checksum_precedes_sts_bucket_requests(self):
        self.s3.head_edits["ChecksumType"] = "COMPOSITE"
        with self.assertRaises(AnchorGovernanceError):
            self.observe()
        self.assertEqual([n for n,_ in self.s3.calls], [
            "head_object", "get_object_retention",
        ])
        self.assertEqual(self.sts.calls, 0)

    def test_sts_account_role_and_http_refusals(self):
        for patch_value in (
            {"Account": "000000000000"},
            {"Arn": "arn:aws:iam::123456789012:root"},
            {"UserId": ""},
            {"ResponseMetadata": {
                "HTTPStatusCode": 403, "RequestId": "not-authorized",
            }},
        ):
            with self.subTest(patch_value=patch_value):
                self.s3.calls.clear()
                self.sts.calls = 0
                saved = deepcopy(self.sts.response)
                self.sts.response.update(patch_value)
                try:
                    with self.assertRaises(AnchorGovernanceError):
                        self.observe()
                    self.assertEqual(self.sts.calls, 1)
                    self.assertEqual(len(self.s3.calls), 2)
                finally:
                    self.sts.response = saved

    def test_versioning_disabled_suspended_and_missing(self):
        for status in ("Suspended", None, ""):
            with self.subTest(status=status):
                self.s3.calls.clear()
                self.s3.controls["get_bucket_versioning"]["Status"] = status
                with self.assertRaises(AnchorGovernanceError):
                    self.observe()
        self.s3.controls["get_bucket_versioning"]["Status"] = "Enabled"

    def test_public_access_any_off_switch_is_refused(self):
        block = self.s3.controls[
            "get_public_access_block"]["PublicAccessBlockConfiguration"]
        for key in tuple(block):
            block[key] = False
            with self.subTest(key=key), self.assertRaises(AnchorGovernanceError):
                self.observe()
            block[key] = True
            self.s3.calls.clear()

    def test_bucket_policy_must_explicitly_be_nonpublic(self):
        self.s3.controls["get_bucket_policy_status"]["PolicyStatus"]["IsPublic"] = True
        with self.assertRaises(AnchorGovernanceError):
            self.observe()

    def test_bucket_object_lock_feature_must_be_enabled(self):
        self.s3.controls[
            "get_object_lock_configuration"]["ObjectLockConfiguration"][
                "ObjectLockEnabled"] = "Disabled"
        with self.assertRaises(AnchorGovernanceError):
            self.observe()

    def test_bucket_read_error_sanitizes_remote_exception(self):
        def fail(**kwargs):
            raise RuntimeError("PRIVATE-BUCKET-NAME-AND-CREDENTIALS")
        self.s3.get_bucket_versioning = fail
        with self.assertRaises(AnchorGovernanceError) as caught:
            self.observe()
        self.assertNotIn("PRIVATE-BUCKET", str(caught.exception))

    def test_offline_claim_tampering_and_extra_fields_denied(self):
        original = self.observe()
        for key, fake in (
            ("full_iam_scp_access_points_policy_verified", True),
            ("bucket_policy_contents_semantically_audited", True),
            ("external_archive_continuously_immutable_verified", True),
            ("independent_signer_identity_verified", True),
            ("source_rights_verified", True),
            ("graph_snapshot_verified", True),
            ("research_release_status", "PASS"),
            ("aws_bucket_object_lock_enabled", False),
            ("observation_hmac_sha256", "f" * 64),
            ("sts_request_id_sha256", "bad"),
            ("aws_region", "us-east-1"),
        ):
            with self.subTest(key=key):
                forged = deepcopy(original)
                forged[key] = fake
                with self.assertRaises(AnchorGovernanceError):
                    self.verify(forged)
        extra = deepcopy(original)
        extra["s3_private_key"] = "SECRET"
        with self.assertRaises(AnchorGovernanceError):
            self.verify(extra)

    def test_offline_nested_version_or_bucket_request_tampering_denied(self):
        original = self.observe()
        changed = deepcopy(original)
        changed["exact_version_observation"]["anchor_file_size_bytes"] = 10
        with self.assertRaises(AnchorGovernanceError):
            self.verify(changed)
        changed = deepcopy(original)
        changed["bucket_read_request_ids_sha256"]["get_bucket_versioning"] = (
            "0" * 64)
        with self.assertRaises(AnchorGovernanceError):
            self.verify(changed)

    def test_offline_never_accesses_aws_clients(self):
        observed = self.observe()
        self.s3.calls.clear()
        self.sts.calls = 0
        self.verify(observed)
        self.assertEqual(self.s3.calls, [])
        self.assertEqual(self.sts.calls, 0)

    def test_cli_requires_explicit_authorization_and_verifies_private_output(self):
        with tempfile.TemporaryDirectory() as root:
            temp = Path(root)
            signed = temp / "anchor.signed.json"
            policy = temp / "policy.json"
            binding = temp / "binding.json"
            secret = temp / "key"
            output = temp / "governance.json"
            signed.write_bytes(self.fx.raw)
            policy.write_text(json.dumps(self.fx.policy), encoding="utf-8")
            binding.write_text(json.dumps(self.fx.binding), encoding="utf-8")
            bootstrap_token(secret)
            self.common["local_key"] = self.fx.local_key
            args = [
                "--signed-anchor", str(signed),
                "--trusted-policy", str(policy),
                "--archive-binding", str(binding),
                "--local-key-file", str(secret),
            ]
            self.assertEqual(governance_cli([
                "inspect", *args, "--aws-profile", "read-only",
                "--output", str(output)]), 2)
            self.assertFalse(output.exists())
            with patch(
                "scripts.audit_anchor_governance_v0915.live_clients",
                return_value=(self.s3, self.sts),
            ):
                self.assertEqual(governance_cli([
                    "inspect", *args, "--aws-profile", "read-only",
                    "--ack-live-aws-read-only",
                    "--output", str(output)]), 0)
            self.assertTrue(output.exists())
            before = len(self.s3.calls)
            self.assertEqual(governance_cli([
                "verify", *args, "--observation", str(output)]), 0)
            self.assertEqual(len(self.s3.calls), before)

    def test_cli_rejects_symlink_signed_file_without_sdk(self):
        with tempfile.TemporaryDirectory() as root:
            temp = Path(root)
            source = temp / "signed.json"
            alias = temp / "alias.json"
            source.write_bytes(self.fx.raw)
            alias.symlink_to(source)
            policy = temp / "policy.json"
            binding = temp / "binding.json"
            key = temp / "key"
            policy.write_text(json.dumps(self.fx.policy))
            binding.write_text(json.dumps(self.fx.binding))
            bootstrap_token(key)
            with patch(
                "scripts.audit_anchor_governance_v0915.live_clients"
            ) as live:
                status = governance_cli([
                    "inspect", "--signed-anchor", str(alias),
                    "--trusted-policy", str(policy),
                    "--archive-binding", str(binding),
                    "--local-key-file", str(key),
                    "--aws-profile", "read-only", "--ack-live-aws-read-only",
                    "--output", str(temp / "report.json"),
                ])
                self.assertEqual(status, 1)
                live.assert_not_called()


if __name__ == "__main__":
    unittest.main()
