#!/usr/bin/env python3
"""CI-only: source membership witness against signed real isolated Neo4j.

No persisted raw source text, production network call or scholarly approval.
"""
from __future__ import annotations

import os
import base64
from datetime import datetime, timezone
from pathlib import Path
import secrets
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from ingestion.sefaria_links import file_sha256
from research_graph.ontology import stable_id
from scripts.capture_smoke import LocalFastAPIOpener
from scripts.search_capture import SignedLoopbackClient, collect, digest, encode
from scripts.search_provenance import observe_provenance
from scripts.search_revision import observe_projection
from scripts.source_receipts import MODES, issue_receipt
from scripts.source_membership import issue_witness, verify_witness
from scripts.external_archive_attestation import DOMAIN, verify_attestation
from scripts.live_s3_version_verify import observe_s3_version, verify_observation
from services.research_api.app import create_app
from services.research_api.signature import CLIENT_ID, sign_request

FIXTURE = ROOT / "tests/fixtures/sefaria_links_synthetic.csv"
URI = "https://storage.googleapis.com/sefaria-export/links/links0.csv"


def main() -> int:
    if os.getenv("CI") != "true":
        print("[BLOCKED] Source membership smoke is CI-only.")
        return 2
    os.environ["DVIROS_REQUIRE_SIGNED_CALLS"] = "1"
    ident = stable_id("source", "sefaria", URI, file_sha256(FIXTURE))
    catalog = {
        "schema_version": "0.8.8", "dataset_kind": "synthetic",
        "questions": [{
            "id": "q-ci-source-member", "kind": "works",
            "query": "synthetic", "language": "",
        }],
    }
    with TestClient(create_app()) as api:
        client = SignedLoopbackClient(
            "http://127.0.0.1:8000", opener=LocalFastAPIOpener(api))
        target = "/v1/sources/" + ident
        now, nonce = int(time.time()), secrets.token_hex(16)
        response = api.get(target, headers={
            "Authorization": "Bearer " + client.bearer,
            "X-DvirOS-Client": CLIENT_ID,
            "X-DvirOS-Timestamp": str(now),
            "X-DvirOS-Nonce": nonce,
            "X-DvirOS-Signature": sign_request(
                client.key, "GET", target, now, nonce),
        })
        if response.status_code != 200:
            raise RuntimeError("Signed synthetic source lookup failed.")
        record = response.json()
        _, capture = collect(
            catalog, client.fetch, mode="scan",
            catalog_sha=digest(encode(catalog)), key=client.key,
            revision_probe=lambda: observe_projection(
                catalog, client.fetch, mode="scan"),
            provenance_probe=lambda: observe_provenance(client.fetch),
        )
        receipt = issue_receipt(
            record, FIXTURE, mode=MODES[0], key=client.key,
            capture_manifest=capture)
        witness = issue_witness(
            record, receipt, FIXTURE, capture, client.fetch, key=client.key)
        verify_witness(
            witness, record, receipt, FIXTURE, capture, key=client.key)
        # Ephemeral PRIVATE KEY: generated inside isolated CI, never saved,
        # not an independent real-world archival provider or a release.
        signer = Ed25519PrivateKey.generate()
        policy = {
            "schema_version": "0.8.14",
            "trust_status": "OPERATOR_PINNED_IDENTITY_NOT_ATTESTED",
            "signers": [{
                "signer_id": "ci_archival_fixture",
                "role": "archive_operator",
                "archive_namespace": "ci_synthetic_archive",
                "ed25519_public_key_b64": base64.b64encode(
                    signer.public_key().public_bytes(
                        Encoding.Raw, PublicFormat.Raw)).decode("ascii"),
            }],
        }
        archive_report = {
            "schema_version": "0.8.14",
            "provider": "s3_object_lock",
            "bucket": "ci-synthetic-archive",
            "object_key": "fixture/links0.csv",
            "version_id": "synthetic-ci-object-version",
            "content_sha256": receipt["observed_raw_file_sha256"],
            "content_length": receipt["observed_file_size_bytes"],
            "object_lock_mode": "COMPLIANCE",
            "retain_until_utc": "2028-01-01T00:00:00Z",
            "evidence_origin": "operator_supplied_unverified",
        }
        statement = {
            "schema_version": "0.8.14",
            "purpose": "archival_operator_attests_report_claim",
            "signer_id": "ci_archival_fixture",
            "archive_namespace": "ci_synthetic_archive",
            "source_record_id": ident,
            "source_receipt_sha256": digest(encode(receipt)),
            "source_witness_sha256": digest(encode(witness)),
            "capture_manifest_sha256": digest(encode(capture)),
            "archive_report_sha256": digest(encode(archive_report)),
            "issued_at_utc": "2026-11-11T12:00:00Z",
            "provider_identity_independently_verified": False,
            "source_rights_verified": False,
            "research_release_status": "HOLD",
        }
        signed = {
            "statement": statement,
            "signature_b64": base64.b64encode(
                signer.sign(DOMAIN + encode(statement))).decode("ascii"),
        }
        attestation_result = verify_attestation(
            policy, archive_report, signed, source_record=record,
            receipt=receipt, witness=witness, capture=capture,
            source_file=FIXTURE, local_key=client.key)
        if (attestation_result["pinned_key_signature_valid"] is not True or
            attestation_result["external_archive_immutability_verified"] is not False or
            attestation_result["research_release_status"] != "HOLD"):
            raise RuntimeError("Signed synthetic archival claim promoted trust.")
        # A fake SDK object explicitly exercises the LIVE READ validation
        # logic without any credentials or requests to real S3.
        # Do not treat this test as a real archive-retention certification.
        class FakeS3:
            def head_object(self, **params):
                if (params["VersionId"] != archive_report["version_id"] or
                    params["ExpectedBucketOwner"] != "123456789012" or
                    params["ChecksumMode"] != "ENABLED"):
                    raise RuntimeError("Unpinned synthetic S3 HEAD.")
                return {
                    "ResponseMetadata": {
                        "HTTPStatusCode": 200, "RequestId": "CI_SYNTHETIC_HEAD"},
                    "VersionId": archive_report["version_id"],
                    "ContentLength": receipt["observed_file_size_bytes"],
                    "ChecksumSHA256": base64.b64encode(bytes.fromhex(
                        receipt["observed_raw_file_sha256"])).decode("ascii"),
                    "ChecksumType": "FULL_OBJECT",
                    "ObjectLockMode": "COMPLIANCE",
                    "ObjectLockRetainUntilDate": datetime(
                        2028, 1, 1, tzinfo=timezone.utc),
                }

            def get_object_retention(self, **params):
                if (params["VersionId"] != archive_report["version_id"] or
                    params["ExpectedBucketOwner"] != "123456789012"):
                    raise RuntimeError("Unpinned synthetic S3 retention.")
                return {
                    "ResponseMetadata": {
                        "HTTPStatusCode": 200, "RequestId": "CI_SYNTHETIC_LOCK"},
                    "Retention": {
                        "Mode": "COMPLIANCE",
                        "RetainUntilDate": datetime(
                            2028, 1, 1, tzinfo=timezone.utc),
                    },
                }

        s3_evidence = observe_s3_version(
            FakeS3(), policy=policy, report=archive_report,
            statement=signed, record=record, receipt=receipt,
            witness=witness, capture=capture, source_file=FIXTURE,
            local_key=client.key, account="123456789012",
            region="il-central-1",
            observed_at=datetime(2026, 11, 11, 13, tzinfo=timezone.utc))
        verify_observation(
            s3_evidence, policy=policy, report=archive_report,
            statement=signed, record=record, receipt=receipt,
            witness=witness, capture=capture, source_file=FIXTURE,
            local_key=client.key, account="123456789012",
            region="il-central-1")
        if (s3_evidence["external_archive_immutability_end_to_end_verified"] is not False or
            s3_evidence["aws_full_object_sha256_matched"] is not True):
            raise RuntimeError("Synthetic S3 observation falsely upgraded trust.")
        if (witness["source_record_id"] != ident or
            witness["research_release_status"] != "HOLD" or
            witness["independent_provider_signature_verified"] is not False or
            witness["cross_request_snapshot_isolation"] is not False):
            raise RuntimeError("Source membership overclaimed independent trust.")
    print("[OK] Signed real Neo4j chain plus mocked S3 HEAD/retention + "
          "Ed25519; NO live AWS used; external immutability unverified; HOLD.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
