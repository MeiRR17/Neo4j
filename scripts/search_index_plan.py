#!/usr/bin/env python3
"""Read-only Neo4j plan evidence for fixed indexed metadata queries (v0.8.6).

EXPLAIN never runs a search. PROFILE executes the *fixed read-only* search and
is locked to an explicitly acknowledged disposable CI fixture. Neither mode
prints query results, original titles, credentials or plan Details.
No performance or production index-use claim is inferred from tiny CI data.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import sys
from urllib import error, request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.bootstrap import DEFAULT_SECRET_PATH, load_auth
from scripts.smoke import NoRedirect, query_url
from services.research_api.metadata_search import fold_metadata
from services.research_api.queries import READ_OPERATIONS
from services.research_api.search_index import INDEX_DEFINITIONS

MAX_BODY_BYTES = 256_000
MAX_OPERATORS = 80
MAX_DEPTH = 16
FETCH_LIMIT = 6
RANGE_OPERATORS = frozenset({
    "NodeIndexSeekByRange", "NodeUniqueIndexSeekByRange",
})
SCAN_OPERATORS = frozenset({"NodeByLabelScan", "AllNodesScan"})


class PlanEvidenceError(RuntimeError):
    """Sanitized failure. Never forward a server response or source text."""


def validate_prefix(raw: str) -> str:
    if not isinstance(raw, str) or not 1 <= len(raw) <= 100:
        raise PlanEvidenceError("Prefix must contain 1..100 characters.")
    try:
        value = fold_metadata(raw)
    except (ValueError, TypeError) as exc:
        raise PlanEvidenceError("Invalid synthetic prefix.") from None
    if not value or len(value) > 200:
        raise PlanEvidenceError("Normalized prefix is empty or exceeds bound.")
    return value


def statement_for(kind: str, profile: bool) -> str:
    if kind not in INDEX_DEFINITIONS:
        raise PlanEvidenceError("Unsupported metadata kind.")
    # Cypher is selected only from the checked-in fixed READ_OPERATIONS;
    # the user can never inject an additional statement or property name.
    return ("PROFILE " if profile else "EXPLAIN ") + READ_OPERATIONS["indexed_" + kind]


def inspect_plan_response(body: object, *, kind: str, profile: bool) -> dict:
    """Reduce a Neo4j plan to allowlisted metadata; discard every source row."""
    if kind not in INDEX_DEFINITIONS or not isinstance(body, dict):
        raise PlanEvidenceError("Unexpected plan response.")
    if body.get("errors") or body.get("queryType") not in (None, "r"):
        raise PlanEvidenceError("Query was not a clean read-only plan.")
    data = body.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("fields"), list):
        raise PlanEvidenceError("Missing query data envelope.")
    values = data.get("values")
    if not isinstance(values, list) or len(values) > (FETCH_LIMIT if profile else 0):
        raise PlanEvidenceError("Profile row budget exceeded or EXPLAIN executed.")
    key = "profiledQueryPlan" if profile else "queryPlan"
    if ("queryPlan" in body and profile) or ("profiledQueryPlan" in body and not profile):
        raise PlanEvidenceError("Mixed EXPLAIN/PROFILE response.")
    root = body.get(key)
    if not isinstance(root, dict):
        raise PlanEvidenceError("Missing Cypher plan tree.")

    ops: list[str] = []
    has_range_seek = False
    has_label_scan = False
    hits = 0
    stack = [(root, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > MAX_DEPTH or len(ops) >= MAX_OPERATORS or not isinstance(node, dict):
            raise PlanEvidenceError("Plan tree exceeds safety bounds.")
        operator = node.get("operatorType")
        args = node.get("arguments")
        children = node.get("children")
        if (not isinstance(operator, str) or len(operator) > 100
                or not isinstance(args, dict) or not isinstance(children, list)
                or len(children) > MAX_OPERATORS):
            raise PlanEvidenceError("Malformed Cypher operator.")
        # Neo4j's server suffix (e.g. @neo4j) is not an input selector.
        name = operator.split("@", 1)[0]
        if not name.isascii() or not name.replace("_", "").isalnum():
            raise PlanEvidenceError("Malformed Cypher operator name.")
        ops.append(name)
        details = args.get("Details", "")
        if not isinstance(details, str):
            raise PlanEvidenceError("Malformed index detail.")
        if name in RANGE_OPERATORS and "search_key_v1" in details:
            has_range_seek = True
        if name in SCAN_OPERATORS:
            has_label_scan = True
        if profile:
            db_hits = node.get("dbHits", args.get("DbHits", 0))
            if type(db_hits) is not int or not 0 <= db_hits <= 10_000_000:
                raise PlanEvidenceError("Malformed profile cost counter.")
            hits += db_hits
            if hits > 100_000_000:
                raise PlanEvidenceError("Profile budget exceeded.")
        for child in reversed(children):
            stack.append((child, depth + 1))

    report = {
        "schema_version": "0.8.6",
        "kind": kind,
        "mode": "profile" if profile else "explain",
        "fixed_read_operation": "indexed_" + kind,
        "search_key_range_seek_planned": has_range_seek,
        "node_or_label_scan_planned": has_label_scan,
        "operator_types": ops,
        "operator_count": len(ops),
        "results_exposed": False,
        "representative_performance_proven": False,
        "execution_metrics_available": profile,
    }
    if profile:
        report["returned_rows"] = len(values)
        report["db_hits"] = hits
        # The Query API may omit the timing fields on older Neo4j releases.
        for api_key, report_key in (
            ("resultAvailableAfter", "result_available_after_ms"),
            ("resultConsumedAfter", "result_consumed_after_ms"),
        ):
            value = body.get(api_key)
            if value is not None:
                if type(value) is not int or not 0 <= value <= 120_000:
                    raise PlanEvidenceError("Malformed API timing metric.")
                report[report_key] = value
    return report


class LocalPlanClient:
    """No redirects, no proxy, localhost-only API, bounded bytes/time."""
    def __init__(self, base_url: str, secret_path: Path):
        self.endpoint = query_url(base_url)
        username, password = load_auth(secret_path)
        auth = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        self.headers = {
            "Authorization": "Basic " + auth,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        }
        self.opener = request.build_opener(request.ProxyHandler({}), NoRedirect())

    def query_plan(self, kind: str, prefix: str, *, profile: bool) -> dict:
        statement = statement_for(kind, profile)
        params = {"prefix": prefix, "cursor": "", "language": "",
                  "fetch_limit": FETCH_LIMIT}
        raw = json.dumps({
            "statement": statement, "parameters": params,
            "accessMode": "Read", "maxExecutionTime": 5,
        }, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            self.endpoint, data=raw, method="POST", headers=self.headers,
        )
        try:
            with self.opener.open(req, timeout=8) as response:
                if response.status != 202:
                    raise PlanEvidenceError("Neo4j plan query unavailable.")
                payload = response.read(MAX_BODY_BYTES + 1)
                if len(payload) > MAX_BODY_BYTES:
                    raise PlanEvidenceError("Plan response exceeded byte budget.")
                body = json.loads(payload.decode("utf-8"))
        except (error.URLError, OSError, ValueError, UnicodeError) as exc:
            raise PlanEvidenceError("Neo4j plan request failed.") from None
        return inspect_plan_response(body, kind=kind, profile=profile)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=sorted(INDEX_DEFINITIONS), default="works")
    parser.add_argument("--prefix", default="synthetic")
    parser.add_argument("--url", default="http://127.0.0.1:7474")
    parser.add_argument("--secret", type=Path, default=DEFAULT_SECRET_PATH)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--ack-disposable-fixture", action="store_true")
    parser.add_argument("--require-range-seek", action="store_true")
    args = parser.parse_args(argv)
    # PROFILE runs the query, so never permit it as a generic local command.
    if args.profile and (
        os.getenv("CI") != "true" or not args.ack_disposable_fixture
    ):
        print("[BLOCKED] PROFILE requires CI=true and --ack-disposable-fixture.")
        return 2
    try:
        prefix = validate_prefix(args.prefix)
        client = LocalPlanClient(args.url, args.secret)
        report = client.query_plan(args.kind, prefix, profile=args.profile)
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        if args.require_range_seek and not report["search_key_range_seek_planned"]:
            print("[HOLD] No indexed range seek observed; do not claim indexing speedup.")
            return 1
        return 0
    except PlanEvidenceError as exc:
        # Only our constant diagnostics; never print server response or input.
        print("[FAIL] Indexed plan evidence unavailable: " + str(exc))
        return 1
    except (ValueError, OSError):
        print("[FAIL] Indexed plan evidence unavailable.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
