"""v0.9.5 minimal-cost read-only PROFILE parser and fixed-query runner.

No arbitrary Cypher, production data, query result values, plan Details,
credential strings or source titles may appear in benchmark output.
"""
from __future__ import annotations

import json
from hashlib import sha256
from time import perf_counter_ns
from urllib import request, error

from scripts.search_index_plan import LocalPlanClient, PlanEvidenceError
from services.research_api.queries import READ_OPERATIONS

OPERATIONS = {
    "work_descriptor": "analysis_work_descriptor",
    "forward_links": "analysis_work_cross_links",
    "reverse_links": "analysis_work_cross_links",
    "incident_frequency": "analysis_frequency_window",
}
MAX_BODY = 256_000
MAX_PLAN_NODES = 100
MAX_PLAN_DEPTH = 18
MAX_RETURNED_ROWS = 51
MAX_DB_HITS = 250_000
MAX_LATENCY_MS = 8_000.0
# These are defensive profiling budgets on a tiny disposable CI fixture,
# NOT operational SLO targets or proof of realistic large-scale performance.


def statement_hash(operation: str) -> str:
    if operation not in OPERATIONS:
        raise PlanEvidenceError("Unsupported benchmark plan selector.")
    statement = READ_OPERATIONS[OPERATIONS[operation]]
    return sha256(statement.encode("utf-8")).hexdigest()


def parse_profile(body: object, operation: str) -> dict:
    if operation not in OPERATIONS or not isinstance(body, dict):
        raise PlanEvidenceError("Unsupported benchmark response.")
    if body.get("errors") or body.get("queryType") not in (None, "r"):
        raise PlanEvidenceError("Profile was not a clean read-only observation.")
    data = body.get("data")
    if not isinstance(data, dict):
        raise PlanEvidenceError("Missing graph profile data.")
    fields, values = data.get("fields"), data.get("values")
    if (not isinstance(fields, list) or
            not all(isinstance(value, str) for value in fields) or
            not isinstance(values, list) or
            len(values) > MAX_RETURNED_ROWS):
        raise PlanEvidenceError("Profile result exceeded row budget.")
    if any(not isinstance(row, list) or len(row) != len(fields) for row in values):
        raise PlanEvidenceError("Malformed profile result row.")
    if body.get("queryPlan") is not None:
        raise PlanEvidenceError("Unexpected EXPLAIN plan alongside PROFILE.")
    root = body.get("profiledQueryPlan")
    if not isinstance(root, dict):
        raise PlanEvidenceError("Missing profiler operator tree.")
    stack = [(root, 0)]
    names, hits = [], 0
    scan_detected = False
    while stack:
        node, depth = stack.pop()
        if (not isinstance(node, dict) or depth > MAX_PLAN_DEPTH or
                len(names) >= MAX_PLAN_NODES):
            raise PlanEvidenceError("Profiler plan exceeded structural bounds.")
        name = node.get("operatorType")
        args = node.get("arguments")
        children = node.get("children")
        if (not isinstance(name, str) or len(name) > 100 or
                not isinstance(args, dict) or not isinstance(children, list)
                or len(children) > MAX_PLAN_NODES):
            raise PlanEvidenceError("Invalid profiler operator.")
        # Never print Neo4j's plan Details; they might include source values.
        safe_name = name.split("@", 1)[0]
        if not safe_name.isascii() or not safe_name.replace("_", "").isalnum():
            safe_name = "OtherOperator"
        names.append(safe_name)
        scan_detected |= safe_name in ("AllNodesScan", "NodeByLabelScan")
        node_hits = node.get("dbHits", args.get("DbHits", 0))
        if type(node_hits) is not int or not 0 <= node_hits <= MAX_DB_HITS:
            raise PlanEvidenceError("Profiler db-hits budget exceeded.")
        hits += node_hits
        if hits > MAX_DB_HITS:
            raise PlanEvidenceError("Total profiler db-hits budget exceeded.")
        for child in reversed(children):
            stack.append((child, depth + 1))
    # Values are deliberately discarded after only counting list lengths.
    return {
        "operation": operation,
        "read_template_sha256": statement_hash(operation),
        "returned_rows": len(values),
        "operator_count": len(names),
        "operator_types": names,
        "db_hits": hits,
        "label_or_full_scan_detected": bool(scan_detected),
        "source_values_exposed": False,
        "representative_performance_proven": False,
        "production_release_approved": False,
    }


class FixedAnalyticsProfiler(LocalPlanClient):
    """Use only the existing loopback, no-redirect credential-safe client."""

    def profile(self, operation: str, params: dict) -> dict:
        if operation not in OPERATIONS:
            raise PlanEvidenceError("Unsupported benchmark operation.")
        expected_keys = {
            "work_descriptor": {"work_id"},
            "forward_links": {"source_work_id", "target_work_id", "fetch_limit"},
            "reverse_links": {"source_work_id", "target_work_id", "fetch_limit"},
            "incident_frequency": {"passage_id", "fetch_limit"},
        }[operation]
        if not isinstance(params, dict) or set(params) != expected_keys:
            raise PlanEvidenceError("Unexpected benchmark parameters.")
        for k, v in params.items():
            if (k == "fetch_limit" and (type(v) is not int or v not in (11, 51))):
                raise PlanEvidenceError("Invalid fixed result window.")
            if k != "fetch_limit":
                from research_graph.ontology import require_canonical_id
                try:
                    require_canonical_id(v)
                except (ValueError, TypeError):
                    raise PlanEvidenceError("Invalid benchmark canonical identity.") from None
                expected_type = "passage" if k == "passage_id" else "work"
                if not v.startswith(expected_type + ":"):
                    raise PlanEvidenceError("Unexpected benchmark identity type.")
        statement = "PROFILE " + READ_OPERATIONS[OPERATIONS[operation]]
        payload = json.dumps({
            "statement": statement,
            "parameters": params,
            "accessMode": "Read",
            "maxExecutionTime": 5,
        }, separators=(",", ":")).encode("utf-8")
        if len(payload) > 15_000:
            raise PlanEvidenceError("Unexpected oversized profile statement.")
        req = request.Request(
            self.endpoint, data=payload, method="POST", headers=self.headers)
        started = perf_counter_ns()
        try:
            with self.opener.open(req, timeout=8) as response:
                if response.status != 202:
                    raise PlanEvidenceError("Graph profiler request unavailable.")
                raw = response.read(MAX_BODY + 1)
                if len(raw) > MAX_BODY:
                    raise PlanEvidenceError("Profile response byte limit exceeded.")
                body = json.loads(raw.decode("utf-8"))
        except (error.URLError, OSError, ValueError, UnicodeError):
            raise PlanEvidenceError("Graph profiler request unavailable.") from None
        elapsed_ms = (perf_counter_ns() - started) / 1_000_000
        if elapsed_ms > MAX_LATENCY_MS:
            raise PlanEvidenceError("Profiler wall-clock safety budget exceeded.")
        report = parse_profile(body, operation)
        report["observed_wall_ms"] = round(elapsed_ms, 3)
        return report
