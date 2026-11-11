"""v0.8.19 IAM/SCP version-drift and structural-condition evidence tests.

All AWS reads are fake. No AWS principal, credential or network is used.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

from scripts.aws_policy_revision import (
    RevisionAuditError, _conditions, _round, observe_revision,
    verify_revision, main, UNREVIEWED,
)
from scripts.aws_policy_documents import _document
from tests.test_aws_policy_documents import (
    PolicyDocumentTests, PolicyIAM, PolicyOrg, ALLOW_BROAD,
)
from tests.test_s3_governance import ACCOUNT, REGION, TEST_NOW

CSV = Path(__file__).resolve().parent / "fixtures" / "sefaria_links_synthetic.csv"
from tests.test_external_archive_attestation import KEY


class RevisionTests(unittest.TestCase):
    def setUp(self):
        old = PolicyDocumentTests(
            "test_complete_bounded_policy_documents_and_exact_policy_chain")
        old.setUp()
        self.old = old
        self.common = old.common

    def capture(self, **change):
        clients = {
            "s3": self.old.s3, "sts": self.old.sts,
            "s3control": self.old.control, "iam": self.old.iam,
            "org": self.old.org,
        }
        clients.update(change)
        return observe_revision(
            clients["s3"], clients["sts"], clients["s3control"],
            clients["iam"], clients["org"],
            **self.common, observed_at=TEST_NOW)

    def test_complete_two_rounds_and_explicit_incomplete_authority(self):
        result = self.capture()
        verify_revision(result, **self.common)
        self.assertTrue(result["two_bounded_policy_rounds_match"])
        self.assertEqual(
            result["first_round_sha256"], result["second_round_sha256"])
        self.assertEqual(result["policy_document_count"], 5)
        self.assertEqual(result["managed_default_version_count"], 1)
        self.assertEqual(result["research_release_status"], "HOLD")
        self.assertFalse(result["effective_iam_or_scp_permissions_computed"])
        self.assertFalse(result["policy_version_transactional_snapshot_verified"])
        self.assertFalse(result["all_conditional_semantics_evaluated"])
        self.assertEqual(result["unreviewed_access_paths"], list(UNREVIEWED))
        self.assertEqual(result["condition_indicators"]["statements_with_conditions"], 1)
        self.assertEqual(result["condition_indicators"]["statements_with_principal_context_keys"], 1)
        self.assertEqual(result["condition_indicators"]["condition_attributes_inspected"], 1)
        self.assertEqual(result["condition_indicators"]["unconditional_broad_iam_allow_statements"], 0)
        for marker in (
            "arn:aws:iam::", "iam:PassRole", "s3:DeleteObject",
            "p-example1", "MetadataOnly",
        ):
            self.assertNotIn(marker, json.dumps(result))
        self.assertGreater(
            sum(name == "get_policy_version" for name, _ in self.old.iam.calls), 2)

    def test_detect_default_version_flip_inside_single_round(self):
        class FlipMidRead(PolicyIAM):
            def __init__(self):
                super().__init__()
                self.calls_to_get_policy = 0
            def get_policy(self, **kwargs):
                self.calls_to_get_policy += 1
                result = super().get_policy(**kwargs)
                if self.calls_to_get_policy >= 3:
                    result["Policy"]["DefaultVersionId"] = "v2"
                return result
        with self.assertRaises(RevisionAuditError):
            self.capture(iam=FlipMidRead())

    def test_detect_version_flip_between_rounds_even_same_document(self):
        class FlipBetween(PolicyIAM):
            def __init__(self):
                super().__init__()
                self.requests = 0
            def get_policy(self, **kwargs):
                self.requests += 1
                response = super().get_policy(**kwargs)
                if self.requests >= 4:
                    response["Policy"]["DefaultVersionId"] = "v2"
                return response
        with self.assertRaises(RevisionAuditError):
            self.capture(iam=FlipBetween())

    def test_inline_document_drifts_after_first_round(self):
        class InlineDrift(PolicyIAM):
            def __init__(self):
                super().__init__()
                self.inline_reads = 0
            def get_role_policy(self, **kwargs):
                self.inline_reads += 1
                response = super().get_role_policy(**kwargs)
                if self.inline_reads >= 3:
                    response["PolicyDocument"]["Statement"][0]["Action"] = "iam:*"
                return response
        with self.assertRaises(RevisionAuditError):
            self.capture(iam=InlineDrift())

    def test_scp_document_drifts_with_same_attachment_set(self):
        class SCPDrift(PolicyOrg):
            def __init__(self):
                super().__init__()
                self.reads = 0
            def describe_policy(self, **kwargs):
                self.reads += 1
                response = super().describe_policy(**kwargs)
                if self.reads >= 7:
                    doc = json.loads(response["Policy"]["Content"])
                    doc["Statement"][0]["Action"] = "s3:*"
                    response["Policy"]["Content"] = json.dumps(doc)
                return response
        with self.assertRaises(RevisionAuditError):
            self.capture(org=SCPDrift())

    def test_condition_ifexists_set_null_and_network_scope_not_evaluated(self):
        doc = _document({
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow", "Action": "s3:*", "Resource": "*",
                "Condition": {
                    "ForAnyValue:StringEqualsIfExists": {
                        "aws:SourceVpce": "vpce-01234567",
                    },
                    "Null": {"aws:PrincipalArn": "false"},
                    "UnknownVendorMatcher": {"s3:ResourceAccount": "123456789012"},
                },
            }],
        })
        counts = _conditions(doc, kind="iam")
        self.assertEqual(counts["statements_with_conditions"], 1)
        self.assertEqual(counts["statements_with_ifexists"], 1)
        self.assertEqual(counts["statements_with_set_qualifiers"], 1)
        self.assertEqual(counts["statements_with_null_tests"], 1)
        self.assertEqual(counts["statements_with_unrecognized_condition_operators"], 1)
        self.assertEqual(counts["statements_with_network_scoping_keys"], 1)
        self.assertEqual(counts["statements_with_principal_context_keys"], 1)
        self.assertEqual(counts["statements_with_aws_resource_scoping_keys"], 1)
        self.assertEqual(counts["unconditional_broad_iam_allow_statements"], 0)
        self.assertEqual(counts["condition_attributes_inspected"], 3)

    def test_unconditional_allow_indicator_does_not_approve_permissions(self):
        doc = _document({
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Allow", "Action": "iam:*",
                           "Resource": "*"}],
        })
        risk = _conditions(doc, kind="iam")
        self.assertEqual(risk["unconditional_broad_iam_allow_statements"], 1)
        self.assertEqual(risk["statements_with_conditions"], 0)
        self.assertEqual(_conditions(doc, kind="scp")[
            "unconditional_broad_iam_allow_statements"], 0)

    def test_malformed_condition_operands_fail_closed(self):
        bad_values = [
            {"StringEquals": {"aws:SourceVpce": {"secret": "x"}}},
            {"StringEquals": {"aws:SourceVpce": None}},
            {"StringEquals": {"aws:SourceVpce": []}},
            {"StringEquals": {"aws:SourceVpce": ["valid", {"no": "x"}]}},
            {"StringEquals": {"aws:SourceVpce": ["\n"]}},
            {"Bad\u0001Operator": {"aws:SourceVpce": "x"}},
            {"StringEquals": {"": "value"}},
            {"StringEquals": {"aws:SourceVpce": "x" * 1025}},
        ]
        for condition in bad_values:
            doc = _document({
                "Version": "2012-10-17",
                "Statement": [{"Effect": "Allow", "Action": "s3:*",
                               "Resource": "*", "Condition": condition}],
            })
            with self.subTest(condition=str(condition)[:32]):
                with self.assertRaises(RevisionAuditError):
                    _conditions(doc, kind="iam")

    def test_policy_document_attachments_still_bound_to_signed_census(self):
        iam = PolicyIAM()
        iam.change_attachments_at = 3
        with self.assertRaises(RevisionAuditError):
            self.capture(iam=iam)
        org = PolicyOrg()
        org.attach["ou-abcd1234-abcdefgh"] = ["p-example1"]
        result = self.capture(org=org)
        verify_revision(result, **self.common)
        self.assertEqual(result["policy_document_count"], 4)

    def test_local_hmac_and_nonapproval_invariants(self):
        result = self.capture()
        for key, value in (
            ("report_hmac", "0" * 64),
            ("research_release_status", "APPROVED"),
            ("effective_iam_or_scp_permissions_computed", True),
            ("all_conditional_semantics_evaluated", True),
            ("policy_version_transactional_snapshot_verified", True),
            ("first_round_sha256", "0" * 64),
            ("managed_default_version_count", 900),
            ("unreviewed_access_paths", []),
        ):
            altered = copy.deepcopy(result)
            altered[key] = value
            with self.subTest(key=key):
                with self.assertRaises(RevisionAuditError):
                    verify_revision(altered, **self.common)
        changed = copy.deepcopy(result)
        changed["parent_policy_report"]["research_release_status"] = "APPROVED"
        with self.assertRaises(RevisionAuditError):
            verify_revision(changed, **self.common)

    def test_offline_cli_without_live_aws_credentials(self):
        captured = self.capture()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            mapping = {
                "record.json": self.old.f.fx.fx.fx.record,
                "receipt.json": self.old.f.fx.fx.fx.receipt,
                "witness.json": self.old.f.fx.fx.fx.witness,
                "capture.json": self.old.f.fx.fx.fx.capture,
                "policy.json": self.old.f.fx.fx.fx.policy,
                "report.json": self.old.f.fx.fx.fx.report,
                "signed.json": self.old.f.fx.fx.signed,
                "observation.json": captured,
            }
            for name, content in mapping.items():
                (root / name).write_text(
                    json.dumps(content, ensure_ascii=False), encoding="utf-8")
            key = root / "hmac.key"
            key.write_text(KEY)
            os.chmod(key, 0o600)
            args = [
                "--source-file", str(CSV),
                "--source-record", str(root / "record.json"),
                "--receipt", str(root / "receipt.json"),
                "--witness", str(root / "witness.json"),
                "--capture-manifest", str(root / "capture.json"),
                "--trusted-policy", str(root / "policy.json"),
                "--archive-report", str(root / "report.json"),
                "--signed-statement", str(root / "signed.json"),
                "--aws-region", REGION,
                "--expected-bucket-owner", ACCOUNT,
                "--local-key-file", str(key),
                "--observation", str(root / "observation.json"),
            ]
            self.assertEqual(main(["verify", *args]), 0)
            tampered = copy.deepcopy(captured)
            tampered["condition_indicators"]["statements_with_conditions"] += 1
            (root / "observation.json").write_text(json.dumps(tampered))
            self.assertEqual(main(["verify", *args]), 2)


if __name__ == "__main__":
    unittest.main()
