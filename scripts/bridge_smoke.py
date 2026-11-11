#!/usr/bin/env python3
"""Ephemeral CI: real Neo4j backend with signed DvirOS contract calls."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from fastapi.testclient import TestClient
from services.research_api.app import create_app
from services.research_api.config import load_token
from services.research_api.signature import (
    CLIENT_ID, bootstrap_signature_key, sign_request,
)


def signed(target:str,nonce:str):
    timestamp=int(time.time())
    from services.research_api.signature import signature_key_path
    return {
        "Authorization":"Bearer "+load_token(),
        "X-DvirOS-Client":CLIENT_ID,
        "X-DvirOS-Timestamp":str(timestamp),
        "X-DvirOS-Nonce":nonce,
        "X-DvirOS-Signature":sign_request(
            load_token(signature_key_path()),"GET",target,timestamp,nonce
        ),
    }


def main()->int:
    if os.getenv("CI")!="true":
        print("[BLOCKED] Signed service smoke requires disposable CI Neo4j.")
        return 2
    bootstrap_signature_key()
    os.environ["DVIROS_REQUIRE_SIGNED_CALLS"]="1"
    with TestClient(create_app()) as client:
        target="/v1/integration/contract"
        req=signed(target,"1"*32)
        response=client.get(target,headers=req)
        if response.status_code!=200:
            raise RuntimeError(f"Signed contract failed HTTP {response.status_code}")
        contract=response.json()
        if (contract.get("contract_version")!="1.0"
            or contract.get("service_id")!="dviros.neo4j.philosophy"
            or contract.get("writes_allowed") is not False):
            raise RuntimeError("Incompatible DvirOS contract.")
        if client.get(target,headers=req).status_code!=403:
            raise RuntimeError("Replay protection failed.")
        if client.get("/v1/data/status",
                      headers=signed("/v1/data/status","2"*32)).status_code!=200:
            raise RuntimeError("Signed live DB metadata read failed.")
        # v0.8.2: test the actual allowlisted read operation against real
        # ephemeral Neo4j, using the same signed service identity.
        metadata_target="/v1/search/metadata?kind=works&limit=5"
        metadata=client.get(metadata_target,
                            headers=signed(metadata_target,"3"*32))
        if metadata.status_code!=200:
            raise RuntimeError(f"Signed metadata search returned HTTP {metadata.status_code}")
        payload=metadata.json()
        if (payload.get("schema_version")!="0.8.2"
            or payload.get("full_text_indexed") is not False
            or payload.get("text_available") is not False
            or payload.get("candidate_window_limit")!=50
            or any(hit.get("review_status")!="unreviewed"
                   or hit.get("text_available") is not False
                   or "excerpt" in hit for hit in payload.get("items",[]))):
            raise RuntimeError("Signed metadata search safety contract failed.")
        # Unrecognized facets must not be ignored as though applied.
        unsupported=metadata_target+"&author=unreviewed"
        if client.get(unsupported,
                      headers=signed(unsupported,"4"*32)).status_code!=422:
            raise RuntimeError("Unsupported research facet was silently ignored.")
        indexed="/v1/search/metadata/indexed?kind=works&query=synthetic&limit=5"
        indexed_response=client.get(indexed,headers=signed(indexed,"5"*32))
        if indexed_response.status_code!=200:
            raise RuntimeError(f"Signed indexed search returned HTTP {indexed_response.status_code}")
        result=indexed_response.json()
        if (result.get("schema_version")!="0.8.3"
            or result.get("index_version")!="search_key_v1"
            or not result.get("index_coverage",{}).get("complete")
            or result.get("full_text_indexed") is not False
            or result.get("alias_matching_available") is not False
            or any(hit.get("review_status")!="unreviewed"
                   or "excerpt" in hit for hit in result.get("items",[]))):
            raise RuntimeError("Indexed metadata provenance/rights contract is invalid.")
        capability_target="/v1/search/metadata/indexed/capability?kind=works"
        capability=client.get(capability_target,
                              headers=signed(capability_target,"6"*32))
        if capability.status_code!=200:
            raise RuntimeError(f"Signed index capability returned HTTP {capability.status_code}")
        cap=capability.json()
        if (cap.get("schema_version")!="0.8.5"
            or cap.get("index_status")!="ready"
            or cap.get("indexed_prefix_ready") is not True
            or cap.get("index_coverage",{}).get("complete") is not True
            or cap.get("text_available") is not False
            or cap.get("source_trail_verified") is not False
            or "items" in cap):
            raise RuntimeError("Signed capability contract mismatch.")
        if client.get(capability_target).status_code!=401:
            raise RuntimeError("Capability bypassed bearer authentication.")
        if client.get("/v1/works").status_code!=401:
            raise RuntimeError("Unauthenticated request was not blocked.")
    print("[OK] Signed DvirOS service, real Neo4j metadata search, rights and replay guards.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
