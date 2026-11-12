"""v0.9.14 strict, read-only S3 object-version checks of signed anchor files."""
from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, PrivateFormat, PublicFormat, NoEncryption,
)

from scripts.audit_anchor_s3_v0914 import main as archive_cli
from services.research_api.anchor_s3_v0914 import (
    AnchorArchiveError, _local_chain, observe_anchor_s3_version,
    verify_anchor_s3_observation,
)
from services.research_api.audit_export_v0911 import export_work_link_audit
from services.research_api.config import bootstrap_token, load_token
from services.research_api.revision_anchor_v0913 import (
    capture_anchor, sign_anchor,
)
from services.research_api.revision_ledger_v0912 import (
    ZERO_CHAIN, append_revision, bootstrap_head, scope_id,
)
from tests.test_revision_ledger_v0912 import FakeClient
from tests.test_work_link_audit_v099 import AuditStore
from tests.test_work_comparison import LEFT, RIGHT


NOW = datetime(2028, 3, 1, 12, 0, tzinfo=timezone.utc)
RETAIN = datetime(2031, 1, 1, 0, 0, tzinfo=timezone.utc)


class FakeS3:
    def __init__(self, binding, *, retention=RETAIN):
        self.binding = binding
        self.retention = retention
        self.calls = []
        self.head_edits = {}
        self.lock_edits = {}
        self.fail = False

    def head_object(self, **params):
        self.calls.append(("head_object", deepcopy(params)))
        if self.fail:
            raise RuntimeError("SECRET-CONNECTION-DETAIL")
        value = {
            "ResponseMetadata": {
                "HTTPStatusCode": 200, "RequestId": "head-request-123",
            },
            "VersionId": self.binding["version_id"],
            "DeleteMarker": False,
            "ContentLength": self.binding["content_length"],
            "ChecksumType": "FULL_OBJECT",
            "ChecksumSHA256": base64.b64encode(
                bytes.fromhex(self.binding["content_sha256"])
            ).decode("ascii"),
            "ObjectLockMode": "COMPLIANCE",
            "ObjectLockRetainUntilDate": self.retention,
        }
        return {**value, **self.head_edits}

    def get_object_retention(self, **params):
        self.calls.append(("get_object_retention", deepcopy(params)))
        return {
            "ResponseMetadata": {
                "HTTPStatusCode": 200, "RequestId": "retain-request-456",
            },
            "Retention": {
                "Mode": "COMPLIANCE", "RetainUntilDate": self.retention,
                **self.lock_edits,
            },
        }


class SignedAnchorS3Tests(unittest.TestCase):
    def setUp(self):
        self.local_key = "L" * 50
        self.client = FakeClient()
        export = export_work_link_audit(
            AuditStore(), source_work_id=LEFT, target_work_id=RIGHT,
            secret=self.local_key, now=1234567890,
        )
        bootstrap_head(self.client, export, secret=self.local_key)
        append_revision(
            self.client, export, secret=self.local_key,
            expected_sequence=0, expected_chain_sha256=ZERO_CHAIN,
            now=1234567891,
        )
        priv = Ed25519PrivateKey.generate()
        self.private = priv.private_bytes(
            Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        pub = priv.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw)
        self.anchor = capture_anchor(self.client, LEFT, RIGHT, now=1234567892)
        self.signed = sign_anchor(
            self.anchor, signer_id="audit-archiver",
            private_key_bytes=self.private)
        self.policy = {
            "schema_version": "0.9.13",
            "trust_status": "OPERATOR_PINNED_IDENTITY_NOT_ATTESTED",
            "signers": [{
                "signer_id": "audit-archiver",
                "role": "audit_revision_operator",
                "scope_id": scope_id(LEFT, RIGHT),
                "ed25519_public_key_b64": base64.b64encode(pub).decode(),
            }],
        }
        self.raw = (json.dumps(
            self.signed, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        self.binding = {
            "schema_version": "0.9.14",
            "provider": "aws_s3",
            "bucket": "private-audit-records",
            "object_key": "anchors/checkpoint-001.json",
            "version_id": "signed-version-001",
            "expected_bucket_owner": "123456789012",
            "aws_region": "il-central-1",
            "content_sha256": sha256(self.raw).hexdigest(),
            "content_length": len(self.raw),
            "minimum_retain_until_utc": "2030-01-01T00:00:00Z",
            "evidence_origin": "operator_pinned_unverified",
        }
        self.s3 = FakeS3(self.binding)
        self.args = {
            "envelope": self.signed,
            "pin_policy": self.policy,
            "signed_bytes": self.raw,
            "binding": self.binding,
            "local_key": self.local_key,
        }

    def inspect(self):
        return observe_anchor_s3_version(
            self.s3, **self.args, observed_at=NOW)

    def verify(self, doc):
        return verify_anchor_s3_observation(doc, **self.args)

    def test_exact_version_two_read_only_calls_and_full_sha(self):
        report = self.inspect()
        self.assertEqual([name for name,_ in self.s3.calls], [
            "head_object", "get_object_retention"])
        expected = {
            "Bucket": self.binding["bucket"],
            "Key": self.binding["object_key"],
            "VersionId": self.binding["version_id"],
            "ExpectedBucketOwner": self.binding["expected_bucket_owner"],
        }
        self.assertEqual(self.s3.calls[0][1], {
            **expected, "ChecksumMode": "ENABLED"})
        self.assertEqual(self.s3.calls[1][1], expected)
        self.assertTrue(report["aws_full_object_sha256_matched"])
        self.assertEqual(report["retention_until_utc"],
                         "2031-01-01T00:00:00Z")
        self.assertEqual(report["anchor_file_sha256"],
                         sha256(self.raw).hexdigest())
        self.assertNotIn("private-audit-records", json.dumps(report))
        self.assertNotIn("signed-version-001", json.dumps(report))
        self.assertTrue(self.verify(report)[
            "exact_version_checksum_and_retention_report_verified"])
        self.assertFalse(self.verify(report)["aws_current_state_rechecked"])

    def test_signed_file_must_be_exact_envelope_before_remote_read(self):
        self.args["signed_bytes"] = self.raw.replace(
            b'"audit-archiver"', b'"other-archiver"')
        with self.assertRaises(AnchorArchiveError):
            self.inspect()
        self.assertEqual(self.s3.calls, [])
        self.args["signed_bytes"] = b'{"unexpected":"data"}'
        self.binding["content_sha256"] = sha256(
            self.args["signed_bytes"]).hexdigest()
        self.binding["content_length"] = len(self.args["signed_bytes"])
        with self.assertRaises(AnchorArchiveError):
            self.inspect()
        self.assertEqual(self.s3.calls, [])

    def test_malformed_duplicate_json_rejected_before_aws(self):
        raw = self.raw[:-2] + b',"signer_id":"audit-archiver"}'
        self.args["signed_bytes"] = raw
        self.binding["content_sha256"] = sha256(raw).hexdigest()
        self.binding["content_length"] = len(raw)
        with self.assertRaises(AnchorArchiveError):
            self.inspect()
        self.assertEqual(self.s3.calls, [])

    def test_wrong_version_or_owner_scope_refuses_remote(self):
        for key, bad in (
            ("expected_bucket_owner","999"),("aws_region","bad-region"),
            ("version_id","../latest"),("version_id","null"),
            ("bucket","UPPERCASE"),
            ("object_key","../secret"),("provider","other-provider"),
            ("evidence_origin","independently_verified"),
        ):
            with self.subTest(key=key):
                b=deepcopy(self.binding)
                b[key]=bad
                self.args["binding"]=b
                with self.assertRaises(AnchorArchiveError):
                    self.inspect()
                self.assertEqual(self.s3.calls, [])
        self.args["binding"]=self.binding

    def test_full_object_sha256_and_length_are_mandatory(self):
        edits = (
            {"ChecksumType": "COMPOSITE"},
            {"ChecksumSHA256": base64.b64encode(b"x"*32).decode()},
            {"ChecksumSHA256": "!"}, {"ContentLength": True},
            {"ContentLength": len(self.raw)+1},
            {"VersionId": "latest"}, {"DeleteMarker": True},
            {"ObjectLockMode": "GOVERNANCE"},
        )
        for delta in edits:
            with self.subTest(delta=delta):
                self.s3.head_edits=delta
                with self.assertRaises(AnchorArchiveError):
                    self.inspect()
                self.s3.calls.clear()
        self.s3.head_edits={}

    def test_compliance_retention_must_match_both_independent_reads(self):
        for edit in (
            {"Mode": "GOVERNANCE"},
            {"RetainUntilDate": datetime(2032,1,1,tzinfo=timezone.utc)},
            {"RetainUntilDate": datetime(2029,1,1,tzinfo=timezone.utc)},
        ):
            with self.subTest(edit=edit):
                self.s3.lock_edits=edit
                with self.assertRaises(AnchorArchiveError):
                    self.inspect()
                self.s3.calls.clear()
        self.s3.lock_edits={}
        self.s3.head_edits={
            "ObjectLockRetainUntilDate": datetime(
                2032,1,1,tzinfo=timezone.utc)}
        with self.assertRaises(AnchorArchiveError):
            self.inspect()

    def test_expired_operator_retention_minimum_fails_before_aws(self):
        self.binding["minimum_retain_until_utc"] = "2027-01-01T00:00:00Z"
        with self.assertRaises(AnchorArchiveError):
            self.inspect()
        self.assertEqual(self.s3.calls, [])

    def test_aws_failure_does_not_echo_s3_exception_or_private_ids(self):
        self.s3.fail=True
        try:
            self.inspect()
        except AnchorArchiveError as exc:
            self.assertNotIn("SECRET-CONNECTION-DETAIL", str(exc))
            self.assertNotIn(self.binding["bucket"], str(exc))
        else:
            self.fail("Remote failure was accepted")

    def test_offline_observation_hmac_tampering_and_false_claims_fail(self):
        original=self.inspect()
        for key,bad in (
            ("local_observation_hmac","0"*64),
            ("aws_full_object_sha256_matched",False),
            ("external_archive_continuously_immutable_verified",True),
            ("source_rights_verified",True),
            ("graph_snapshot_verified",True),
            ("retention_until_utc","2029-01-01T00:00:00Z"),
            ("head_request_id_sha256","bad"),
            ("signed_anchor_sha256","0"*64),
            ("anchor_file_size_bytes",1),
        ):
            with self.subTest(key=key):
                edited=deepcopy(original)
                edited[key]=bad
                with self.assertRaises(AnchorArchiveError):
                    self.verify(edited)
        edited=deepcopy(original)
        edited["bucket"]="private-bucket"
        with self.assertRaises(AnchorArchiveError):
            self.verify(edited)

    def test_wrong_pinned_key_or_altered_binding_rejected_offline(self):
        report=self.inspect()
        forged=deepcopy(self.policy)
        forged["signers"][0]["scope_id"]="audit-scope:"+"0"*64
        self.args["pin_policy"]=forged
        with self.assertRaises(AnchorArchiveError):
            self.verify(report)
        self.args["pin_policy"]=self.policy
        self.binding["object_key"]="anchors/another.json"
        with self.assertRaises(AnchorArchiveError):
            self.verify(report)

    def test_offline_verify_never_touches_s3(self):
        report=self.inspect()
        self.s3.calls.clear()
        self.verify(report)
        self.assertEqual(self.s3.calls, [])

    def test_cli_inspect_needs_explicit_authorization_and_private_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            paths=[root/n for n in (
                "anchor.json","policy.json","binding.json","key.txt",
                "observed.json")]
            a,p,b,k,out=paths
            a.write_bytes(self.raw)
            p.write_text(json.dumps(self.policy), encoding="utf-8")
            b.write_text(json.dumps(self.binding), encoding="utf-8")
            bootstrap_token(k)
            key=load_token(k)
            self.args["local_key"]=key
            base=["--signed-anchor",str(a),
                  "--trusted-policy",str(p),
                  "--archive-binding",str(b),
                  "--local-key-file",str(k)]
            self.assertEqual(archive_cli([
                "inspect",*base,"--aws-profile","audit-read",
                "--output",str(out)]),2)
            self.assertFalse(out.exists())
            with patch("scripts.audit_anchor_s3_v0914.live_s3_client",
                       return_value=self.s3):
                self.assertEqual(archive_cli([
                    "inspect",*base,"--aws-profile","audit-read",
                    "--ack-live-aws-read-only","--output",str(out)]),0)
            self.assertTrue(out.exists())
            if os.name!="nt":
                self.assertEqual(out.stat().st_mode & 0o777, 0o600)
            before=len(self.s3.calls)
            self.assertEqual(archive_cli([
                "verify",*base,"--observation",str(out)]),0)
            self.assertEqual(len(self.s3.calls), before)
            self.assertEqual(archive_cli([
                "verify",*base,"--observation",str(out)]),0)

    def test_cli_refuses_signed_file_symlinks_and_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            a=root/"anchor.json"
            p=root/"policy.json"
            b=root/"binding.json"
            k=root/"key"
            a.write_bytes(self.raw)
            p.write_text(json.dumps(self.policy))
            b.write_text(json.dumps(self.binding))
            bootstrap_token(k)
            alias=root/"alias.json"
            alias.symlink_to(a)
            baseline=["verify","--signed-anchor",str(alias),
                      "--trusted-policy",str(p),
                      "--archive-binding",str(b),
                      "--local-key-file",str(k),
                      "--observation",str(root/"absent.json")]
            self.assertEqual(archive_cli(baseline),1)
            a.write_bytes(b'{"a":1,"a":2}')
            baseline[baseline.index(str(alias))]=str(a)
            self.assertEqual(archive_cli(baseline),1)


if __name__=="__main__":
    unittest.main()
