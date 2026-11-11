"""v0.8.3: rights-safe, coverage-gated indexed metadata *title prefix* lookup.

This endpoint differs from the v0.8.2 bounded substring/alias scanner:
it only searches normalized title prefixes and never assumes alias
coverage, full-text indexing, complete historical evidence or user rights.
"""
from __future__ import annotations

from typing import Any

from services.research_api.db import DatabaseUnavailable
from services.research_api.metadata_search import (
    ALLOWED_KINDS, _safe_hit, fold_metadata, validate_search,
)

INDEX_SCHEMA = "0.8.3"
INDEX_VERSION = "search_key_v1"
MAX_LIMIT = 20

# Exact names and labels from migration 004. Never accept them from a caller.
INDEX_DEFINITIONS = {
    "works": ("work_search_key_v1", "Work"),
    "persons": ("person_search_key_v1", "Person"),
    "passages": ("passage_search_key_v1", "Passage"),
    "concepts": ("concept_search_key_v1", "Concept"),
}


CAPABILITY_SCHEMA = "0.8.5"


def physical_index_status(store: Any, kind: str) -> str:
    """Exact physical index readiness, never raw index metadata."""
    if kind not in INDEX_DEFINITIONS:
        raise ValueError("Unknown metadata kind.")
    name, label = INDEX_DEFINITIONS[kind]
    rows = store.query("index_state", {"index_name": name})
    if not isinstance(rows, list) or len(rows) > 1:
        raise DatabaseUnavailable("Index inventory invalid.")
    if not rows:
        return "missing"
    row = rows[0]
    if (not isinstance(row, dict) or set(row) != {
            "name", "type", "entityType", "labelsOrTypes", "properties", "state"
        } or row["name"] != name or row["type"] != "RANGE"
            or row["entityType"] != "NODE"
            or row["labelsOrTypes"] != [label]
            or row["properties"] != ["search_key_v1"]):
        raise DatabaseUnavailable("Index definition invalid.")
    if row["state"] == "ONLINE":
        return "ready"
    if row["state"] in ("POPULATING", "FAILED"):
        return "not_online"
    raise DatabaseUnavailable("Index state invalid.")


def verify_online_index(store: Any, kind: str) -> None:
    """A full title backfill is not sufficient without the physical index."""
    if physical_index_status(store, kind) != "ready":
        raise DatabaseUnavailable("Metadata index not ready.")


def read_coverage(store: Any, kind: str) -> dict:
    if kind not in ALLOWED_KINDS:
        raise ValueError("Unknown metadata kind.")
    rows = store.query(f"index_coverage_{kind}")
    if not isinstance(rows, list) or len(rows) != 1:
        raise DatabaseUnavailable("Search index coverage unavailable.")
    row = rows[0]
    if not isinstance(row, dict) or set(row) != {"total", "covered"}:
        raise DatabaseUnavailable("Search index coverage invalid.")
    total, covered = row["total"], row["covered"]
    if (type(total) is not int or type(covered) is not int
            or not 0 <= covered <= total <= 1_000_000):
        raise DatabaseUnavailable("Index counts invalid.")
    return {"total": total, "covered": covered,
            "complete": total > 0 and covered == total}


def verify_coverage(store: Any, kind: str) -> dict:
    """Every indexed lookup rechecks physical index and source freshness."""
    verify_online_index(store, kind)
    coverage = read_coverage(store, kind)
    if not coverage["complete"]:
        raise DatabaseUnavailable("Index backfill incomplete.")
    return coverage


def indexed_capability(store: Any, *, kind: str) -> dict:
    """Point-in-time private DvirOS probe; no content or automatic fallback."""
    state = physical_index_status(store, kind)
    coverage = None
    if state == "ready":
        coverage = read_coverage(store, kind)
        if coverage["total"] == 0:
            state = "empty"
        elif not coverage["complete"]:
            state = "incomplete"
    return {
        "schema_version": CAPABILITY_SCHEMA,
        "kind": kind, "index_version": INDEX_VERSION,
        "index_status": state, "indexed_prefix_ready": state == "ready",
        "index_coverage": coverage, "bounded_scan_supported": True,
        "scan_candidate_window_limit": 50,
        "scan_requires_cursor_completion": True,
        "alias_matching_on_index": False, "full_text_indexed": False,
        "source_trail_verified": False, "text_available": False,
        "corpus_status": "unreviewed_metadata_only",
    }


def search_indexed_metadata(store: Any, *, kind: str,
                            query: str, cursor: str | None = None,
                            limit: int = 10, language: str = "") -> dict:
    """Use the versioned Neo4j range index for title PREFIX matches only.

    This is a read-only service. A separate, operator-acknowledged backfill
    populates search_key_v1; completeness is checked on EVERY request.
    """
    folded, clean_cursor, language = validate_search(
        kind, query, cursor, limit, language)
    if not folded:
        raise ValueError("Indexed search requires a nonempty metadata prefix.")
    if len(folded) > 200:
        raise ValueError("Normalized search prefix exceeds budget.")
    coverage = verify_coverage(store, kind)
    rows = store.query(f"indexed_{kind}", {
        "prefix": folded, "cursor": clean_cursor,
        "fetch_limit": limit + 1, "language": language,
    })
    if not isinstance(rows, list) or len(rows) > limit + 1:
        raise DatabaseUnavailable("Indexed search result exceeds budget.")
    seen = set()
    previous = clean_cursor
    hits = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "id", "title", "source_anchor", "aliases"} or row.get("aliases") != []:
            raise DatabaseUnavailable("Indexed metadata field projection invalid.")
        hit = _safe_hit(row, kind, folded, query)
        if (hit is None or hit["match_basis"] != "title"
                or not fold_metadata(hit["title"]).startswith(folded)
                or hit["id"] in seen or (previous and hit["id"] <= previous)):
            raise DatabaseUnavailable("Indexed metadata order or title mismatch.")
        previous = hit["id"]
        seen.add(previous)
        hits.append(hit)
    has_more = len(hits) > limit
    selected = hits[:limit]
    return {
        "schema_version": INDEX_SCHEMA,
        "kind": kind,
        "items": selected,
        "next_cursor": selected[-1]["id"] if has_more and selected else None,
        "has_more": has_more,
        "search_complete": not has_more,
        "match_order": "indexed_title_prefix_canonical_id",
        "index_version": INDEX_VERSION,
        "index_coverage": coverage,
        "alias_matching_available": False,
        "full_text_indexed": False,
        "source_trail_verified": False,
        "text_available": False,
        "corpus_status": "unreviewed_metadata_only",
    }
