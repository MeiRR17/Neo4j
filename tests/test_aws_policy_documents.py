"""v0.8.18 bounded IAM/SCP policy document analysis, all AWS mocked."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from scripts.aws_policy_documents import (
    PolicyAuditError, _document, _indicators, observe_policy_documents,
    verify_policy_report, MAX_DOCUMENT_BYTES,
)
from tests.test_aws_access_surface import (
    AccessCensusTests, IAMMock, OrgMock, S3ControlMock,
)
from tests.test_s3_governance import FakeGovernanceS3, FakeSTS, ACCOUNT, REGION, TEST_NOW

ALLOW_BROAD = {
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Action": ["s3:*", "iam:PassRole"],
                   "Resource": "*", "Condition": {"StringEquals":
                        {"aws:PrincipalTag/Synthetic": "yes"}}}],
}
INLINE_DENY = {
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Deny", "Action": "s3:DeleteObject",
                   "Resource": "*"}],
}
SCP_DENY = {"Version": "2012-10-17",
            "Statement": [{"Effect": "Deny",
                           "Action": "s3:DeleteObject", "Resource": "*"}]}
SCP_ALLOW = {"Version": "2012-10-17",
             "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]}


class PolicyIAM(IAMMock):
    def __init__(self):
        super().__init__()
        self.default_version = "v1"
        self.policy_document = copy.deepcopy(ALLOW_BROAD)
        self.inline_document = copy.deepcopy(INLINE_DENY)
        self.attached_calls = 0
        self.change_attachments_at = None

    def list_attached_role_policies(self, **kwargs):
        self.attached_calls += 1
        if self.change_attachments_at == self.attached_calls:
            self.attached["AttachedPolicies"].append({
                "PolicyArn": "arn:aws:iam::"+ACCOUNT+":policy/new-permission"})
        return super().list_attached_role_policies(**kwargs)

    def get_policy(self, **kwargs):
        self.calls.append(("get_policy",kwargs))
        return {"ResponseMetadata":{"HTTPStatusCode":200,"RequestId":"managed"},
                "Policy":{"Arn":kwargs["PolicyArn"],
                          "DefaultVersionId":self.default_version}}

    def get_policy_version(self, **kwargs):
        self.calls.append(("get_policy_version",kwargs))
        return {"ResponseMetadata":{"HTTPStatusCode":200,"RequestId":"version"},
                "PolicyVersion":{"VersionId":kwargs["VersionId"],
                                 "IsDefaultVersion":True,
                                 "Document":copy.deepcopy(self.policy_document)}}

    def get_role_policy(self, **kwargs):
        self.calls.append(("get_role_policy",kwargs))
        return {"ResponseMetadata":{"HTTPStatusCode":200,"RequestId":"inline"},
                "RoleName":kwargs["RoleName"],"PolicyName":kwargs["PolicyName"],
                "PolicyDocument":copy.deepcopy(self.inline_document)}


class PolicyOrg(OrgMock):
    def __init__(self):
        super().__init__()
        self.contents = {
            "p-example1":copy.deepcopy(SCP_DENY),
            "p-example2":copy.deepcopy(SCP_ALLOW),
            "p-example3":copy.deepcopy(SCP_DENY),
        }

    def describe_policy(self, **kwargs):
        ident=kwargs["PolicyId"]
        self.calls.append(("describe_policy",kwargs))
        return {"ResponseMetadata":{"HTTPStatusCode":200,"RequestId":"scpdoc"},
                "Policy":{"PolicySummary":{"Id":ident,
                                          "Type":"SERVICE_CONTROL_POLICY"},
                          "Content":json.dumps(self.contents[ident])}}


class PolicyDocumentTests(unittest.TestCase):
    def setUp(self):
        base=AccessCensusTests(
            "test_positive_requires_account_access_point_role_and_all_scp_ancestors")
        base.setUp()
        self.f=base
        self.s3=FakeGovernanceS3(self.f.fx.fx.fx.report)
        self.sts=FakeSTS()
        self.control=S3ControlMock(bucket=self.f.fx.fx.fx.report["bucket"])
        self.iam=PolicyIAM()
        self.org=PolicyOrg()
        self.common=self.f.common

    def audit(self, **overrides):
        clients=dict(s3=self.s3,sts=self.sts,s3control=self.control,
                     iam=self.iam,org=self.org)
        clients.update(overrides)
        return observe_policy_documents(
            clients["s3"],clients["sts"],clients["s3control"],
            clients["iam"],clients["org"],**self.common,observed_at=TEST_NOW)

    def test_complete_bounded_policy_documents_and_exact_policy_chain(self):
        result=self.audit()
        verify_policy_report(result,**self.common)
        self.assertEqual(result["policy_count"],5)
        self.assertEqual(result["iam_managed_policy_count"],1)
        self.assertEqual(result["iam_inline_policy_count"],1)
        self.assertEqual(result["scp_policy_count"],3)
        f=result["policy_indicators"]
        self.assertEqual(f["iam_allow_wildcard_resource_statements"],1)
        self.assertEqual(f["iam_storage_mutation_allow_statements"],1)
        self.assertEqual(f["iam_iam_escalation_allow_statements"],1)
        self.assertEqual(f["iam_explicit_deny_statements"],1)
        self.assertEqual(f["scp_explicit_deny_statements"],2)
        self.assertEqual(f["scp_allow_statements"],1)
        self.assertEqual(f["conditioned_statements"],1)
        self.assertEqual(f["total_statements_scanned"],5)
        self.assertTrue(result["doc_reads_bound_to_attachment_inventory"])
        self.assertFalse(result["iam_effective_permissions_calculated"])
        self.assertFalse(result["scp_effective_permissions_calculated"])
        self.assertFalse(result["policy_conditions_semantically_evaluated"])
        self.assertEqual(result["research_release_status"],"HOLD")
        self.assertEqual(
            [m for m,args in self.iam.calls if m.startswith("get_policy")],
            ["get_policy","get_policy_version"])
        self.assertEqual(
            sum(m=="describe_policy" for m,args in self.org.calls),3)
        raw=json.dumps(result)
        for forbidden in ("iam:PassRole","s3:DeleteObject","MetadataOnly",
                          "p-example1","arn:aws:iam::", "research-reader"):
            self.assertNotIn(forbidden,raw)

    def test_iam_version_boundary_and_unsafe_document_fail_closed(self):
        for kind in ("invalid-version","bad-document","foreign-policy"):
            iam=PolicyIAM()
            if kind=="invalid-version":
                iam.default_version="unsafe"
            if kind=="bad-document":
                iam.policy_document["Statement"][0]["Principal"]="*"
            if kind=="foreign-policy":
                iam.attached["AttachedPolicies"][0]["PolicyArn"]=(
                    "arn:aws:iam::999999999999:policy/fake")
            with self.subTest(kind=kind),self.assertRaises(PolicyAuditError):
                self.audit(iam=iam)

    def test_bounded_parser_rejects_unknown_effect_or_duplicate_json(self):
        examples=[
            {"Version":"2012-10-17","Statement":[{"Effect":"Maybe",
                 "Action":"s3:*","Resource":"*"}]},
            {"Version":"2012-10-17","Statement":[{"Effect":"Allow",
                 "Action":"*","NotAction":"s3:*","Resource":"*"}]},
            {"Version":"2012-10-17","Statement":[{"Effect":"Allow",
                 "Action":"*","Resource":"*","NotResource":"*"}]},
            {"Version":"2012-10-17","Statement":[]},
            {"Version":"2020-01-01","Statement":SCP_ALLOW["Statement"]},
            {"Version":"2012-10-17","Statement":SCP_ALLOW["Statement"],
             "Unrecognized":"field"},
        ]
        for d in examples:
            with self.subTest(data=str(d)[:40]),self.assertRaises(PolicyAuditError):
                _document(d)
        for raw in ('{"Version":"2012-10-17","Version":"2012-10-17",'
                    '"Statement":[]}', "not json", "{", "x"*MAX_DOCUMENT_BYTES):
            with self.assertRaises(PolicyAuditError):
                _document(raw)

    def test_iam_url_encoded_compatibility_and_notaction_caution(self):
        from urllib.parse import quote
        d={"Version":"2012-10-17","Statement":[{
            "Effect":"Allow","NotAction":"iam:*","Resource":"*"}]}
        self.assertEqual(_document(quote(json.dumps(d))),_document(d))
        f=_indicators(_document(d),kind="iam")
        self.assertEqual(f["not_action_or_not_resource_statements"],1)
        self.assertEqual(f["iam_storage_mutation_allow_statements"],0)
        self.assertEqual(f["iam_iam_escalation_allow_statements"],0)

    def test_scp_policy_document_identifier_mismatch_rejected(self):
        class Wrong(PolicyOrg):
            def describe_policy(self,**kwargs):
                v=super().describe_policy(**kwargs)
                v["Policy"]["PolicySummary"]["Id"]="p-another1"
                return v
        with self.assertRaises(PolicyAuditError):
            self.audit(org=Wrong())

    def test_scp_incomplete_parent_inventory_rejected(self):
        org=PolicyOrg()
        org.parent.pop("ou-abcd1234-abcdefgh")
        with self.assertRaises(PolicyAuditError):
            self.audit(org=org)

    def test_policy_attachment_drift_during_document_reads_rejected(self):
        iam=PolicyIAM()
        iam.change_attachments_at=3
        with self.assertRaises(PolicyAuditError):
            self.audit(iam=iam)

    def test_missing_managed_policy_version_or_scp_document_is_blocking(self):
        class NoVersion(PolicyIAM):
            def get_policy_version(self,**kwargs):
                d=super().get_policy_version(**kwargs)
                d["PolicyVersion"]["IsDefaultVersion"]=False
                return d
        with self.assertRaises(PolicyAuditError):
            self.audit(iam=NoVersion())
        class Denied(PolicyOrg):
            def describe_policy(self,**kwargs):
                raise RuntimeError("private organization policy text")
        with self.assertRaises(PolicyAuditError) as err:
            self.audit(org=Denied())
        self.assertNotIn("private",str(err.exception))

    def test_offline_hmac_and_trust_flags_must_not_promote_access(self):
        good=self.audit()
        for k,v in (
            ("report_hmac","0"*64),
            ("iam_effective_permissions_calculated",True),
            ("policy_conditions_semantically_evaluated",True),
            ("research_release_status","APPROVED"),
            ("policy_count",999),
            ("policy_documents_projection_sha256","A"*64),
        ):
            changed=copy.deepcopy(good);changed[k]=v
            with self.subTest(field=k),self.assertRaises(PolicyAuditError):
                verify_policy_report(changed,**self.common)
        good["access_census"]["effective_iam_permissions_verified"]=True
        with self.assertRaises(PolicyAuditError):
            verify_policy_report(good,**self.common)

    def test_bounded_scan_with_shared_scp_counts_unique_documents(self):
        org=PolicyOrg()
        org.attach["ou-abcd1234-abcdefgh"]=["p-example1"]
        r=self.audit(org=org)
        self.assertEqual(r["scp_policy_count"],2)
        self.assertEqual(r["policy_indicators"]["total_statements_scanned"],4)


if __name__=="__main__":
    unittest.main()
