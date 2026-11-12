"""v0.9.16 two time-separated, mocked-only S3 archive observations.

Tests use existing synthetic signed Ed25519/Neo4j fixtures and stubbed
S3 and STS clients. No AWS account, outbound network or real source.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from scripts.audit_anchor_governance_v0915 import main as archive_cli
from services.research_api.anchor_governance_recheck_v0916 import (
    AnchorRecheckError, MIN_INTERVAL_SECONDS,
    compare_anchor_governance, verify_anchor_governance_comparison,
)
from services.research_api.anchor_governance_v0915 import (
    observe_anchor_governance,
)
from services.research_api.config import bootstrap_token, load_token
from tests.test_anchor_governance_v0915 import (
    AnchorGovernanceTests, FakeBucketS3, FakeSts,
)
from tests.test_anchor_s3_v0914 import NOW


SECOND = NOW + timedelta(days=1, hours=1)


class DistinctS3(FakeBucketS3):
    def head_object(self, **params):
        value = super().head_object(**params)
        value["ResponseMetadata"]["RequestId"] += "-later"
        return value

    def get_object_retention(self, **params):
        value = super().get_object_retention(**params)
        value["ResponseMetadata"]["RequestId"] += "-later"
        return value

    def _control(self, method, **params):
        value = super()._control(method, **params)
        value["ResponseMetadata"]["RequestId"] += "-later"
        return value


class DistinctSts(FakeSts):
    def get_caller_identity(self):
        value = super().get_caller_identity()
        value["ResponseMetadata"]["RequestId"] += "-later"
        return value


class AnchorRecheckTests(unittest.TestCase):
    def setUp(self):
        base = AnchorGovernanceTests(
            "test_seven_explicit_read_only_calls_and_offline_hmac")
        base.setUp()
        self.base = base
        self.common = dict(base.common)
        self.first = base.observe()
        self.second_s3 = DistinctS3(base.fx.binding)
        self.second_sts = DistinctSts(base.fx.binding["expected_bucket_owner"])
        self.second = self.observe_later()

    def observe_later(self, when=SECOND):
        return observe_anchor_governance(
            self.second_s3, self.second_sts,
            observed_at=when, **self.common,
        )

    def compare(self, first=None, second=None):
        return compare_anchor_governance(
            self.first if first is None else first,
            self.second if second is None else second,
            **self.common,
        )

    def verify(self, result, first=None, second=None):
        return verify_anchor_governance_comparison(
            result,
            self.first if first is None else first,
            self.second if second is None else second,
            **self.common,
        )

    def test_two_25h_observations_produce_hmac_and_no_aws_calls(self):
        self.base.s3.calls.clear()
        self.base.sts.calls = 0
        self.second_s3.calls.clear()
        self.second_sts.calls = 0
        result = self.compare()
        self.assertEqual(result["observed_interval_seconds"], 25 * 3600)
        self.assertEqual(result["minimum_interval_seconds"],
                         MIN_INTERVAL_SECONDS)
        self.assertTrue(result["distinct_provider_request_ids"])
        self.assertTrue(result["same_signed_anchor_bytes"])
        self.assertTrue(result["nondecreasing_retention_observed"])
        self.assertFalse(result["external_timestamp_verified"])
        self.assertFalse(result["aws_real_time_continuity_proven"])
        self.assertEqual(result["research_release_status"], "HOLD")
        checked = self.verify(result)
        self.assertTrue(checked["two_local_observation_hmacs_verified"])
        self.assertFalse(checked["aws_current_state_rechecked"])
        self.assertEqual(self.base.s3.calls, [])
        self.assertEqual(self.second_s3.calls, [])
        self.assertEqual(self.base.sts.calls, 0)
        self.assertEqual(self.second_sts.calls, 0)
        output = json.dumps(result)
        for identifier in (
            self.base.fx.binding["bucket"],
            self.base.fx.binding["object_key"],
            self.base.fx.binding["version_id"],
            self.base.fx.binding["expected_bucket_owner"],
        ):
            self.assertNotIn(identifier, output)

    def test_exact_24h_interval_allowed(self):
        report = self.observe_later(NOW + timedelta(hours=24))
        value = self.compare(second=report)
        self.assertEqual(value["observed_interval_seconds"], 86400)

    def test_23h_59m_interval_refused(self):
        report = self.observe_later(
            NOW + timedelta(hours=23, minutes=59))
        with self.assertRaises(AnchorRecheckError):
            self.compare(second=report)

    def test_reverse_order_refused(self):
        with self.assertRaises(AnchorRecheckError):
            self.compare(first=self.second, second=self.first)

    def test_identical_replayed_aws_request_ids_rejected(self):
        duplicated = observe_anchor_governance(
            FakeBucketS3(self.base.fx.binding),
            FakeSts(self.base.fx.binding["expected_bucket_owner"]),
            observed_at=SECOND, **self.common,
        )
        with self.assertRaises(AnchorRecheckError):
            self.compare(second=duplicated)

    def test_single_reused_sts_request_id_rejected(self):
        sts = FakeSts(self.base.fx.binding["expected_bucket_owner"])
        report = observe_anchor_governance(
            DistinctS3(self.base.fx.binding), sts,
            observed_at=SECOND, **self.common,
        )
        with self.assertRaises(AnchorRecheckError):
            self.compare(second=report)

    def test_different_object_version_is_refused_even_if_hmac_valid(self):
        different = deepcopy(self.base.fx.binding)
        different["version_id"] = "another-s3-object-version"
        distinct_s3 = DistinctS3(different)
        common = dict(self.common)
        # A true re-scope needs a different archive binding and signed
        # receipt, which cannot be silently accepted by one comparison.
        common["binding"] = different
        with self.assertRaises(AnchorRecheckError):
            compare_anchor_governance(
                self.first, self.second, **common,
            )
        self.assertEqual(distinct_s3.calls, [])

    def test_retention_extension_is_allowed(self):
        later = DistinctS3(self.base.fx.binding)
        later.retention = datetime(2032, 1, 1, tzinfo=timezone.utc)
        future = observe_anchor_governance(
            later, DistinctSts(self.base.fx.binding["expected_bucket_owner"]),
            observed_at=SECOND, **self.common,
        )
        result = self.compare(second=future)
        self.assertEqual(
            result["second_retention_until_utc"], "2032-01-01T00:00:00Z"
        )
        self.assertTrue(result["nondecreasing_retention_observed"])

    def test_shortened_compliance_retention_is_refused(self):
        later = DistinctS3(self.base.fx.binding)
        later.retention = datetime(2030, 6, 1, tzinfo=timezone.utc)
        report = observe_anchor_governance(
            later, DistinctSts(self.base.fx.binding["expected_bucket_owner"]),
            observed_at=SECOND, **self.common,
        )
        with self.assertRaises(AnchorRecheckError):
            self.compare(second=report)

    def test_broken_bucket_policy_in_second_read_fails_before_compare(self):
        broken = DistinctS3(self.base.fx.binding)
        broken.controls["get_bucket_policy_status"][
            "PolicyStatus"]["IsPublic"] = True
        with self.assertRaises(ValueError):
            observe_anchor_governance(
                broken, DistinctSts(
                    self.base.fx.binding["expected_bucket_owner"]),
                observed_at=SECOND, **self.common,
            )

    def test_tampered_first_or_second_hmac_is_rejected(self):
        for index in (0, 1):
            one, two = deepcopy(self.first), deepcopy(self.second)
            (one if index == 0 else two)[
                "observation_hmac_sha256"] = "f" * 64
            with self.subTest(index=index), self.assertRaises(AnchorRecheckError):
                self.compare(first=one, second=two)

    def test_comparison_hmac_and_extra_trust_flags_refused(self):
        original = self.compare()
        for key, bad in (
            ("comparison_hmac_sha256", "0" * 64),
            ("aws_real_time_continuity_proven", True),
            ("external_timestamp_verified", True),
            ("full_iam_scp_access_points_policy_verified", True),
            ("source_rights_verified", True),
            ("graph_snapshot_verified", True),
            ("research_release_status", "PASS"),
            ("observed_interval_seconds", 3600),
        ):
            with self.subTest(key=key):
                changed = deepcopy(original)
                changed[key] = bad
                with self.assertRaises(AnchorRecheckError):
                    self.verify(changed)
        changed = deepcopy(original)
        changed["raw_bucket_name"] = "private-secret"
        with self.assertRaises(AnchorRecheckError):
            self.verify(changed)

    def test_wrong_local_key_or_signer_policy_fails_offline(self):
        with self.assertRaises(AnchorRecheckError):
            compare_anchor_governance(
                self.first, self.second, **{**self.common, "local_key": "short"},
            )
        pin = deepcopy(self.common["pin_policy"])
        pin["signers"][0]["scope_id"] = "audit-scope:" + "0" * 64
        with self.assertRaises(AnchorRecheckError):
            compare_anchor_governance(
                self.first, self.second, **{**self.common, "pin_policy": pin},
            )

    def test_cli_compare_and_verify_are_offline_and_private(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            signed = root / "signed.json"
            pin = root / "pin.json"
            binding = root / "binding.json"
            first = root / "first.json"
            second = root / "second.json"
            token_path = root / "local-token"
            output = root / "comparison.json"
            signed.write_bytes(self.base.fx.raw)
            pin.write_text(json.dumps(self.base.fx.policy), encoding="utf-8")
            binding.write_text(json.dumps(self.base.fx.binding), encoding="utf-8")
            bootstrap_token(token_path)
            secret = load_token(token_path)
            common = {**self.common, "local_key": secret}
            one = observe_anchor_governance(
                FakeBucketS3(self.base.fx.binding),
                FakeSts(self.base.fx.binding["expected_bucket_owner"]),
                observed_at=NOW, **common)
            two = observe_anchor_governance(
                DistinctS3(self.base.fx.binding),
                DistinctSts(self.base.fx.binding["expected_bucket_owner"]),
                observed_at=SECOND, **common)
            first.write_text(json.dumps(one), encoding="utf-8")
            second.write_text(json.dumps(two), encoding="utf-8")
            args = [
                "--signed-anchor", str(signed),
                "--trusted-policy", str(pin),
                "--archive-binding", str(binding),
                "--local-key-file", str(token_path),
                "--first-observation", str(first),
                "--second-observation", str(second),
            ]
            with patch("scripts.audit_anchor_governance_v0915.live_clients") as aws:
                self.assertEqual(archive_cli([
                    "compare", *args, "--output", str(output)]), 0)
                self.assertTrue(output.is_file())
                self.assertEqual(archive_cli([
                    "verify-comparison", *args,
                    "--comparison", str(output)]), 0)
                self.assertEqual(archive_cli([
                    "compare", *args, "--output", str(output)]), 1)
                aws.assert_not_called()

    def test_one_observation_or_missing_previous_comparison_refused(self):
        with tempfile.TemporaryDirectory() as root:
            token = Path(root) / "token"
            bootstrap_token(token)
            result = archive_cli([
                "compare", "--signed-anchor", str(Path(root) / "missing"),
                "--trusted-policy", str(Path(root) / "missing"),
                "--archive-binding", str(Path(root) / "missing"),
                "--local-key-file", str(token),
            ])
            self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
