"""v0.9.3 strict work-and-author comparison over observed graph metadata.

Two work descriptors and two small directional SOURCE_LINK windows are read
through fixed Cypher statements. No author identity, link count, status or
year is a scholarly claim, verified rights decision, or an influence proof.
"""
from __future__ import annotations

from research_graph.ontology import REVIEW_STATUSES, require_canonical_id
from services.research_api.db import DatabaseUnavailable

MAX_LINKS = 10
WORK_FIELDS = frozenset({"id", "title", "provider_ref", "author_sample"})
AUTHOR_FIELDS = frozenset({"id", "date_from_year", "date_to_year"})
LINK_FIELDS = frozenset({
    "edge_id", "source_passage_id", "target_passage_id", "evidence_id",
    "edge_review_status", "evidence_review_status", "source_ref",
    "target_ref", "evidence_source_ref", "version_id", "rights_tag",
})


def _id(value: object, kind: str, *, request: bool = False) -> str:
    try:
        require_canonical_id(value)
    except (ValueError, TypeError):
        if request:
            raise ValueError("A canonical Work ID is required.") from None
        raise DatabaseUnavailable("Malformed graph identity.") from None
    if not value.startswith(kind + ":"):
        if request:
            raise ValueError("A canonical Work ID is required.")
        raise DatabaseUnavailable("Unexpected graph identity.")
    return value


def _text(value: object, limit: int, *, required: bool = False) -> None:
    if value is None and not required:
        return
    if (not isinstance(value, str) or not value or len(value) > limit or
            any(ord(character) < 32 for character in value)):
        raise DatabaseUnavailable("Unexpected bounded graph metadata.")


def _descriptor(store, work_id: str) -> dict:
    rows = store.query("analysis_work_descriptor", {"work_id": work_id})
    if not isinstance(rows, list) or len(rows) > 1:
        raise DatabaseUnavailable("Ambiguous Work identity.")
    if not rows:
        raise LookupError("Work not found.")
    record = rows[0]
    if not isinstance(record, dict) or set(record) != WORK_FIELDS:
        raise DatabaseUnavailable("Unexpected Work projection.")
    if _id(record["id"], "work") != work_id:
        raise DatabaseUnavailable("Wrong Work returned.")
    _text(record["title"], 512)
    _text(record["provider_ref"], 512)
    authors = record["author_sample"]
    if not isinstance(authors, list) or len(authors) > 3:
        raise DatabaseUnavailable("Unbounded author sample.")
    seen, cleaned = set(), []
    for author in authors:
        if not isinstance(author, dict) or set(author) != AUTHOR_FIELDS:
            raise DatabaseUnavailable("Unexpected author projection.")
        identifier = _id(author["id"], "person")
        if identifier in seen:
            raise DatabaseUnavailable("Repeated author reference.")
        seen.add(identifier)
        beginning, end = author["date_from_year"], author["date_to_year"]
        for year in (beginning, end):
            if year is not None and (type(year) is not int or
                                     not -4000 <= year <= 2100):
                raise DatabaseUnavailable("Invalid recorded author year.")
        if beginning is not None and end is not None and beginning > end:
            raise DatabaseUnavailable("Reversed recorded author interval.")
        cleaned.append(dict(author))
    # A third row is solely a lookahead; never imply all authors were read.
    truncated = len(cleaned) > 2
    sample = sorted(cleaned, key=lambda row: row["id"])[:2]
    state = ("truncated" if truncated else
             "missing" if not sample else
             "single" if len(sample) == 1 else "multiple")
    return {
        "id": work_id,
        "title": record["title"],
        "provider_ref": record["provider_ref"],
        "author_sample": sample,
        "author_sample_truncated": truncated,
        "author_metadata_status": state,
    }


def _direction(store, source_work: str, target_work: str, limit: int) -> dict:
    rows = store.query("analysis_work_cross_links", {
        "source_work_id": source_work,
        "target_work_id": target_work,
        "fetch_limit": limit + 1,
    })
    if not isinstance(rows, list) or len(rows) > limit + 1:
        raise DatabaseUnavailable("Cross-work window exceeded limit.")
    seen_edges, seen_evidence = set(), set()
    checked = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != LINK_FIELDS:
            raise DatabaseUnavailable("Unexpected cross-work link projection.")
        edge_id = _id(row["edge_id"], "edge")
        evidence_id = _id(row["evidence_id"], "evidence")
        source_id = _id(row["source_passage_id"], "passage")
        target_id = _id(row["target_passage_id"], "passage")
        if (source_id == target_id or edge_id in seen_edges or
                evidence_id in seen_evidence):
            raise DatabaseUnavailable("Duplicate cross-work evidence.")
        seen_edges.add(edge_id)
        seen_evidence.add(evidence_id)
        for status in ("edge_review_status", "evidence_review_status"):
            if row[status] not in REVIEW_STATUSES:
                raise DatabaseUnavailable("Unsupported research review state.")
        for field, size, required in (
            ("source_ref", 512, True), ("target_ref", 512, True),
            ("evidence_source_ref", 512, False),
            ("version_id", 256, False), ("rights_tag", 128, False),
        ):
            _text(row[field], size, required=required)
        checked.append(dict(row))
    included = checked[:limit]
    joint_approved = sum(
        row["edge_review_status"] == row["evidence_review_status"] == "approved"
        for row in included
    )
    contested = sum(
        row["edge_review_status"] in ("rejected", "disputed") or
        row["evidence_review_status"] in ("rejected", "disputed")
        for row in included
    )
    return {
        "source_work_id": source_work,
        "target_work_id": target_work,
        "links": included,
        "observed_window_denominator": len(included),
        "joint_approved_status_links": joint_approved,
        "contested_status_links": contested,
        "pending_status_links": len(included) - joint_approved - contested,
        "has_more": len(checked) > limit,
    }


def compare_works(store, *, left_work_id: str, right_work_id: str,
                  limit: int = 10) -> dict:
    left_id = _id(left_work_id, "work", request=True)
    right_id = _id(right_work_id, "work", request=True)
    if left_id == right_id or type(limit) is not int or not 1 <= limit <= MAX_LINKS:
        raise ValueError("Distinct Works and limit in range 1..10 required.")
    left = _descriptor(store, left_id)
    right = _descriptor(store, right_id)
    forward = _direction(store, left_id, right_id, limit)
    reverse = _direction(store, right_id, left_id, limit)
    all_links = forward["links"] + reverse["links"]
    if (len({row["edge_id"] for row in all_links}) != len(all_links) or
            len({row["evidence_id"] for row in all_links}) != len(all_links)):
        raise DatabaseUnavailable("Duplicate bidirectional evidence.")
    # Equal IDs are meaningful only for the sampled author metadata,
    # never verification of author attribution across editions.
    left_authors = {item["id"] for item in left["author_sample"]}
    right_authors = {item["id"] for item in right["author_sample"]}
    complete_sample = (
        bool(left_authors) and bool(right_authors) and
        not left["author_sample_truncated"] and
        not right["author_sample_truncated"]
    )
    overlap = sorted(left_authors & right_authors) if complete_sample else []
    overlap_status = (
        "insufficient_author_metadata" if not complete_sample else
        "shared_author_id_observed" if overlap else "different_author_ids_observed"
    )
    return {
        "schema_version": "0.9.3",
        "left_work": left,
        "right_work": right,
        "left_to_right": forward,
        "right_to_left": reverse,
        "author_id_overlap_status": overlap_status,
        "shared_author_ids": overlap,
        "directional_window_limit": limit,
        "all_cross_work_links_examined": False,
        "author_attribution_independently_verified": False,
        "historical_influence_proven": False,
        "source_rights_verified": False,
        "graph_snapshot_isolation_verified": False,
        "research_release_status": "HOLD",
        "note": (
            "Two per-direction, bounded samples of observed SOURCE_LINK metadata. "
            "Author IDs and approval labels are unverified catalog observations, "
            "not demonstrated authorship, citation, source rights or influence."
        ),
    }
