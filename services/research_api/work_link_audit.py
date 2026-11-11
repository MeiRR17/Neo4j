"""v0.9.9 bounded, keyset-paginated audit of evidenced Work source links.

Each page is a separate bounded read. Edge IDs are keyset cursors, not
snapshot IDs. Never infer complete corpus review, source rights, authorship,
transitive influence or historical provenance from returned metadata.
"""
from __future__ import annotations

from research_graph.ontology import REVIEW_STATUSES
from services.research_api.db import DatabaseUnavailable
from services.research_api.work_comparison import (
    LINK_FIELDS, _descriptor, _id, _text,
)

MAX_AUDIT_PAGE = 20


def audit_work_link_page(store, *, source_work_id: str,
                         target_work_id: str,
                         after_edge_id: str | None = None,
                         limit: int = 10) -> dict:
    """Read exactly one direction; validate every returned row and lookahead."""
    source = _id(source_work_id, "work", request=True)
    target = _id(target_work_id, "work", request=True)
    if source == target:
        raise ValueError("Two distinct canonical Works are required.")
    if type(limit) is not int or not 1 <= limit <= MAX_AUDIT_PAGE:
        raise ValueError("Page size must be between one and twenty.")
    if after_edge_id is None:
        cursor = ""
    else:
        if type(after_edge_id) is not str or not after_edge_id:
            raise ValueError("The optional cursor must be a canonical Edge ID.")
        cursor = _id(after_edge_id, "edge", request=True)

    # Do not silently return an empty page for missing Work records.
    # Descriptors are bounded and never enter this response.
    _descriptor(store, source)
    _descriptor(store, target)
    rows = store.query("analysis_work_cross_link_page", {
        "source_work_id": source,
        "target_work_id": target,
        "after_edge_id": cursor,
        "fetch_limit": limit + 1,
    })
    if not isinstance(rows, list) or len(rows) > limit + 1:
        raise DatabaseUnavailable("Audit page exceeded read budget.")

    seen_edges, seen_evidence = set(), set()
    checked, last = [], cursor
    for row in rows:
        if not isinstance(row, dict) or set(row) != LINK_FIELDS:
            raise DatabaseUnavailable("Unexpected audit link projection.")
        if (_id(row["source_work_id"], "work") != source or
                _id(row["target_work_id"], "work") != target):
            raise DatabaseUnavailable("Audit page escaped requested Works.")
        edge = _id(row["edge_id"], "edge")
        evidence = _id(row["evidence_id"], "evidence")
        src = _id(row["source_passage_id"], "passage")
        dst = _id(row["target_passage_id"], "passage")
        if (edge <= last or edge in seen_edges or evidence in seen_evidence or
                src == dst):
            raise DatabaseUnavailable("Audit page key order or evidence invalid.")
        last = edge
        seen_edges.add(edge)
        seen_evidence.add(evidence)
        for field in ("edge_review_status", "evidence_review_status"):
            if type(row[field]) is not str or row[field] not in REVIEW_STATUSES:
                raise DatabaseUnavailable("Unsupported audit review state.")
        for field, maximum, required in (
            ("source_ref", 512, True),
            ("target_ref", 512, True),
            ("evidence_source_ref", 512, False),
            ("version_id", 256, False),
            ("rights_tag", 128, False),
        ):
            _text(row[field], maximum, required=required)
        checked.append(dict(row))

    included = checked[:limit]
    joint_approved = sum(
        link["edge_review_status"] == link["evidence_review_status"] == "approved"
        for link in included
    )
    contested = sum(
        link["edge_review_status"] in ("rejected", "disputed") or
        link["evidence_review_status"] in ("rejected", "disputed")
        for link in included
    )
    has_more = len(checked) > limit
    return {
        "schema_version": "0.9.9",
        "source_work_id": source,
        "target_work_id": target,
        "requested_limit": limit,
        "after_edge_id": after_edge_id,
        "links": included,
        "observed_window_denominator": len(included),
        "joint_approved_status_links": joint_approved,
        "contested_status_links": contested,
        "pending_status_links": len(included) - joint_approved - contested,
        "has_more": has_more,
        "next_cursor": included[-1]["edge_id"] if has_more and included else None,
        "sampled_window_only": True,
        "snapshot_consistency_verified": False,
        "source_rights_verified": False,
        "historical_influence_proven": False,
        "research_release_status": "HOLD",
        "note": (
            "One ordered, directed SOURCE_LINK keyset page with exact Evidence "
            "metadata; each request is a separate read. Cursor traversal is "
            "not a consistent graph snapshot, rights check, population "
            "census or proof of historical influence."
        ),
    }
