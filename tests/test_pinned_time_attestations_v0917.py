"""Synthetic-only signed timestamp authority proof for archived S3 receipts.

No credential, timestamp-service network call or real AWS object is used.
Test issuer Ed25519 keys are generated transiently within the test.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from scripts.verify_anchor_pinned_times_v0917 import main as time_cli
from services.research_api.audit_export_v0911 import canonical_bytes
from services.research_api.config import bootstrap_token, load_token
from services.research_api.pinned_time_attestations_v0917 import (
    PinnedTimeError, STAMP_DOMAIN, compare_pinned_times,
    verify_pinned_time_comparison,
)
from tests.test_anchor_governance_recheck_v0916 import AnchorRecheckTests, NOW, SECOND


def iso(ts):
    return ts.isoformat().replace("+00:00", "Z")


class PinnedTimeTests(unittest.TestCase):
    def setUp(self):
        fixture = AnchorRecheckTests(
            "test_two_25h_observations_produce_hmac_and_no_aws_calls")
        fixture.setUp()
        self.fx = fixture
        self.first, self.second = fixture.first, fixture.second
        self.pair = fixture.compare()
        self.key = Ed25519PrivateKey.generate()
        pub = self.key.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw)
        self.policy = {
            "schema_version": "0.9.17",
            "trust_status": "OPERATOR_PINNED_EXTERNAL_TIME_ISSUER_NOT_ACCREDITED",
            "authorities": [{
                "authority_id": "external-audit-clock",
                "role": "external_receipt_timestamp_signer",
                "ed25519_public_key_b64": base64.b64encode(pub).decode("ascii"),
            }],
        }
        self.common = {**fixture.common, "time_policy": self.policy}
        self.first_stamp = self.stamp(self.first, NOW + timedelta(minutes=2),
                                      nonce="first")
        self.second_stamp = self.stamp(self.second, SECOND + timedelta(minutes=2),
                                       nonce="second")

    def stamp(self, receipt, moment, *, nonce, signer=None, issuer="external-audit-clock"):
        claim = {
            "schema_version": "0.9.17",
            "scope": "signed_governance_receipt_sha256",
            "authority_id": issuer,
            "signed_anchor_sha256": self.pair["signed_anchor_sha256"],
            "binding_sha256": self.pair["binding_sha256"],
            "subject_observation_sha256":
                sha256(canonical_bytes(receipt)).hexdigest(),
            "issued_at_utc": iso(moment),
            "request_nonce_sha256": sha256(nonce.encode()).hexdigest(),
        }
        signature = (self.key if signer is None else signer).sign(
            STAMP_DOMAIN + canonical_bytes(claim))
        return {
            "statement": claim,
            "signature_b64": base64.b64encode(signature).decode("ascii"),
        }

    def compare(self, first_stamp=None, second_stamp=None, **changes):
        return compare_pinned_times(
            changes.pop("first", self.first),
            changes.pop("second", self.second),
            changes.pop("pair", self.pair),
            self.first_stamp if first_stamp is None else first_stamp,
            self.second_stamp if second_stamp is None else second_stamp,
            **{**self.common, **changes},
        )

    def test_two_pinned_time_signatures_and_25h_interval(self):
        out = self.compare()
        self.assertEqual(out["signed_interval_seconds"], 90000)
        self.assertTrue(out["pinned_ed25519_time_signatures_verified"])
        self.assertTrue(out["two_governance_receipts_verified"])
        self.assertFalse(out["authority_identity_independently_accredited"])
        self.assertFalse(out["independent_timestamp_service_contacted"])
        self.assertFalse(out["rfc3161_token_verified"])
        self.assertFalse(out["continuous_object_lock_verified"])
        self.assertEqual(out["research_release_status"], "HOLD")
        checked = verify_pinned_time_comparison(
            out, self.first, self.second, self.pair,
            self.first_stamp, self.second_stamp, **self.common)
        self.assertTrue(checked["signed_time_interval_verified"])
        self.assertFalse(checked["real_timestamp_service_contacted"])

    def test_no_aws_calls_during_signed_time_comparison(self):
        self.fx.base.s3.calls.clear()
        self.fx.second_s3.calls.clear()
        self.fx.base.sts.calls = 0
        self.fx.second_sts.calls = 0
        self.compare()
        self.assertEqual(self.fx.base.s3.calls, [])
        self.assertEqual(self.fx.second_s3.calls, [])
        self.assertEqual(self.fx.base.sts.calls, 0)
        self.assertEqual(self.fx.second_sts.calls, 0)

    def test_exact_24h_signed_gap_accepted(self):
        second = self.fx.observe_later(NOW + timedelta(hours=24))
        pair = self.fx.compare(second=second)
        stamp2 = self.stamp(
            second, NOW + timedelta(hours=24, minutes=2), nonce="exact")
        out = self.compare(second_stamp=stamp2, second=second, pair=pair)
        self.assertEqual(out["signed_interval_seconds"], 86400)

    def test_23h50m_signed_gap_refused_even_if_local_24h(self):
        second = self.fx.observe_later(NOW + timedelta(hours=24))
        pair = self.fx.compare(second=second)
        stamp2 = self.stamp(
            second, NOW + timedelta(hours=24), nonce="too-short")
        with self.assertRaises(PinnedTimeError):
            self.compare(second_stamp=stamp2, second=second, pair=pair)

    def test_signature_must_follow_receipt_within_15m(self):
        for delta in (-1, 901):
            with self.subTest(delta=delta):
                bad = self.stamp(
                    self.first, NOW + timedelta(seconds=delta),
                    nonce=f"lag-{delta}")
                with self.assertRaises(PinnedTimeError):
                    self.compare(first_stamp=bad)

    def test_wrong_digest_fails_even_with_correct_signature(self):
        claim = self.stamp(self.first, NOW + timedelta(minutes=2),
                           nonce="wrong")
        claim["statement"]["subject_observation_sha256"] = "f"*64
        claim["signature_b64"] = base64.b64encode(self.key.sign(
            STAMP_DOMAIN + canonical_bytes(claim["statement"])
        )).decode("ascii")
        with self.assertRaises(PinnedTimeError):
            self.compare(first_stamp=claim)

    def test_self_signed_unpinned_authority_rejected(self):
        adversary = Ed25519PrivateKey.generate()
        forged = self.stamp(
            self.first, NOW + timedelta(minutes=2), nonce="forged",
            signer=adversary)
        with self.assertRaises(PinnedTimeError):
            self.compare(first_stamp=forged)

    def test_operator_anchor_key_cannot_be_timestamp_authority(self):
        duplicate = deepcopy(self.policy)
        duplicate["authorities"][0]["ed25519_public_key_b64"] = (
            self.fx.base.fx.policy["signers"][0]["ed25519_public_key_b64"]
        )
        with self.assertRaises(PinnedTimeError):
            self.compare(time_policy=duplicate)

    def test_wrong_signer_role_duplicate_policy_and_unpinned_scope(self):
        for modified in (
            {**self.policy, "trust_status": "ACCREDITED"},
            {**self.policy, "authorities": []},
            {**self.policy, "authorities": self.policy["authorities"] * 2},
            {**self.policy, "authorities": [
                {**self.policy["authorities"][0], "role": "root"}]},
        ):
            with self.subTest(modified=str(modified)[:60]):
                with self.assertRaises(PinnedTimeError):
                    self.compare(time_policy=modified)

    def test_reused_nonce_with_distinct_signatures_rejected(self):
        repeated = self.stamp(
            self.second, SECOND + timedelta(minutes=2), nonce="first")
        with self.assertRaises(PinnedTimeError):
            self.compare(second_stamp=repeated)

    def test_timestamp_authority_change_between_observations_rejected(self):
        other = Ed25519PrivateKey.generate()
        pub = other.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        policy = deepcopy(self.policy)
        policy["authorities"].append({
            "authority_id": "another-time-issuer",
            "role": "external_receipt_timestamp_signer",
            "ed25519_public_key_b64": base64.b64encode(pub).decode("ascii"),
        })
        different = self.stamp(
            self.second, SECOND + timedelta(minutes=2), nonce="other-issuer",
            signer=other, issuer="another-time-issuer")
        with self.assertRaises(PinnedTimeError):
            self.compare(second_stamp=different, time_policy=policy)

    def test_timestamp_tampering_signature_and_malformed_nonce_denied(self):
        for field, data in (
            ("signature_b64", "not-base64"),
            ("signature_b64", base64.b64encode(b"\0"*64).decode()),
        ):
            bad = deepcopy(self.first_stamp)
            bad[field] = data
            with self.assertRaises(PinnedTimeError):
                self.compare(first_stamp=bad)
        bad = deepcopy(self.first_stamp)
        bad["statement"]["request_nonce_sha256"] = "BAD"
        with self.assertRaises(PinnedTimeError):
            self.compare(first_stamp=bad)
        bad = deepcopy(self.second_stamp)
        bad["statement"]["issued_at_utc"] = "2028-03-02T13:00:00+00:00"
        with self.assertRaises(PinnedTimeError):
            self.compare(second_stamp=bad)

    def test_comparison_tampering_false_claim_and_wrong_hmac_denied(self):
        original = self.compare()
        for field, data in (
            ("local_comparison_hmac_sha256", "0"*64),
            ("signed_interval_seconds", 1),
            ("pinned_ed25519_time_signatures_verified", False),
            ("authority_identity_independently_accredited", True),
            ("rfc3161_token_verified", True),
            ("continuous_object_lock_verified", True),
            ("research_release_status", "PASS"),
        ):
            with self.subTest(field=field):
                changed = deepcopy(original)
                changed[field] = data
                with self.assertRaises(PinnedTimeError):
                    verify_pinned_time_comparison(
                        changed, self.first, self.second, self.pair,
                        self.first_stamp, self.second_stamp, **self.common)
        extra = deepcopy(original)
        extra["private_aws_bucket"] = "secret"
        with self.assertRaises(PinnedTimeError):
            verify_pinned_time_comparison(
                extra, self.first, self.second, self.pair,
                self.first_stamp, self.second_stamp, **self.common)

    def test_wrong_paired_receipt_or_secret_rejected(self):
        changed = deepcopy(self.pair)
        changed["signed_anchor_sha256"] = "f"*64
        with self.assertRaises(PinnedTimeError):
            self.compare(pair=changed)
        with self.assertRaises(PinnedTimeError):
            self.compare(local_key="not-a-key")

    def test_cli_compares_and_verifies_without_external_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = {
                "signed-anchor": self.fx.base.fx.raw,
                "trusted-policy": json.dumps(
                    self.fx.base.fx.policy).encode(),
                "archive-binding": json.dumps(
                    self.fx.base.fx.binding).encode(),
                "first-observation": json.dumps(self.first).encode(),
                "second-observation": json.dumps(self.second).encode(),
                "paired-comparison": json.dumps(self.pair).encode(),
                "first-timestamp": json.dumps(self.first_stamp).encode(),
                "second-timestamp": json.dumps(self.second_stamp).encode(),
                "time-authority-policy": json.dumps(self.policy).encode(),
            }
            args = []
            for name, data in names.items():
                path = root / (name + ".json")
                path.write_bytes(data)
                args.extend(["--" + name, str(path)])
            token = root / "local-key"
            bootstrap_token(token)
            from services.research_api.anchor_governance_v0915 import _mac
            from services.research_api.anchor_governance_recheck_v0916 import (
                compare_anchor_governance,
            )
            secret = load_token(token)
            common = {**self.common, "local_key": secret}
            first_report = self.first
            second_report = self.second
            # Re-sign observations with the CLI's protected token by
            # recreating their complete local reports in the mock fixture.
            from tests.test_anchor_governance_v0915 import FakeBucketS3, FakeSts
            from tests.test_anchor_governance_recheck_v0916 import (
                DistinctS3, DistinctSts,
            )
            from services.research_api.anchor_governance_v0915 import (
                observe_anchor_governance,
            )
            first_report = observe_anchor_governance(
                FakeBucketS3(self.fx.base.fx.binding),
                FakeSts(self.fx.base.fx.binding["expected_bucket_owner"]),
                observed_at=NOW, **{**self.fx.common, "local_key": secret})
            second_report = observe_anchor_governance(
                DistinctS3(self.fx.base.fx.binding),
                DistinctSts(self.fx.base.fx.binding["expected_bucket_owner"]),
                observed_at=SECOND, **{**self.fx.common, "local_key": secret})
            pair_report = compare_anchor_governance(
                first_report, second_report,
                **{**self.fx.common, "local_key": secret})
            file_map = {
                "first-observation": first_report,
                "second-observation": second_report,
                "paired-comparison": pair_report,
                "first-timestamp": self.stamp(
                    first_report, NOW + timedelta(minutes=2), nonce="cli-one"),
                "second-timestamp": self.stamp(
                    second_report, SECOND + timedelta(minutes=2), nonce="cli-two"),
            }
            for name, obj in file_map.items():
                (root / (name + ".json")).write_text(json.dumps(obj))
            args.extend(["--local-key-file", str(token)])
            result = root / "time-report.json"
            with patch("scripts.s3_governance.live_clients") as network:
                self.assertEqual(time_cli(
                    ["compare", *args, "--output", str(result)]), 0)
                self.assertTrue(result.is_file())
                self.assertEqual(time_cli(
                    ["verify", *args, "--report", str(result)]), 0)
                self.assertEqual(time_cli(
                    ["compare", *args, "--output", str(result)]), 1)
                network.assert_not_called()

    def test_cli_without_provisioned_timestamps_is_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            absent = str(Path(directory) / "missing.json")
            args = ["compare"]
            for name in (
                "signed-anchor", "trusted-policy", "archive-binding",
                "local-key-file", "first-observation", "second-observation",
                "paired-comparison", "first-timestamp", "second-timestamp",
                "time-authority-policy",
            ):
                args.extend(["--" + name, absent])
            args.extend(["--output", str(Path(directory) / "never.json")])
            self.assertEqual(time_cli(args), 1)
            self.assertFalse((Path(directory) / "never.json").exists())


if __name__ == "__main__":
    unittest.main()
