#!/usr/bin/env python3
"""Ephemeral CI: signed search capture end-to-end over real synthetic Neo4j.

The HTTP layer is FastAPI TestClient in the current process; database reads
are against the isolated real Neo4j container, never a production service.
No captured source metadata, IDs, titles, secrets or query text is printed.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from scripts.search_capture import (
    SignedLoopbackClient, collect, digest, encode, verify,
)
from scripts.search_revision import observe_projection
from scripts.search_provenance import observe_provenance
from services.research_api.app import create_app


class LocalFastAPIResponse:
    """Only the minimal urllib response interface required by our caller."""

    def __init__(self, status: int, body: bytes):
        self.status = status
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return False

    def read(self, max_bytes: int):
        return self.body[:max_bytes]


class LocalFastAPIOpener:
    """Transports a signed urllib GET to the local test API, no Internet."""

    def __init__(self, app_client: TestClient):
        self.client = app_client

    def open(self, req, timeout: int):
        url = urlsplit(req.full_url)
        if (url.scheme != "http" or url.netloc != "127.0.0.1:8000"
                or req.get_method() != "GET" or timeout != 8):
            raise RuntimeError("Capture transport left the CI-only local boundary.")
        target = url.path + ("?" + url.query if url.query else "")
        response = self.client.get(target, headers=dict(req.header_items()),
                                   follow_redirects=False)
        return LocalFastAPIResponse(response.status_code, response.content)


def main() -> int:
    if os.environ.get("CI") != "true":
        print("[BLOCKED] Live signed capture smoke is isolated CI only.")
        return 2
    os.environ["DVIROS_REQUIRE_SIGNED_CALLS"] = "1"
    catalog = {
        "schema_version": "0.8.8",
        "dataset_kind": "synthetic",
        "questions": [
            {"id": "q-ci-synthetic-001", "kind": "works",
             "query": "synthetic", "language": ""}
        ],
    }
    catalog_sha = digest(encode(catalog))
    with TestClient(create_app()) as api:
        # Without the local service identity even public metadata is blocked.
        denied = api.get("/v1/search/metadata?kind=works&query=synthetic&limit=20")
        if denied.status_code != 401:
            raise RuntimeError("Unsigned Research API access unexpectedly allowed.")
        caller = SignedLoopbackClient(
            "http://127.0.0.1:8000", opener=LocalFastAPIOpener(api))
        for mode in ("scan", "indexed"):
            snapshots, manifest = collect(
                catalog, caller.fetch, mode=mode,
                catalog_sha=catalog_sha, key=caller.key,
                revision_probe=lambda: observe_projection(
                    catalog, caller.fetch, mode=mode),
                provenance_probe=lambda: observe_provenance(caller.fetch))
            if manifest["schema_version"] != "0.8.11" or (
                manifest["revision_observation"][
                    "corpus_immutable_revision_verified"] is not False
            ) or (manifest["provenance_observation"][
                "source_rights_verified"] is not False):
                raise RuntimeError("Revision observation was not bound safely.")
            count = verify(
                catalog, snapshots, manifest, catalog_sha=catalog_sha,
                snapshot_sha=digest(encode(snapshots)), key=caller.key)
            if count < 1 or count > 12 or manifest["release_status"] != "HOLD":
                raise RuntimeError("Signed capture provenance/release guard failed.")
            if manifest["source_rights_verified"] is not False or (
                manifest["independent_human_review_verified"] is not False
            ):
                raise RuntimeError("Capture incorrectly promoted research status.")
    print("[OK] Signed real Neo4j capture/verify for scan+indexed; synthetic only; HOLD.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
