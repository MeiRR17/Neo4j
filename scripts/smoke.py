#!/usr/bin/env python3
"""Local-only authenticated Neo4j Query API smoke check (no dependencies)."""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import time
from urllib import error, parse, request

from bootstrap import DEFAULT_SECRET_PATH, load_auth


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Refusing HTTP redirect when checking local database credentials.")


def query_url(base_url: str) -> str:
    """Reject hosts, ports in URLs with userinfo, and remote destinations."""
    parsed = parse.urlsplit(base_url)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
            or parsed.port != 7474):
        raise ValueError("Smoke check is restricted to http://127.0.0.1:7474.")
    return "http://127.0.0.1:7474/db/neo4j/query/v2"


def post_query(url: str, auth: tuple[str, str] | None = None) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if auth is not None:
        username, password = auth
        raw = f"{username}:{password}".encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
    payload = json.dumps({"statement": "RETURN 1 AS value"}).encode("utf-8")
    req = request.Request(url, data=payload, method="POST", headers=headers)
    opener = request.build_opener(request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(req, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        # Do not print the potentially credential-sensitive response body.
        return exc.code, {}


def run(url: str, secret_path: Path, timeout: float) -> bool:
    endpoint = query_url(url)
    credentials = load_auth(secret_path)
    deadline = time.monotonic() + timeout
    while True:
        try:
            status, _ = post_query(endpoint)
            if status != 401:
                raise RuntimeError(f"Unauthenticated query returned HTTP {status}, expected 401.")
            status, body = post_query(endpoint, credentials)
            data = body.get("data", {})
            if status != 202 or data.get("fields") != ["value"] or data.get("values") != [[1]]:
                raise RuntimeError(f"Authenticated query failed: HTTP {status} or unexpected result.")
            return True
        except (OSError, error.URLError) as exc:
            if time.monotonic() >= deadline:
                raise RuntimeError("Neo4j did not become ready before timeout.") from exc
            time.sleep(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:7474")
    parser.add_argument("--secret", type=Path, default=DEFAULT_SECRET_PATH)
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args()
    try:
        if args.timeout < 0:
            raise ValueError("Timeout cannot be negative.")
        run(args.url, args.secret, args.timeout)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"[FAIL] Neo4j smoke: {exc}")
        return 1
    print("[OK] Auth is required, and authenticated read-only Cypher query returned 1.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
