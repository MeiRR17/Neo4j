"""Bounded local Query API v2 adapter for an immutable read operation registry.

Neo4j Community does not provide full enterprise RBAC. Thus read-only here
is enforced by the app's closed query registry, not by an invented DB role.
The Query API accessMode 'Read' is routing, NOT an authorization boundary.
Production requires a read-only DB principal / DB isolation in a supported
deployment, plus service-to-service auth and TLS (v0.14).
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from urllib import error, request

from scripts.bootstrap import DEFAULT_SECRET_PATH, load_auth
from scripts.smoke import NoRedirect, query_url
from services.research_api.queries import READ_OPERATIONS

MAX_RESULT_BYTES = 2_000_000
MAX_EXECUTION_SECONDS = 5


class DatabaseUnavailable(RuntimeError):
    """Sanitized DB error; caller must not disclose Neo4j internal messages."""


class ReadOnlyQueryClient:
    """Read-only query *registry*, not an arbitrary Cypher executor."""

    def __init__(self, base_url: str = "http://127.0.0.1:7474",
                 secret_path: Path = DEFAULT_SECRET_PATH):
        self.endpoint = query_url(base_url)
        self.secret_path = Path(secret_path)
        self.opener = request.build_opener(request.ProxyHandler({}), NoRedirect())

    def query(self, operation: str, params: dict | None = None) -> list[dict]:
        if operation not in READ_OPERATIONS:
            raise ValueError("Unknown read operation; arbitrary Cypher is forbidden.")
        params = dict(params or {})
        # Defend against malformed caller input. All statements live in the code.
        if len(json.dumps(params, ensure_ascii=False)) > 5000:
            raise ValueError("Query parameters exceed budget.")
        try:
            username, password = load_auth(self.secret_path)
            auth = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
            payload = json.dumps({
                "statement": READ_OPERATIONS[operation],
                "parameters": params, "accessMode": "Read",
                "maxExecutionTime": MAX_EXECUTION_SECONDS,
            }).encode("utf-8")
            req = request.Request(
                self.endpoint, data=payload, method="POST",
                headers={
                    "Authorization": "Basic " + auth,
                    "Content-Type": "application/json",
                    "Accept": "application/json", "Accept-Encoding": "identity",
                },
            )
            with self.opener.open(req, timeout=8) as res:
                if res.status != 202:
                    raise DatabaseUnavailable("Graph storage unavailable.")
                raw = res.read(MAX_RESULT_BYTES + 1)
                if len(raw) > MAX_RESULT_BYTES:
                    raise DatabaseUnavailable("Graph result exceeded read budget.")
                body = json.loads(raw.decode("utf-8"))
        except (ValueError, OSError, error.URLError, json.JSONDecodeError) as exc:
            if isinstance(exc, ValueError) and "Unknown read operation" in str(exc):
                raise
            raise DatabaseUnavailable("Graph storage unavailable.") from None
        if not isinstance(body, dict) or body.get("errors"):
            raise DatabaseUnavailable("Graph query failed.")
        if body.get("queryType") not in (None, "r"):
            raise DatabaseUnavailable("Non-read graph result refused.")
        data = body.get("data")
        if not isinstance(data, dict):
            raise DatabaseUnavailable("Graph data format unexpected.")
        fields = data.get("fields")
        values = data.get("values")
        if not isinstance(fields, list) or not all(isinstance(f, str) for f in fields) or not isinstance(values, list):
            raise DatabaseUnavailable("Graph response fields missing.")
        if len(values) > 51:
            raise DatabaseUnavailable("Graph result row cap exceeded.")
        result = []
        for row in values:
            if not isinstance(row, list) or len(row) != len(fields):
                raise DatabaseUnavailable("Graph response row shape invalid.")
            result.append(dict(zip(fields, row)))
        return result
