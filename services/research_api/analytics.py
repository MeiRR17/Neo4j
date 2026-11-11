"""v0.9.0 bounded exploratory graph analytics; no inference of influence."""
from __future__ import annotations

from research_graph.ontology import REVIEW_STATUSES, require_canonical_id
from services.research_api.db import DatabaseUnavailable

OPERATIONS = {"source-links": "analysis_source_links",
              "shared-targets": "analysis_shared_targets"}
FIELDS = {
    "source-links": frozenset({
        "id", "source_passage_id", "target_passage_id", "evidence_id",
        "claim_kind", "review_status", "evidence_review_status",
        "source_ref", "version_id", "rights_tag",
    }),
    "shared-targets": frozenset({
        "candidate_passage_id", "shared_target_passage_id",
        "focus_evidence_id", "candidate_evidence_id",
        "focus_review_status", "candidate_review_status",
        "focus_evidence_review_status", "candidate_evidence_review_status",
        "focus_source_ref", "candidate_source_ref",
    }),
}
NOTES = {
    "source-links": "A provider link does not prove direct citation, agreement or historical influence.",
    "shared-targets": "Shared link targets suggest co-reference, not verified co-citation or influence.",
}


def _id(value: object, kind: str) -> None:
    try:
        require_canonical_id(value)
    except (ValueError, TypeError):
        raise DatabaseUnavailable("Invalid analysis evidence.") from None
    if not value.startswith(kind + ":"):
        raise DatabaseUnavailable("Invalid analysis evidence.")


def _text(value: object, maximum: int) -> None:
    if value is not None and (not isinstance(value, str) or len(value) > maximum
                              or any(ord(char) < 32 for char in value)):
        raise DatabaseUnavailable("Invalid analysis metadata.")


def _check_row(kind: str, row: object, focus: str) -> dict:
    if not isinstance(row, dict) or set(row) != FIELDS[kind]:
        raise DatabaseUnavailable("Unexpected analysis projection.")
    if kind == "source-links":
        for field, prefix in (
            ("id", "edge"), ("source_passage_id", "passage"),
            ("target_passage_id", "passage"), ("evidence_id", "evidence")
        ):
            _id(row[field], prefix)
        if focus not in (row["source_passage_id"], row["target_passage_id"]):
            raise DatabaseUnavailable("Analysis escaped requested scope.")
        if row["claim_kind"] != "OBSERVED_SOURCE_LINK":
            raise DatabaseUnavailable("Analysis evidence kind mismatch.")
        for field in ("review_status", "evidence_review_status"):
            if row[field] not in REVIEW_STATUSES:
                raise DatabaseUnavailable("Invalid analysis review status.")
        for field, length in (("source_ref", 512), ("version_id", 256),
                              ("rights_tag", 128)):
            _text(row[field], length)
    else:
        for field, prefix in (
            ("candidate_passage_id", "passage"),
            ("shared_target_passage_id", "passage"),
            ("focus_evidence_id", "evidence"),
            ("candidate_evidence_id", "evidence")
        ):
            _id(row[field], prefix)
        if row["candidate_passage_id"] == focus:
            raise DatabaseUnavailable("Self-reference candidate rejected.")
        for field in ("focus_review_status", "candidate_review_status",
                      "focus_evidence_review_status",
                      "candidate_evidence_review_status"):
            if row[field] not in REVIEW_STATUSES:
                raise DatabaseUnavailable("Invalid analysis review status.")
        for field in ("focus_source_ref", "candidate_source_ref"):
            _text(row[field], 512)
    return dict(row)


def analysis_page(store, *, kind: str, passage_id: str, limit: int = 10) -> dict:
    if kind not in OPERATIONS or type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("Unknown analysis or invalid limit.")
    try:
        require_canonical_id(passage_id)
    except (ValueError, TypeError):
        raise ValueError("Canonical passage ID required.") from None
    if not passage_id.startswith("passage:"):
        raise ValueError("Canonical passage ID required.")
    rows = store.query(OPERATIONS[kind], {"id": passage_id, "fetch_limit": limit + 1})
    if not isinstance(rows, list) or len(rows) > limit + 1:
        raise DatabaseUnavailable("Bounded analysis window exceeded.")
    checked = [_check_row(kind, row, passage_id) for row in rows]
    if len({tuple(sorted(row.items())) for row in checked}) != len(checked):
        raise DatabaseUnavailable("Duplicate evidence must not inflate analysis.")
    return {
        "schema_version": "0.9.0",
        "analysis_kind": kind,
        "focus_passage_id": passage_id,
        "items": checked[:limit],
        "has_more": len(checked) > limit,
        "result_window_limit": 20,
        "corpus_completeness_verified": False,
        "source_rights_verified": False,
        "historical_influence_proven": False,
        "research_release_status": "HOLD",
        "note": NOTES[kind],
    }
