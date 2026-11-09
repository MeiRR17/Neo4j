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
        if client.get("/v1/works").status_code!=401:
            raise RuntimeError("Unauthenticated request was not blocked.")
    print("[OK] DvirOS v1 signed contract, replay rejection and real Neo4j read.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
