"""v0.8.20 S3 bucket/Access Point/role trust policy observations.

All AWS read methods are in-memory fakes. No credentials or live network.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

from scripts.aws_resource_trust import (
    ResourceTrustError, _document, _indicators, observe_resource_trust,
    verify_resource_trust, main,
)
from tests.test_aws_policy_revision import RevisionTests, KEY
from tests.test_aws_policy_documents import PolicyIAM
from tests.test_aws_access_surface import S3ControlMock
from tests.test_s3_governance import FakeGovernanceS3, ACCOUNT, REGION, TEST_NOW

CSV = Path(__file__).resolve().parent / "fixtures" / "sefaria_links_synthetic.csv"
OTHER = "222222222222"

ROLE_TRUST = {
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow",
                   "Principal": {"AWS": "arn:aws:iam::"+ACCOUNT+":root"},
                   "Action": "sts:AssumeRole"}],
}


def bucket_doc(bucket):
    return {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow",
             "Principal": {"AWS": "arn:aws:iam::"+OTHER+":role/OutsideReader"},
             "Action": ["s3:GetObject"],
             "Resource": "arn:aws:s3:::" + bucket + "/*",
             "Condition": {"StringEquals": {
                 "aws:SourceVpce": "vpce-01234567890abcde0"}}},
            {"Effect": "Deny", "Principal": "*",
             "Action": "s3:DeleteObject",
             "Resource": "arn:aws:s3:::" + bucket + "/*"},
        ],
    }


def access_doc():
    return {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow",
                       "Principal": {"AWS": "arn:aws:iam::"+ACCOUNT+":root"},
                       "Action": "s3:GetObject",
                       "Resource": (
                           "arn:aws:s3:il-central-1:"+ACCOUNT+
                           ":accesspoint/research-reader/object/*")}],
    }


class S3PolicyMock(FakeGovernanceS3):
    def __init__(self, report):
        super().__init__(report)
        self.policy_document = bucket_doc(report["bucket"])
        self.policy_reads = 0
        self.change_on = None

    def get_bucket_policy(self, **kwargs):
        self.policy_reads += 1
        self.calls.append(("get_bucket_policy", kwargs))
        if kwargs != {
            "Bucket": self.report["bucket"],
            "ExpectedBucketOwner": ACCOUNT,
        }:
            raise RuntimeError("wrong bucket or owner")
        document = copy.deepcopy(self.policy_document)
        if self.change_on is not None and self.policy_reads >= self.change_on:
            document["Statement"][0]["Principal"]["AWS"] = (
                "arn:aws:iam::"+ACCOUNT+":root")
        return {"ResponseMetadata": {
            "HTTPStatusCode": 200, "RequestId": "fixture-bucket-policy"},
            "Policy": json.dumps(document)}


class AccessPolicyMock(S3ControlMock):
    def __init__(self, bucket):
        super().__init__(bucket=bucket)
        self.policy_document = access_doc()
        self.policy_reads = 0
        self.change_on = None

    def get_access_point_policy(self, **kwargs):
        self.policy_reads += 1
        self.calls.append(("get_access_point_policy", kwargs))
        if kwargs != {"AccountId": ACCOUNT, "Name": "research-reader"}:
            raise RuntimeError("wrong scoped point")
        document = copy.deepcopy(self.policy_document)
        if self.change_on is not None and self.policy_reads >= self.change_on:
            document["Statement"][0]["Action"] = "s3:PutObject"
        return {"ResponseMetadata": {
            "HTTPStatusCode": 200, "RequestId": "fixture-point-policy"},
            "Policy": json.dumps(document)}


class RoleTrustMock(PolicyIAM):
    def __init__(self):
        super().__init__()
        self.trust = copy.deepcopy(ROLE_TRUST)
        self.trust_reads = 0
        self.change_on = None

    def get_role(self, **kwargs):
        self.trust_reads += 1
        res = super().get_role(**kwargs)
        res["Role"]["AssumeRolePolicyDocument"] = copy.deepcopy(self.trust)
        if self.change_on is not None and self.trust_reads >= self.change_on:
            res["Role"]["AssumeRolePolicyDocument"]["Statement"][0][
                "Principal"]["AWS"] = "arn:aws:iam::"+OTHER+":root"
        return res


class ResourceTrustTests(unittest.TestCase):
    def setUp(self):
        fx = RevisionTests("test_complete_two_rounds_and_explicit_incomplete_authority")
        fx.setUp()
        self.fx = fx
        self.common = fx.common
        self.s3 = S3PolicyMock(fx.old.f.fx.fx.fx.report)
        self.sts = fx.old.sts
        self.control = AccessPolicyMock(fx.old.f.fx.fx.fx.report["bucket"])
        self.iam = RoleTrustMock()
        self.org = fx.old.org

    def observe(self, **changes):
        c = dict(s3=self.s3, sts=self.sts, s3control=self.control,
                 iam=self.iam, org=self.org)
        c.update(changes)
        return observe_resource_trust(
            c["s3"], c["sts"], c["s3control"], c["iam"], c["org"],
            **self.common, observed_at=TEST_NOW)

    def test_resource_and_role_trust_complete_bounded_signed_census(self):
        result = self.observe()
        verify_resource_trust(result, **self.common)
        self.assertEqual(result["resource_policy_count"], 3)
        self.assertEqual(result["bucket_policy_count"], 1)
        self.assertEqual(result["access_point_policy_count"], 1)
        self.assertEqual(result["role_trust_policy_count"], 1)
        self.assertTrue(result["two_policy_rounds_match"])
        self.assertFalse(result["cross_account_access_proven"])
        self.assertFalse(result["effective_permission_decision_computed"])
        self.assertEqual(result["research_release_status"], "HOLD")
        stats = result["policy_indicators"]
        self.assertEqual(stats["allow_explicit_foreign_account_principal_statements"], 1)
        self.assertEqual(stats["allow_with_conditions_statements"], 1)
        self.assertEqual(stats["allow_assume_role_action_statements"], 1)
        self.assertEqual(stats["explicit_deny_statements"], 1)
        self.assertEqual(stats["total_statements_examined"], 4)
        self.assertEqual(self.s3.policy_reads, 2)
        self.assertEqual(self.control.policy_reads, 2)
        self.assertGreaterEqual(self.iam.trust_reads, 2)
        for secret in (
            "OutsideReader", "SourceVpce", "research-reader",
            "arn:aws:iam::", self.s3.report["bucket"], OTHER,
        ):
            self.assertNotIn(secret, json.dumps(result))

    def test_policy_reads_use_only_expected_bucket_and_access_point(self):
        self.observe()
        for kind, args in self.s3.calls:
            if kind == "get_bucket_policy":
                self.assertEqual(args, {
                    "Bucket": self.s3.report["bucket"],
                    "ExpectedBucketOwner": ACCOUNT})
        for kind, args in self.control.calls:
            if kind == "get_access_point_policy":
                self.assertEqual(args, {
                    "AccountId": ACCOUNT, "Name": "research-reader"})

    def test_bucket_policy_content_drift_rejected(self):
        s3 = S3PolicyMock(self.s3.report)
        s3.change_on = 2
        with self.assertRaises(ResourceTrustError):
            self.observe(s3=s3)

    def test_access_point_policy_content_drift_rejected(self):
        s3control = AccessPolicyMock(self.s3.report["bucket"])
        s3control.change_on = 2
        with self.assertRaises(ResourceTrustError):
            self.observe(s3control=s3control)

    def test_role_trust_policy_content_drift_rejected(self):
        iam = RoleTrustMock()
        # Earlier v0.8.19 reads GetRole several times before new round.
        iam.change_on = 15
        with self.assertRaises(ResourceTrustError):
            self.observe(iam=iam)

    def test_access_point_list_drift_or_unknown_point_fails_closed(self):
        control = AccessPolicyMock(self.s3.report["bucket"])
        control.points.append(dict(control.points[0]))
        with self.assertRaises(ResourceTrustError):
            self.observe(s3control=control)
        control = AccessPolicyMock(self.s3.report["bucket"])
        control.point["NetworkOrigin"] = "Internet"
        with self.assertRaises(ResourceTrustError):
            self.observe(s3control=control)

    def test_invalid_or_absent_policy_fails_closed(self):
        class Denied(S3PolicyMock):
            def get_bucket_policy(self, **kwargs):
                raise RuntimeError("private bucket name should not leak")
        with self.assertRaises(ResourceTrustError) as context:
            self.observe(s3=Denied(self.s3.report))
        self.assertNotIn("private bucket", str(context.exception))
        class Missing(AccessPolicyMock):
            def get_access_point_policy(self, **kwargs):
                return {"ResponseMetadata": {
                    "HTTPStatusCode": 200, "RequestId": "missing"}}
        with self.assertRaises(ResourceTrustError):
            self.observe(s3control=Missing(self.s3.report["bucket"]))

    def test_strict_policy_principal_forms_and_json_duplicates(self):
        samples = [
            {"Effect": "Allow", "Action": "s3:GetObject",
             "Principal": "arn:aws:iam::"+OTHER+":root",
             "Resource": "*"},
            {"Effect": "Allow", "Action": "s3:GetObject",
             "NotPrincipal": {"AWS": "*"}, "Resource": "*",
             "Principal": "*"},
            {"Effect": "Allow", "Action": "s3:GetObject",
             "Principal": {"Unknown": "*"}, "Resource": "*"},
            {"Effect": "Allow", "Action": "s3:GetObject",
             "Principal": {"AWS": []}, "Resource": "*"},
            {"Effect": "Allow", "Action": "s3:GetObject",
             "Principal": "*", "Resource": "*", "NotResource": "*"},
        ]
        for statement in samples:
            with self.subTest(statement=repr(statement)[:60]):
                with self.assertRaises(ResourceTrustError):
                    _document({"Version": "2012-10-17",
                               "Statement": [statement]}, kind="bucket")
        duplicate = ('{"Version":"2012-10-17","Version":"2012-10-17",'
                     '"Statement":[]}')
        with self.assertRaises(ResourceTrustError):
            _document(duplicate, kind="bucket")

    def test_principal_structural_counts_do_not_prove_access(self):
        doc = _document({
            "Version": "2012-10-17",
            "Statement": [
                {"Effect": "Allow", "Principal": "*",
                 "Action": "s3:GetObject", "Resource": "*",
                 "Condition": {"StringEquals": {"aws:SourceVpce": "vpce-abc"}}},
                {"Effect": "Allow",
                 "NotPrincipal": {"AWS": "arn:aws:iam::"+ACCOUNT+":root"},
                 "Action": "s3:GetObject", "Resource": "*"},
                {"Effect": "Allow",
                 "Principal": {"Service": "logs.amazonaws.com"},
                 "Action": "s3:PutObject", "Resource": "*"},
            ],
        }, kind="bucket")
        stats = _indicators(doc, owner=ACCOUNT)
        self.assertEqual(stats["allow_wildcard_principal_statements"], 1)
        self.assertEqual(stats["allow_notprincipal_statements"], 1)
        self.assertEqual(stats["allow_service_or_federated_principal_statements"], 1)
        self.assertEqual(stats["allow_with_conditions_statements"], 1)
        self.assertEqual(stats["allow_explicit_foreign_account_principal_statements"], 0)

    def test_missing_resource_policy_is_not_silent_empty(self):
        with self.assertRaises(ResourceTrustError):
            _document({
                "Version": "2012-10-17",
                "Statement": [{"Effect": "Allow", "Principal": "*",
                               "Action": "s3:GetObject"}],
            }, kind="bucket")

    def test_offline_verifier_denies_approval_forgery_and_chain_tamper(self):
        result = self.observe()
        for field, value in (
            ("report_hmac", "0" * 64),
            ("cross_account_access_proven", True),
            ("effective_permission_decision_computed", True),
            ("research_release_status", "APPROVED"),
            ("resource_policy_count", 1),
            ("unreviewed_resource_routes", []),
            ("resource_policy_projection_sha256", "f" * 64),
        ):
            tampered = copy.deepcopy(result)
            tampered[field] = value
            with self.subTest(field=field):
                with self.assertRaises(ResourceTrustError):
                    verify_resource_trust(tampered, **self.common)
        other = copy.deepcopy(result)
        other["parent_revision_report"]["research_release_status"] = "APPROVED"
        with self.assertRaises(ResourceTrustError):
            verify_resource_trust(other, **self.common)

    def test_offline_cli_success_and_bad_report(self):
        evidence = self.observe()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = self.fx.old.f.fx.fx.fx
            parts = {
                "record.json": original.record,
                "receipt.json": original.receipt,
                "witness.json": original.witness,
                "capture.json": original.capture,
                "policy.json": original.policy,
                "report.json": original.report,
                "signed.json": original.check.__globals__["synthetic_signed_envelope"](
                    original.policy, original.statement, original.signer),
                "resource.json": evidence,
            }
            for name, data in parts.items():
                (root / name).write_text(json.dumps(data), encoding="utf-8")
            secret = root / "secret"
            secret.write_text(KEY)
            os.chmod(secret, 0o600)
            args = [
                "--source-file", str(CSV),
                "--source-record", str(root/"record.json"),
                "--receipt", str(root/"receipt.json"),
                "--witness", str(root/"witness.json"),
                "--capture-manifest", str(root/"capture.json"),
                "--trusted-policy", str(root/"policy.json"),
                "--archive-report", str(root/"report.json"),
                "--signed-statement", str(root/"signed.json"),
                "--aws-region", REGION, "--expected-bucket-owner", ACCOUNT,
                "--local-key-file", str(secret),
                "--observation", str(root/"resource.json"),
            ]
            self.assertEqual(main(["verify", *args]), 0)
            altered = copy.deepcopy(evidence)
            altered["all_resource_policies_examined"] = True
            (root / "resource.json").write_text(json.dumps(altered))
            self.assertEqual(main(["verify", *args]), 2)


if __name__ == "__main__":
    unittest.main()
