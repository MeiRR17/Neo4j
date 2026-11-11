#!/usr/bin/env python3
"""Isolated CI: check a locally retained synthetic CSV against real SourceRecord.

No source bytes or version metadata are printed. No network or graph writes.
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
from scripts.source_receipts import (
    MODES, issue_receipt, verify_receipt,
)
from services.research_api.app import create_app
from services.research_api.config import api_token_path, load_token
from services.research_api.signature import (
    CLIENT_ID, sign_request, signature_key_path,
)

FIXTURE = ROOT / "tests/fixtures/sefaria_links_synthetic.csv"
URI = "https://storage.googleapis.com/sefaria-export/links/links0.csv"


def main() -> int:
    if os.getenv("CI") != "true":
        print("[BLOCKED] Receipt smoke requires isolated CI.")
        return 2
    os.environ["DVIROS_REQUIRE_SIGNED_CALLS"] = "1"
    source_sha = file_sha256(FIXTURE)
    source_id = stable_id("source", "sefaria", URI, source_sha)
    target = "/v1/sources/" + source_id
    bearer = load_token(api_token_path())
    key = load_token(signature_key_path())
    now = int(time.time())
    nonce = secrets.token_hex(16)
    headers = {
        "Authorization": "Bearer " + bearer,
        "X-DvirOS-Client": CLIENT_ID,
        "X-DvirOS-Timestamp": str(now),
        "X-DvirOS-Nonce": nonce,
        "X-DvirOS-Signature": sign_request(
            key, "GET", target, now, nonce),
    }
    with TestClient(create_app()) as api:
        unauthorized = api.get(target)
        if unauthorized.status_code != 401:
            raise RuntimeError("SourceRecord access was not denied anonymously.")
        found = api.get(target, headers=headers)
        if found.status_code != 200:
            raise RuntimeError("Signed isolated CI SourceRecord not available.")
        record = found.json()
    receipt = issue_receipt(record, FIXTURE, mode=MODES[0], key=key)
    verify_receipt(receipt, record, FIXTURE, key=key)
    if (receipt["research_release_status"] != "HOLD" or
        receipt["source_redistribution_rights_verified"] is not False or
        receipt["original_provider_response_authenticated"] is not False):
        raise RuntimeError("Source receipt improperly upgraded scholarly status.")
    print("[OK] Signed real Neo4j SourceRecord matches retained synthetic CSV; HOLD.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
