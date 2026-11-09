#!/usr/bin/env python3
"""CI-only targeted persistence check: marker survives an actual restart.

Runs exclusively against a local throwaway Docker Compose instance.
Creates a temporary test label, verifies after restart, then removes it.
Never run against research data or production.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess
import time
from urllib import error, request
from uuid import uuid4

from bootstrap import DEFAULT_SECRET_PATH, load_auth
from smoke import NoRedirect, query_url, run as authenticated_smoke


def execute(statement: str, marker_id: str) -> list:
    """Execute one fixed, parameterized test statement on loopback only."""
    _, password = load_auth(DEFAULT_SECRET_PATH)
    raw = base64.b64encode(f"neo4j:{password}".encode("utf-8")).decode("ascii")
    req = request.Request(
        query_url("http://127.0.0.1:7474"),
        method="POST",
        data=json.dumps({
            "statement": statement,
            "parameters": {"id": marker_id},
        }).encode("utf-8"),
        headers={"Authorization": "Basic " + raw, "Content-Type": "application/json"},
    )
    opener = request.build_opener(request.ProxyHandler({}), NoRedirect())
    with opener.open(req, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
        if response.status != 202 or payload.get("errors"):
            raise RuntimeError("Neo4j Query API rejected persistence probe.")
        return payload.get("data", {}).get("values", [])


def wait_ready(seconds: int = 120) -> None:
    deadline = time.monotonic() + seconds
    while True:
        try:
            authenticated_smoke("http://127.0.0.1:7474", DEFAULT_SECRET_PATH, 0)
            return
        except (RuntimeError, OSError, error.URLError):
            if time.monotonic() >= deadline:
                raise RuntimeError("Neo4j did not regain authenticated readiness.")
            time.sleep(2)


def main() -> int:
    marker_id = uuid4().hex
    create = "MERGE (m:FoundationPersistenceProbe {id: $id}) RETURN m.id AS id"
    read = "MATCH (m:FoundationPersistenceProbe {id: $id}) RETURN m.id AS id"
    delete = "MATCH (m:FoundationPersistenceProbe {id: $id}) DETACH DELETE m"
    try:
        wait_ready()
        if execute(create, marker_id) != [[marker_id]]:
            raise RuntimeError("Could not create test marker.")
        subprocess.run(["docker", "compose", "restart", "neo4j"], check=True)
        wait_ready()
        if execute(read, marker_id) != [[marker_id]]:
            raise RuntimeError("Test marker was not persisted across restart.")
        execute(delete, marker_id)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"[FAIL] Neo4j restart persistence: {exc}")
        # CI environment is isolated and discarded after the run.
        return 1
    print("[OK] Authenticated read/write, persistence across restart and test cleanup.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
