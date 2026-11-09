#!/usr/bin/env python3
"""Run local-only development Research API; no public interface binding."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.research_api.config import load_token

if __name__ == "__main__":
    from scripts.bootstrap import DEFAULT_SECRET_PATH, load_auth
    from scripts.migrate import LocalQueryClient, load_migrations, applied_checksum
    from services.research_api.signature import signature_key_path
    from services.research_api.config import load_token
    import os
    import uvicorn

    try:
        load_token()
        # The CLI runner always requires signed DvirOS backend identity.
        # Unsigned local TestClient harness is limited to explicit test use.
        os.environ["DVIROS_REQUIRE_SIGNED_CALLS"] = "1"
        load_token(signature_key_path())
        load_auth(DEFAULT_SECRET_PATH)
        client = LocalQueryClient("http://127.0.0.1:7474", DEFAULT_SECRET_PATH)
        for migration in load_migrations():
            if applied_checksum(client, migration.id) != migration.checksum:
                raise RuntimeError("Graph migrations not applied or checksum drift.")
    except (ValueError, OSError, RuntimeError) as exc:
        print("[BLOCKED] API startup prerequisites: local token + Neo4j + schema required.")
        raise SystemExit(1)
    uvicorn.run(
        "services.research_api.app:app",
        host="127.0.0.1", port=8765,
        access_log=False, log_level="warning",
    )
