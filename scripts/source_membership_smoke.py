#!/usr/bin/env python3
"""CI-only: source membership witness against signed real isolated Neo4j.

No persisted raw source text, production network call or scholarly approval.
"""
from __future__ import annotations

import os
from pathlib import Path
import secrets
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from ingestion.sefaria_links import file_sha256
from research_graph.ontology import stable_id
from scripts.capture_smoke import LocalFastAPIOpener
from scripts.search_capture import SignedLoopbackClient, collect, digest, encode
from scripts.search_provenance import observe_provenance
from scripts.search_revision import observe_projection
from scripts.source_receipts import MODES, issue_receipt
from scripts.source_membership import issue_witness, verify_witness
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
        if (witness["source_record_id"] != ident or
            witness["research_release_status"] != "HOLD" or
            witness["independent_provider_signature_verified"] is not False or
            witness["cross_request_snapshot_isolation"] is not False):
            raise RuntimeError("Source membership overclaimed independent trust.")
    print("[OK] Captured signed source membership in isolated CI graph; "
          "external verification pending; HOLD.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
