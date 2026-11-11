"""v0.9.1 evidence-bounded, directed shortest observed SOURCE_LINK paths.

A successful result is the shortest *observed eligible path within two hops*,
not a proof of historical influence or snapshot consistency. A direct query
runs first; the 2-hop query runs only if no qualifying direct edge is found.
Only unreviewed/approved link and Evidence states may constitute candidates.
"""
from __future__ import annotations

from research_graph.ontology import require_canonical_id
from services.research_api.db import DatabaseUnavailable

EDGE_FIELDS = frozenset({
    "edge_id", "from_passage_id", "to_passage_id", "evidence_id",
    "claim_kind", "edge_review_status", "evidence_review_status",
    "source_ref", "version_id", "rights_tag",
})
ROW_FIELDS = frozenset({"passage_ids", "edges", "hop_count"})
ELIGIBLE = frozenset({"unreviewed", "approved"})


def _canonical(value: object, prefix: str, *, request: bool = False) -> str:
    try:
        require_canonical_id(value)
    except (TypeError, ValueError):
        if request:
            raise ValueError("Canonical passage ID is required.") from None
        raise DatabaseUnavailable("Malformed evidence path.") from None
    if not value.startswith(prefix + ":"):
        if request:
            raise ValueError("Canonical passage ID is required.")
        raise DatabaseUnavailable("Malformed evidence path.")
    return value


def _optional_text(value: object, bound: int) -> None:
    if value is None:
        return
    if (not isinstance(value, str) or not 0 < len(value) <= bound
            or any(ord(c) < 32 for c in value)):
        raise DatabaseUnavailable("Malformed evidence metadata.")


def _validate_path(row: object, source: str, target: str, hops: int) -> dict:
    if not isinstance(row, dict) or set(row) != ROW_FIELDS:
        raise DatabaseUnavailable("Unexpected evidence path projection.")
    if type(row["hop_count"]) is not int or row["hop_count"] != hops:
        raise DatabaseUnavailable("Unexpected evidence hop count.")
    ids, edges = row["passage_ids"], row["edges"]
    if (not isinstance(ids, list) or len(ids) != hops + 1 or
            not isinstance(edges, list) or len(edges) != hops):
        raise DatabaseUnavailable("Evidence route shape invalid.")
    for value in ids:
        _canonical(value, "passage")
    if (ids[0] != source or ids[-1] != target or
            len(ids) != len(set(ids))):
        raise DatabaseUnavailable("Evidence path scope/cycle invalid.")
    seen_edges, seen_evidence = set(), set()
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict) or set(edge) != EDGE_FIELDS:
            raise DatabaseUnavailable("Unexpected edge evidence fields.")
        _canonical(edge["edge_id"], "edge")
        _canonical(edge["evidence_id"], "evidence")
        _canonical(edge["from_passage_id"], "passage")
        _canonical(edge["to_passage_id"], "passage")
        if (edge["from_passage_id"] != ids[index]
                or edge["to_passage_id"] != ids[index + 1]):
            raise DatabaseUnavailable("Evidence path direction mismatch.")
        if edge["claim_kind"] != "OBSERVED_SOURCE_LINK":
            raise DatabaseUnavailable("Evidence path claim kind invalid.")
        if (edge["edge_review_status"] not in ELIGIBLE
                or edge["evidence_review_status"] not in ELIGIBLE):
            raise DatabaseUnavailable("Rejected/disputed evidence cannot support path.")
        for name, bound in (("source_ref", 512), ("version_id", 256),
                            ("rights_tag", 128)):
            _optional_text(edge[name], bound)
        if (edge["edge_id"] in seen_edges or
                edge["evidence_id"] in seen_evidence):
            raise DatabaseUnavailable("Duplicated evidence may not support a route.")
        seen_edges.add(edge["edge_id"])
        seen_evidence.add(edge["evidence_id"])
    return {"passage_ids": list(ids), "edges": [dict(edge) for edge in edges],
            "hop_count": hops}


def evidence_path_page(store, *, source_id: str, target_id: str,
                       limit: int = 5) -> dict:
    source = _canonical(source_id, "passage", request=True)
    target = _canonical(target_id, "passage", request=True)
    if source == target or type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError("Distinct canonical passages and bounded limit required.")
    params = {"source_id": source, "target_id": target, "fetch_limit": limit + 1}
    # Two fixed, separately bounded read operations avoid unconstrained path
    # language from user input. Direct edges always take precedence.
    rows = store.query("analysis_path_direct", params)
    hops = 1
    if rows == []:
        rows = store.query("analysis_path_two_hop", params)
        hops = 2
    if not isinstance(rows, list) or len(rows) > limit + 1:
        raise DatabaseUnavailable("Evidence path response exceeded budget.")
    checked = [_validate_path(row, source, target, hops) for row in rows]
    keys = [tuple(edge["edge_id"] for edge in row["edges"]) for row in checked]
    if len(keys) != len(set(keys)):
        raise DatabaseUnavailable("Duplicate graph route detected.")
    # Never treat a 2-hop observation as a verified global shortest path:
    # only the allowlisted SOURCE_LINK subset is examined, without isolation.
    return {
        "schema_version": "0.9.1",
        "source_passage_id": source,
        "target_passage_id": target,
        "paths": checked[:limit],
        "observed_shortest_hops": hops if checked else None,
        "has_more": len(checked) > limit,
        "max_hops": 2,
        "eligible_review_statuses": ["unreviewed", "approved"],
        "whole_graph_shortest_path_proven": False,
        "graph_snapshot_isolation_verified": False,
        "historical_influence_proven": False,
        "source_rights_verified": False,
        "research_release_status": "HOLD",
        "note": (
            "Shortest eligible directed SOURCE_LINK route within 2 hops "
            "at observation time; not proof of citation, influence, "
            "graph completeness, rights or a consistent snapshot."
        ),
    }
