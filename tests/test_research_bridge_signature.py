"""DvirOS signed-service identity: HMAC parity, expiry, replay and auth."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from services.research_api.app import create_app
from services.research_api.config import bootstrap_token, load_token
from services.research_api.signature import (
    CLIENT_ID, ReplayGuard, sign_request, verify_signed_request,
)


class FakeStore:
    def query(self, name, params=None):
        if name == "works":
            return []
        if name == "data_status":
            return [{
                "works": 0, "passages": 0,
                "evidence_records": 0, "editions": 0,
            }]
        if name == "ready":
            from scripts.migrate import load_migrations
            return [{"id":m.id,"checksum":m.checksum} for m in load_migrations()]
        return []


class SignatureContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.api_token = Path(self.tmp.name) / "api-token"
        self.hmac_key = Path(self.tmp.name) / "shared-hmac"
        bootstrap_token(self.api_token)
        bootstrap_token(self.hmac_key)
        self.client = TestClient(create_app(
            backend=FakeStore(), token_path=self.api_token,
            signature_path=self.hmac_key,
        ))
        self.bearer = "Bearer " + load_token(self.api_token)

    def headers(self, *, target="/v1/integration/contract",
                nonce="0123456789abcdef0123456789abcdef", timestamp=None):
        timestamp = int(time.time()) if timestamp is None else timestamp
        return {
            "Authorization": self.bearer,
            "X-DvirOS-Client": CLIENT_ID,
            "X-DvirOS-Timestamp": str(timestamp),
            "X-DvirOS-Nonce": nonce,
            "X-DvirOS-Signature": sign_request(
                load_token(self.hmac_key), "GET", target, timestamp, nonce
            ),
        }

    def test_golden_hmac_matches_node_dviros_bridge(self):
        self.assertEqual(
            sign_request("S" * 48, "GET",
                         "/v1/works?limit=2&query=Guide+for+the+Perplexed",
                         1794220000, "0123456789abcdef0123456789abcdef"),
            "b32409ea6428811e59bec4a7e9f21c17dd2cf22d2852c0eeef0423c74ee87816",
        )

    def test_unsigned_legacy_mode_remains_test_compatible(self):
        with patch.dict(os.environ, {"DVIROS_REQUIRE_SIGNED_CALLS":"0"}):
            res = self.client.get("/v1/integration/contract",
                                  headers={"Authorization":self.bearer})
            self.assertEqual(res.status_code,200)
            self.assertEqual(res.json()["contract_version"],"1.0")
            self.assertEqual(res.json()["writes_allowed"],False)

    def test_signed_mode_blocks_missing_and_wrong_identity(self):
        with patch.dict(os.environ, {"DVIROS_REQUIRE_SIGNED_CALLS":"1"}):
            self.assertEqual(self.client.get("/v1/works",
                             headers={"Authorization":self.bearer}).status_code,403)
            self.assertEqual(self.client.get("/v1/works").status_code,401)
            bad=self.headers(target="/v1/works")
            bad["X-DvirOS-Signature"]="0"*64
            self.assertEqual(self.client.get("/v1/works",headers=bad).status_code,403)
            good=self.headers(target="/v1/works")
            self.assertEqual(self.client.get("/v1/works",headers=good).status_code,200)

    def test_replay_mutated_path_and_stale_request_rejected(self):
        with patch.dict(os.environ, {"DVIROS_REQUIRE_SIGNED_CALLS":"1"}):
            signed=self.headers()
            r=self.client.get("/v1/integration/contract",headers=signed)
            self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(self.client.get("/v1/integration/contract",
                                              headers=signed).status_code,403)
            self.assertEqual(self.client.get("/v1/works",
                                              headers=self.headers()).status_code,403)
            stale=self.headers(timestamp=int(time.time())-120)
            self.assertEqual(self.client.get("/v1/integration/contract",headers=stale).status_code,403)

    def test_signed_query_includes_canonical_query_string(self):
        with patch.dict(os.environ, {"DVIROS_REQUIRE_SIGNED_CALLS":"1"}):
            target="/v1/works?limit=2&query=Guide+for+the+Perplexed"
            signed=self.headers(target=target,nonce="b"*32)
            self.assertEqual(self.client.get(target,headers=signed).status_code,200)
            self.assertEqual(self.client.get(target+"&language=en",
                                              headers=self.headers(target=target,nonce="c"*32)).status_code,403)

    def test_invalid_secret_settings_fail_closed(self):
        with patch.dict(os.environ, {"DVIROS_REQUIRE_SIGNED_CALLS":"bad"}):
            self.assertEqual(self.client.get("/v1/works",headers={"Authorization":self.bearer}).status_code,503)
        with patch.dict(os.environ, {"DVIROS_REQUIRE_SIGNED_CALLS":"1"}):
            headers=self.headers(target="/v1/integration/contract")
            self.hmac_key.unlink()
            self.assertEqual(self.client.get("/v1/integration/contract",
                                  headers=headers).status_code,503)

    def test_replay_cache_is_bounded(self):
        cache=ReplayGuard()
        self.assertTrue(cache.consume("a"*32,1000))
        self.assertFalse(cache.consume("a"*32,1000))
        self.assertTrue(cache.consume("a"*32,2000))


if __name__=="__main__":
    unittest.main()
