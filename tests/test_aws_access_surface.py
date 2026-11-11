"""v0.8.17 bounded IAM/SCP/Access Point census; ALL AWS responses mocked."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.aws_access_surface import (
    AccessAuditError, _access_points, _role, _scp, _pages,
    observe_access_surface, verify_access_surface, live_clients,
)
from tests.test_s3_governance import (
    GovernanceTests, FakeGovernanceS3, FakeSTS, ACCOUNT, REGION, TEST_NOW,
    CSV, KEY,
)

META = lambda tag: {"ResponseMetadata": {"HTTPStatusCode": 200, "RequestId": tag}}


class S3ControlMock:
    def __init__(self, *, bucket, with_point=True):
        self.bucket, self.calls = bucket, []
        self.bpa = {**META("account-bpa"),
                    "PublicAccessBlockConfiguration": {
                        "BlockPublicAcls": True, "IgnorePublicAcls": True,
                        "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
                    }}
        self.points = ([{"Name": "research-reader", "Bucket": bucket}]
                       if with_point else [])
        self.point = {
            **META("ap-detail"), "Name": "research-reader", "Bucket": bucket,
            "NetworkOrigin": "VPC", "VpcConfiguration": {"VpcId": "vpc-12345678"},
            "PublicAccessBlockConfiguration":
                dict(self.bpa["PublicAccessBlockConfiguration"]),
        }
        self.policy = {**META("ap-policy"), "PolicyStatus": {"IsPublic": False}}
    def get_public_access_block(self, **kwargs):
        self.calls.append(("get_public_access_block",kwargs))
        if kwargs != {"AccountId": ACCOUNT}: raise RuntimeError("wrong account")
        return copy.deepcopy(self.bpa)
    def list_access_points(self, **kwargs):
        self.calls.append(("list_access_points",kwargs))
        if (kwargs.get("AccountId") != ACCOUNT or
            kwargs.get("Bucket") != self.bucket): raise RuntimeError("wrong bucket")
        return {**META("ap-list"), "AccessPointList": copy.deepcopy(self.points)}
    def get_access_point(self, **kwargs):
        self.calls.append(("get_access_point",kwargs))
        if kwargs != {"AccountId": ACCOUNT, "Name": "research-reader"}:
            raise RuntimeError("wrong access point")
        return copy.deepcopy(self.point)
    def get_access_point_policy_status(self, **kwargs):
        self.calls.append(("get_access_point_policy_status",kwargs))
        if kwargs != {"AccountId": ACCOUNT, "Name": "research-reader"}:
            raise RuntimeError("wrong policy")
        return copy.deepcopy(self.policy)


class IAMMock:
    def __init__(self):
        self.calls=[]
        self.role = {**META("iam-role"), "Role":{
            "Arn": "arn:aws:iam::"+ACCOUNT+":role/research",
            "PermissionsBoundary": {
                "PermissionsBoundaryType":"Policy",
                "PermissionsBoundaryArn":"arn:aws:iam::"+ACCOUNT+":policy/restrict",
            },
        }}
        self.attached = {**META("iam-attach"),
                         "AttachedPolicies":[{
                            "PolicyArn":"arn:aws:iam::"+ACCOUNT+":policy/read-only"}]}
        self.inline = {**META("iam-inline"),
                       "PolicyNames":["MetadataOnly"]}
    def get_role(self, **kwargs):
        self.calls.append(("get_role",kwargs))
        if kwargs != {"RoleName":"research"}: raise RuntimeError("wrong role")
        return copy.deepcopy(self.role)
    def list_attached_role_policies(self, **kwargs):
        self.calls.append(("list_attached_role_policies",kwargs))
        return copy.deepcopy(self.attached)
    def list_role_policies(self, **kwargs):
        self.calls.append(("list_role_policies",kwargs))
        return copy.deepcopy(self.inline)


class OrgMock:
    def __init__(self):
        self.calls=[]
        self.parent={
            ACCOUNT: {"Id":"ou-abcd1234-abcdefgh", "Type":"ORGANIZATIONAL_UNIT"},
            "ou-abcd1234-abcdefgh":{"Id":"r-abcd1234","Type":"ROOT"},
        }
        self.attach = {
            ACCOUNT:["p-example1"],
            "ou-abcd1234-abcdefgh":["p-example2"],
            "r-abcd1234":["p-example3"],
        }
    def list_parents(self, **kwargs):
        self.calls.append(("list_parents",kwargs))
        if kwargs["ChildId"] not in self.parent: raise RuntimeError("bad parent")
        return {**META("parents"), "Parents":[copy.deepcopy(
            self.parent[kwargs["ChildId"]])]}
    def list_policies_for_target(self, **kwargs):
        self.calls.append(("list_policies_for_target",kwargs))
        if kwargs.get("Filter") != "SERVICE_CONTROL_POLICY":
            raise RuntimeError("invalid policy type")
        return {**META("scp-list"), "Policies":[{
            "Type":"SERVICE_CONTROL_POLICY", "Id":p}
            for p in self.attach[kwargs["TargetId"]]]}


class AccessCensusTests(unittest.TestCase):
    def setUp(self):
        self.fx = GovernanceTests(
            "test_positive_real_code_checks_six_s3_reads_one_sts")
        self.fx.setUp()
        self.common = self.fx.common()
        self.s3 = FakeGovernanceS3(self.fx.fx.fx.report)
        self.sts = FakeSTS()
        self.control = S3ControlMock(bucket=self.fx.fx.fx.report["bucket"])
        self.iam = IAMMock()
        self.org = OrgMock()

    def collect(self, **replace):
        args = {
            "s3":self.s3, "sts":self.sts, "s3control":self.control,
            "iam":self.iam, "org":self.org,
        }
        args.update(replace)
        return observe_access_surface(
            args["s3"], args["sts"], args["s3control"], args["iam"],
            args["org"], **self.common, observed_at=TEST_NOW)

    def test_positive_requires_account_access_point_role_and_all_scp_ancestors(self):
        v = self.collect()
        verify_access_surface(v, **self.common)
        self.assertEqual(v["bucket_access_point_count"], 1)
        self.assertEqual(v["caller_role_attachment_count"], 1)
        self.assertEqual(v["caller_role_inline_count"], 1)
        self.assertTrue(v["caller_permissions_boundary_present"])
        self.assertEqual(v["scp_targets_count"], 3)
        self.assertEqual(v["scp_attachment_count"], 3)
        self.assertEqual(v["release_status"], "HOLD")
        self.assertFalse(v["effective_iam_permissions_verified"])
        self.assertFalse(v["all_s3_access_routes_verified"])
        self.assertFalse(v["scp_policy_semantics_verified"])
        text=json.dumps(v)
        for field in ("research-reader","arn:aws:iam::",
                      self.fx.fx.fx.report["bucket"], "p-example1"):
            self.assertNotIn(field,text)
        self.assertEqual(
            [x[0] for x in self.control.calls],
            ["get_public_access_block","list_access_points",
             "get_access_point","get_access_point_policy_status"])
        self.assertEqual(
            [x[0] for x in self.org.calls],
            ["list_parents","list_parents",
             "list_policies_for_target","list_policies_for_target",
             "list_policies_for_target"])

    def test_zero_access_points_is_explicitly_hashed(self):
        self.control.points=[]
        v=self.collect()
        self.assertEqual(v["bucket_access_point_count"], 0)
        verify_access_surface(v, **self.common)

    def test_account_level_public_access_block_requires_four_flags(self):
        for key in ("BlockPublicAcls","IgnorePublicAcls",
                    "BlockPublicPolicy","RestrictPublicBuckets"):
            with self.subTest(key=key):
                self.control=S3ControlMock(bucket=self.fx.fx.fx.report["bucket"])
                self.control.bpa["PublicAccessBlockConfiguration"][key]=False
                with self.assertRaises(AccessAuditError):self.collect()
        self.control=S3ControlMock(bucket=self.fx.fx.fx.report["bucket"])
        self.control.bpa["PublicAccessBlockConfiguration"].pop("BlockPublicPolicy")
        with self.assertRaises(AccessAuditError):self.collect()

    def test_public_or_internet_access_point_denied(self):
        for field,value in (
            ("NetworkOrigin","Internet"),
            ("VpcConfiguration",{}),
            ("Bucket","other-bucket"),
        ):
            with self.subTest(field=field):
                control=S3ControlMock(bucket=self.fx.fx.fx.report["bucket"])
                control.point[field]=value
                with self.assertRaises(AccessAuditError):
                    self.collect(s3control=control)
        control=S3ControlMock(bucket=self.fx.fx.fx.report["bucket"])
        control.policy["PolicyStatus"]["IsPublic"]=True
        with self.assertRaises(AccessAuditError):
            self.collect(s3control=control)

    def test_access_point_pagination_truncation_and_duplicates_fail_closed(self):
        control=S3ControlMock(bucket=self.fx.fx.fx.report["bucket"])
        control.points.append(dict(control.points[0]))
        with self.assertRaises(AccessAuditError):
            self.collect(s3control=control)
        control=S3ControlMock(bucket=self.fx.fx.fx.report["bucket"])
        class Endless(S3ControlMock):
            def list_access_points(self, **kwargs):
                return {**META("unending"),"AccessPointList":[],
                        "NextToken":"samepage"}
        endless=Endless(bucket=self.fx.fx.fx.report["bucket"])
        with self.assertRaises(AccessAuditError):
            self.collect(s3control=endless)

    def test_iam_role_is_really_sts_caller_and_attachment_inventory_only(self):
        self.iam.role["Role"]["Arn"]="arn:aws:iam::"+ACCOUNT+":role/other"
        with self.assertRaises(AccessAuditError):self.collect()
        self.iam=IAMMock()
        self.iam.inline["PolicyNames"]=["../bad"]
        with self.assertRaises(AccessAuditError):self.collect()
        self.iam=IAMMock()
        self.iam.attached["AttachedPolicies"].append(
            dict(self.iam.attached["AttachedPolicies"][0]))
        with self.assertRaises(AccessAuditError):self.collect()
        self.iam=IAMMock()
        sts=FakeSTS()
        sts.response["Arn"]="arn:aws:iam::"+ACCOUNT+":user/research"
        with self.assertRaises(AccessAuditError):self.collect(sts=sts)

    def test_scp_ancestry_and_attachment_coverage_denies_missing_or_cycle(self):
        org=OrgMock()
        org.parent["ou-abcd1234-abcdefgh"]=org.parent[ACCOUNT]
        with self.assertRaises(AccessAuditError):self.collect(org=org)
        org=OrgMock()
        org.parent[ACCOUNT]={"Id":"r-no","Type":"ROOT"}
        with self.assertRaises(AccessAuditError):self.collect(org=org)
        org=OrgMock()
        org.attach[ACCOUNT]=["p-example1","p-example1"]
        with self.assertRaises(AccessAuditError):self.collect(org=org)
        org=OrgMock()
        org.attach["r-abcd1234"]=["p-example3", "p-notvalid!"]
        with self.assertRaises(AccessAuditError):self.collect(org=org)
        org=OrgMock()
        class Denied(OrgMock):
            def list_parents(self, **kwargs):
                raise RuntimeError("secret AWS organizations account")
        with self.assertRaises(AccessAuditError) as ctx:
            self.collect(org=Denied())
        self.assertNotIn("secret",str(ctx.exception))

    def test_sts_bucket_failure_stops_rest_of_census(self):
        bad=copy.deepcopy(self.common)
        bad["receipt"]={**bad["receipt"],"observed_file_size_bytes":999999}
        with self.assertRaises(AccessAuditError):
            observe_access_surface(self.s3,self.sts,self.control,
                                   self.iam,self.org,**bad,observed_at=TEST_NOW)
        self.assertEqual(self.control.calls, [])
        self.assertEqual(self.iam.calls, [])
        self.assertEqual(self.org.calls, [])

    def test_offline_hmac_rejects_tamper_or_release_promotion(self):
        v=self.collect()
        for key,val in (
            ("audit_hmac","0"*64),
            ("effective_iam_permissions_verified",True),
            ("scp_policy_semantics_verified",True),
            ("all_s3_access_routes_verified",True),
            ("release_status","APPROVED"),
            ("bucket_access_point_count",999),
            ("scp_targets_count",0),
        ):
            with self.subTest(key=key):
                fake=copy.deepcopy(v);fake[key]=val
                with self.assertRaises(AccessAuditError):
                    verify_access_surface(fake,**self.common)
        v["prior_governance_observation"]["release_status"]="APPROVED"
        with self.assertRaises(AccessAuditError):
            verify_access_surface(v,**self.common)

    def test_readonly_client_construction_has_fixed_endpoints_and_profile(self):
        class Session:
            instances=[]
            def __init__(self,**kw):
                self.clients=[]
                self.kw=kw
                Session.instances.append(self)
            def client(self,service,**kw):
                self.clients.append((service,kw))
                return object()
        with patch("boto3.Session",Session):
            live_clients(profile="research-audit",region=REGION,account=ACCOUNT)
        calls=[item for ses in Session.instances for item in ses.clients]
        names=[x[0] for x in calls]
        self.assertIn("s3control",names)
        self.assertIn("iam",names)
        self.assertIn("organizations",names)
        endpoints={name:args["endpoint_url"] for name,args in calls}
        self.assertEqual(endpoints["s3control"],
                         "https://s3-control.il-central-1.amazonaws.com")
        self.assertEqual(endpoints["iam"],"https://iam.amazonaws.com")
        self.assertEqual(endpoints["organizations"],
                         "https://organizations.us-east-1.amazonaws.com")
        with self.assertRaises(AccessAuditError):
            live_clients(profile="../bad",region=REGION,account=ACCOUNT)


if __name__=="__main__":
    unittest.main()
