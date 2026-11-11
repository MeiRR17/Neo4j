"""v0.9.13 separately pinned Ed25519 revision anchor and live prefix guards."""
from __future__ import annotations

import base64
from copy import deepcopy
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

from scripts.audit_revision_anchor_v0913 import main as anchor_cli
from services.research_api.audit_export_v0911 import export_work_link_audit
from services.research_api.revision_anchor_v0913 import (
    AnchorError, capture_anchor, compare_anchor_to_live,
    sign_anchor, verify_anchor,
)
from services.research_api.revision_ledger_v0912 import (
    ZERO_CHAIN, append_revision, bootstrap_head, scope_id,
)
from tests.test_revision_ledger_v0912 import FakeClient
from tests.test_work_link_audit_v099 import AuditStore
from tests.test_work_comparison import LEFT, RIGHT


class PinnedAnchorTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeClient()
        self.secret = "S" * 52
        self.signed_export = export_work_link_audit(
            AuditStore(), source_work_id=LEFT, target_work_id=RIGHT,
            secret=self.secret, now=1234567890)
        bootstrap_head(self.db, self.signed_export, secret=self.secret)
        self.key = Ed25519PrivateKey.generate()
        self.raw_key = self.key.private_bytes(
            Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        pub = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.policy = {
            "schema_version": "0.9.13",
            "trust_status": "OPERATOR_PINNED_IDENTITY_NOT_ATTESTED",
            "signers": [{
                "signer_id": "archiver-primary",
                "role": "audit_revision_operator",
                "scope_id": scope_id(LEFT, RIGHT),
                "ed25519_public_key_b64": base64.b64encode(pub).decode("ascii"),
            }],
        }

    def append(self, seq=0, prev=ZERO_CHAIN, at=1234567891):
        return append_revision(
            self.db, self.signed_export, secret=self.secret,
            expected_sequence=seq, expected_chain_sha256=prev, now=at)

    def witness(self, *, at=1234567892):
        anchor = capture_anchor(self.db, LEFT, RIGHT, now=at)
        signed = sign_anchor(
            anchor, signer_id="archiver-primary",
            private_key_bytes=self.raw_key)
        return signed

    def test_empty_root_and_independently_pinned_signature(self):
        signed = self.witness()
        self.assertEqual(signed["anchor"]["anchored_sequence"], 0)
        self.assertEqual(signed["anchor"]["anchored_chain_sha256"], ZERO_CHAIN)
        verified = verify_anchor(signed, self.policy)
        self.assertTrue(verified["signature_verified_against_pinned_public_key"])
        self.assertFalse(verified["signer_identity_independently_verified"])
        self.assertFalse(verified["external_object_lock_verified"])
        self.assertEqual(verified["research_release_status"], "HOLD")
        self.assertEqual(compare_anchor_to_live(
            self.db, signed, self.policy)["revisions_after_anchor"], 0)

    def test_signed_nonzero_head_and_exact_live_chain(self):
        first = self.append()
        signed = self.witness()
        self.assertEqual(signed["anchor"]["anchored_sequence"], 1)
        self.assertEqual(signed["anchor"]["anchored_revision_id"],
                         first["revision_id"])
        result = compare_anchor_to_live(self.db, signed, self.policy)
        self.assertEqual(result["current_sequence"], 1)
        self.assertTrue(result["live_prefix_matches_pinned_anchor"])
        self.assertFalse(result["continuous_storage_immutability_verified"])

    def test_later_append_preserves_original_pinned_prefix(self):
        first = self.append()
        signed = self.witness()
        self.append(seq=1, prev=first["chain_sha256"], at=1234567893)
        result = compare_anchor_to_live(self.db, signed, self.policy)
        self.assertEqual(result["current_sequence"], 2)
        self.assertEqual(result["revisions_after_anchor"], 1)
        self.assertEqual(result["anchored_sequence"], 1)

    def test_rollback_history_detected(self):
        self.append()
        signed = self.witness()
        key = scope_id(LEFT, RIGHT)
        self.db.records[key].clear()
        self.db.heads[key].update(
            sequence=0, latest_revision_id="", chain_sha256=ZERO_CHAIN)
        with self.assertRaises(AnchorError):
            compare_anchor_to_live(self.db, signed, self.policy)

    def test_rewritten_anchored_record_detected(self):
        first = self.append()
        signed = self.witness()
        self.append(seq=1, prev=first["chain_sha256"], at=1234567893)
        self.db.records[scope_id(LEFT, RIGHT)][0]["observed_link_count"] = 99
        with self.assertRaises(AnchorError):
            compare_anchor_to_live(self.db, signed, self.policy)

    def test_pinned_scope_rejects_other_direction(self):
        self.append()
        signed = self.witness()
        changed = deepcopy(signed)
        changed["anchor"]["source_work_id"] = RIGHT
        with self.assertRaises(AnchorError):
            verify_anchor(changed, self.policy)
        switched = deepcopy(self.policy)
        switched["signers"][0]["scope_id"] = scope_id(RIGHT, LEFT)
        with self.assertRaises(AnchorError):
            verify_anchor(signed, switched)

    def test_tamper_metadata_and_hash_rejected(self):
        signed = self.witness()
        tampered = deepcopy(signed)
        tampered["anchor"]["captured_at_unix"] += 1
        with self.assertRaises(AnchorError):
            verify_anchor(tampered, self.policy)
        tampered = deepcopy(signed)
        tampered["anchor_sha256"] = "f" * 64
        with self.assertRaises(AnchorError):
            verify_anchor(tampered, self.policy)
        tampered = deepcopy(signed)
        tampered["signature_b64"] = base64.b64encode(b"\x00"*64).decode("ascii")
        with self.assertRaises(AnchorError):
            verify_anchor(tampered, self.policy)

    def test_false_release_rights_or_snapshot_claim_denied(self):
        for key in (
            "graph_snapshot_verified", "source_graph_immutable",
            "external_object_lock_verified", "source_rights_verified",
            "signer_identity_independently_verified",
        ):
            changed = deepcopy(self.witness())
            changed["anchor"][key] = True
            with self.subTest(key=key), self.assertRaises(AnchorError):
                verify_anchor(changed, self.policy)
        extra = deepcopy(self.witness())
        extra["anchor"]["raw_source_text"] = "SECRET"
        with self.assertRaises(AnchorError):
            verify_anchor(extra, self.policy)

    def test_wrong_private_key_length_or_signer_name_denied(self):
        anchor = capture_anchor(self.db, LEFT, RIGHT)
        with self.assertRaises(AnchorError):
            sign_anchor(anchor, signer_id="archiver-primary", private_key_bytes=b"x")
        with self.assertRaises(AnchorError):
            sign_anchor(anchor, signer_id="invalid name", private_key_bytes=self.raw_key)
        other = Ed25519PrivateKey.generate().private_bytes(
            Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        signed = sign_anchor(anchor, signer_id="archiver-primary",
                             private_key_bytes=other)
        with self.assertRaises(AnchorError):
            verify_anchor(signed, self.policy)

    def test_trust_policy_denies_unpinned_or_duplicate_signers(self):
        signed = self.witness()
        for policy in (
            {},
            {"schema_version":"0.9.13","trust_status":"TRUSTED","signers":self.policy["signers"]},
            {**self.policy,"signers":[]},
            {**self.policy,"signers":self.policy["signers"]*2},
        ):
            with self.subTest(policy=str(policy)[:45]),self.assertRaises(AnchorError):
                verify_anchor(signed, policy)

    def test_no_network_or_db_needed_for_detached_signature_check(self):
        signed = self.witness()
        self.db.calls.clear()
        verify_anchor(signed, self.policy)
        self.assertEqual(self.db.calls, [])

    def test_empty_anchor_does_not_certify_future_work_data(self):
        signed = self.witness()
        self.append()
        result = compare_anchor_to_live(self.db, signed, self.policy)
        self.assertEqual(result["revisions_after_anchor"], 1)
        self.assertFalse(result["source_graph_immutable"])
        self.assertFalse(result["external_object_lock_verified"])

    def test_cli_sign_verify_and_live_compare_private_files(self):
        with tempfile.TemporaryDirectory() as root:
            directory=Path(root)
            statement=directory/"capture.json"
            policy_file=directory/"policy.json"
            key_file=directory/"operator.raw"
            signature_file=directory/"signature.json"
            statement.write_text(json.dumps(capture_anchor(self.db,LEFT,RIGHT)),
                                 encoding="utf-8")
            policy_file.write_text(json.dumps(self.policy),encoding="utf-8")
            key_file.write_bytes(self.raw_key)
            key_file.chmod(0o600)
            self.assertEqual(anchor_cli([
                "sign","--anchor",str(statement),
                "--signer-id","archiver-primary",
                "--private-key",str(key_file),
                "--output",str(signature_file)]),0)
            self.assertEqual(anchor_cli([
                "verify","--signed",str(signature_file),
                "--policy",str(policy_file)]),0)
            with patch("scripts.audit_revision_anchor_v0913.LocalQueryClient",
                       return_value=self.db):
                self.assertEqual(anchor_cli([
                    "compare","--signed",str(signature_file),
                    "--policy",str(policy_file)]),0)
                capture_file=directory/"captured2.json"
                self.assertEqual(anchor_cli([
                    "capture","--source-work-id",LEFT,
                    "--target-work-id",RIGHT,
                    "--output",str(capture_file)]),0)
            self.assertTrue(capture_file.is_file())
            self.assertEqual(anchor_cli([
                "sign","--anchor",str(statement),
                "--signer-id","archiver-primary",
                "--private-key",str(key_file),
                "--output",str(signature_file)]),1)

    def test_cli_rejects_unsafe_key_permissions_and_symlinks(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)
            anchor=p/"anchor.json"
            policy=p/"policy.json"
            key=p/"rawkey"
            anchor.write_text(json.dumps(capture_anchor(self.db,LEFT,RIGHT)))
            policy.write_text(json.dumps(self.policy))
            key.write_bytes(self.raw_key)
            key.chmod(0o644)
            args=["sign","--anchor",str(anchor),
                  "--signer-id","archiver-primary","--private-key",str(key),
                  "--output",str(p/"out.json")]
            if os.name != "nt":
                self.assertEqual(anchor_cli(args),1)
            key.chmod(0o600)
            sym=p/"link.key"
            sym.symlink_to(key)
            args[args.index(str(key))]=str(sym)
            self.assertEqual(anchor_cli(args),1)
            self.assertFalse((p/"out.json").exists())

    def test_invalid_anchor_sequence_and_fake_id_fail_before_signing(self):
        anchor=capture_anchor(self.db,LEFT,RIGHT)
        for key,value in (
            ("anchored_sequence",True),
            ("anchored_sequence",33),
            ("anchored_revision_id","audit-rev:"+"1"*64),
            ("anchored_chain_sha256","1"*64),
            ("research_release_status","PASS"),
            ("scope_id","audit-scope:"+"0"*64),
        ):
            bad=deepcopy(anchor)
            bad[key]=value
            with self.subTest(key=key),self.assertRaises(AnchorError):
                sign_anchor(
                    bad,signer_id="archiver-primary",
                    private_key_bytes=self.raw_key)


if __name__=="__main__":
    unittest.main()
