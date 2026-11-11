"""v0.9.2 bounded SOURCE_LINK frequencies and author-lifetime indicators.

Counts refer to the first 50 canonical incident observed edges, NOT whole-graph
centrality. Years are unverified Person metadata, NOT composition/publication
dates or proof that a source influenced another. No corpus rights are granted.
"""
from __future__ import annotations

from research_graph.ontology import REVIEW_STATUSES, require_canonical_id
from services.research_api.db import DatabaseUnavailable

WINDOW = 50
FREQUENCY_FIELDS = frozenset({
    "edge_id", "source_passage_id", "target_passage_id", "evidence_id",
    "edge_review_status", "evidence_review_status",
})
CHRONOLOGY_FIELDS = frozenset({
    "edge_id", "evidence_id", "source_passage_id", "target_passage_id",
    "source_work_id", "target_work_id", "source_authors", "target_authors",
})
AUTHOR_FIELDS = frozenset({"id", "date_from_year", "date_to_year"})


def _id(value: object, prefix: str, *, user_input: bool = False) -> str:
    try:
        require_canonical_id(value)
    except (TypeError, ValueError):
        if user_input:
            raise ValueError("Canonical passage ID required.") from None
        raise DatabaseUnavailable("Unexpected canonical graph identifier.") from None
    if not value.startswith(prefix + ":"):
        if user_input:
            raise ValueError("Canonical passage ID required.")
        raise DatabaseUnavailable("Unexpected canonical graph identifier.")
    return value


def _status(value: object) -> str:
    if not isinstance(value, str) or value not in REVIEW_STATUSES:
        raise DatabaseUnavailable("Unexpected graph evidence status.")
    return value


def link_frequency(store, *, passage_id: str) -> dict:
    focus = _id(passage_id, "passage", user_input=True)
    rows = store.query("analysis_frequency_window", {
        "passage_id": focus, "fetch_limit": WINDOW + 1,
    })
    if not isinstance(rows, list) or len(rows) > WINDOW + 1:
        raise DatabaseUnavailable("Frequency sample exceeded fixed budget.")
    seen_edges, seen_evidence = set(), set()
    outgoing = incoming = joint_approved = contested = 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != FREQUENCY_FIELDS:
            raise DatabaseUnavailable("Unsafe frequency projection.")
        edge = _id(row["edge_id"], "edge")
        evidence = _id(row["evidence_id"], "evidence")
        source = _id(row["source_passage_id"], "passage")
        target = _id(row["target_passage_id"], "passage")
        if (source == target or focus not in (source, target)
                or edge in seen_edges or evidence in seen_evidence):
            raise DatabaseUnavailable("Duplicate or out-of-scope source link.")
        seen_edges.add(edge)
        seen_evidence.add(evidence)
        _status(row["edge_review_status"])
        _status(row["evidence_review_status"])
    # Only included sample rows contribute to the denominator; the lookahead
    # row validates integrity but must never inflate the published metrics.
    for row in rows[:WINDOW]:
        outgoing += row["source_passage_id"] == focus
        incoming += row["target_passage_id"] == focus
        edge_state = row["edge_review_status"]
        evidence_state = row["evidence_review_status"]
        joint_approved += (edge_state == evidence_state == "approved")
        contested += (edge_state in ("rejected", "disputed")
                      or evidence_state in ("rejected", "disputed"))
    denominator = min(len(rows), WINDOW)
    return {
        "schema_version": "0.9.2",
        "passage_id": focus,
        "sample_order": "ascending_canonical_source_link_edge_id",
        "sample_limit": WINDOW,
        "observed_link_denominator": denominator,
        "outgoing_observed_links": outgoing,
        "incoming_observed_links": incoming,
        "joint_approved_status_links": joint_approved,
        "contested_status_links": contested,
        "pending_status_links": denominator - joint_approved - contested,
        "joint_approved_status_fraction": (
            round(joint_approved / denominator, 4) if denominator else None
        ),
        "window_truncated": len(rows) > WINDOW,
        "whole_graph_centrality_verified": False,
        "graph_snapshot_isolation_verified": False,
        "source_rights_verified": False,
        "scholarly_quality_approved": False,
        "historical_influence_proven": False,
        "research_release_status": "HOLD",
        "note": (
            "Count and fraction are for the first 50 incident observed links "
            "only; approval flags are internal review states, not source "
            "rights, centrality, authority, or verified influence."
        ),
    }


def _authors(value: object) -> list[dict]:
    if not isinstance(value, list) or len(value) > 2:
        raise DatabaseUnavailable("Unbounded author projection.")
    result, seen = [], set()
    for row in value:
        if not isinstance(row, dict) or set(row) != AUTHOR_FIELDS:
            raise DatabaseUnavailable("Unsafe author metadata projection.")
        author_id = _id(row["id"], "person")
        if author_id in seen:
            raise DatabaseUnavailable("Duplicate historical author identity.")
        seen.add(author_id)
        start, end = row["date_from_year"], row["date_to_year"]
        for year in (start, end):
            if year is not None and (type(year) is not int or
                                     not -4000 <= year <= 2100):
                raise DatabaseUnavailable("Invalid author year metadata.")
        if start is not None and end is not None and start > end:
            raise DatabaseUnavailable("Reversed author year metadata.")
        result.append(dict(row))
    return result


def author_chronology(store, *, source_id: str, target_id: str) -> dict:
    source = _id(source_id, "passage", user_input=True)
    target = _id(target_id, "passage", user_input=True)
    if source == target:
        raise ValueError("Distinct source and target passages required.")
    rows = store.query("analysis_author_lifetimes", {
        "source_id": source, "target_id": target,
    })
    if not isinstance(rows, list) or len(rows) > 1:
        raise DatabaseUnavailable("Author-lifetime result exceeds bound.")
    edge_id = evidence_id = source_work_id = target_work_id = None
    source_authors, target_authors = [], []
    status, relation = "no_eligible_observed_link_or_work", "unknown"
    if rows:
        row = rows[0]
        if not isinstance(row, dict) or set(row) != CHRONOLOGY_FIELDS:
            raise DatabaseUnavailable("Unsafe author-lifetime projection.")
        edge_id = _id(row["edge_id"], "edge")
        evidence_id = _id(row["evidence_id"], "evidence")
        if (_id(row["source_passage_id"], "passage") != source or
                _id(row["target_passage_id"], "passage") != target):
            raise DatabaseUnavailable("Lifetime analysis escaped link scope.")
        source_work_id = _id(row["source_work_id"], "work")
        target_work_id = _id(row["target_work_id"], "work")
        source_authors = _authors(row["source_authors"])
        target_authors = _authors(row["target_authors"])
        if source_work_id == target_work_id:
            status = "same_work"
        elif not source_authors or not target_authors:
            status = "missing_author_metadata"
        elif len(source_authors) != 1 or len(target_authors) != 1:
            status = "ambiguous_author_metadata"
        elif (source_authors[0]["date_from_year"] is None or
              source_authors[0]["date_to_year"] is None or
              target_authors[0]["date_from_year"] is None or
              target_authors[0]["date_to_year"] is None):
            status = "incomplete_year_metadata"
        else:
            status = "author_lifetime_intervals_compared"
            s, t = source_authors[0], target_authors[0]
            if s["date_from_year"] > t["date_to_year"]:
                relation = "source_author_lifetime_later"
            elif t["date_from_year"] > s["date_to_year"]:
                relation = "target_author_lifetime_later"
            else:
                relation = "lifetimes_overlap"
    return {
        "schema_version": "0.9.2",
        "source_passage_id": source,
        "target_passage_id": target,
        "sample_link_edge_id": edge_id,
        "sample_link_evidence_id": evidence_id,
        "source_work_id": source_work_id,
        "target_work_id": target_work_id,
        "source_authors": source_authors,
        "target_authors": target_authors,
        "metadata_status": status,
        "author_lifetime_relation": relation,
        "source_years_independently_verified": False,
        "composition_or_publication_order_verified": False,
        "historical_influence_proven": False,
        "source_rights_verified": False,
        "graph_snapshot_isolation_verified": False,
        "research_release_status": "HOLD",
        "note": (
            "Tentative comparison of author year metadata for one observed "
            "source-link; authorship, composition dates, historical influence "
            "and source rights are not independently established."
        ),
    }
