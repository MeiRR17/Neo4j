"""Bounded bilingual metadata search, without a full-text or rights-release claim.

A read-only, cursor-based candidate window is used until an ingestion-time
normalized index is deployed. Search completeness is surfaced explicitly;
DO NOT present a single 50-record window as corpus-wide search.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from research_graph.ontology import require_canonical_id
from services.research_api.db import DatabaseUnavailable

SEARCH_SCHEMA = "0.8.2"
SCAN_LIMIT = 50
QUERY_LIMIT = 100
ALLOWED_KINDS = {
    "works": ("work", "metadata_works"),
    "persons": ("person", "metadata_persons"),
    "passages": ("passage", "metadata_passages"),
    "concepts": ("concept", "metadata_concepts"),
}
LANGUAGES = frozenset({"", "he", "en", "ar", "yi"})
ALLOWED_ROW_KEYS = {"id", "title", "source_anchor", "aliases"}
SAFE_CHARACTER = re.compile(r"^[^\x00-\x1f\x7f]*$")


def fold_metadata(value: str) -> str:
    """Normalize disposable lookup text, never graph canonical identity."""
    if not isinstance(value, str):
        raise ValueError("Search metadata must be text.")
    if not SAFE_CHARACTER.fullmatch(value):
        raise ValueError("Control characters forbidden in metadata.")
    text = unicodedata.normalize("NFKD", value).casefold()
    output = []
    for character in text:
        group = unicodedata.category(character)
        if group.startswith("M"):
            continue
        if group.startswith(("P", "S", "Z")):
            output.append(" ")
        else:
            output.append(character)
    return " ".join("".join(output).split())


def safe_id(raw: str, prefix: str) -> str:
    if not isinstance(raw, str) or not raw.startswith(prefix + ":"):
        raise ValueError("Invalid canonical search identifier.")
    try:
        require_canonical_id(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid canonical search identifier.") from exc
    return raw


def validate_search(kind: str, query: str, cursor: str | None,
                    limit: int, language: str) -> tuple[str, str, str]:
    if kind not in ALLOWED_KINDS:
        raise ValueError("Unknown metadata entity type.")
    if not isinstance(query, str) or len(query) > QUERY_LIMIT:
        raise ValueError("Metadata query exceeds bound.")
    folded = fold_metadata(query.strip())
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
        raise ValueError("Metadata search limit exceeds bound.")
    if language not in LANGUAGES or (language and kind != "works"):
        raise ValueError("Unsupported language selector.")
    clean_cursor = safe_id(cursor, ALLOWED_KINDS[kind][0]) if cursor else ""
    return folded, clean_cursor, language


def _safe_hit(row: dict, kind: str, folded_query: str, raw_query: str) -> dict | None:
    """Strict projection: never forward arbitrary DB property or source text."""
    prefix, _ = ALLOWED_KINDS[kind]
    if not isinstance(row, dict) or set(row) - ALLOWED_ROW_KEYS:
        raise DatabaseUnavailable("Metadata projection contract mismatch.")
    try:
        entity_id = safe_id(row.get("id"), prefix)
        title = row.get("title")
        anchor = row.get("source_anchor")
        aliases = row.get("aliases")
        if not isinstance(title, str) or len(title) > 300 or not SAFE_CHARACTER.fullmatch(title):
            raise ValueError("Invalid metadata title.")
        if anchor is not None and (not isinstance(anchor, str) or len(anchor) > 500
                                   or not SAFE_CHARACTER.fullmatch(anchor)):
            raise ValueError("Invalid metadata anchor.")
        if not isinstance(aliases, list) or len(aliases) > 8 or any(
            not isinstance(alias, str) or len(alias) > 150 or
            not SAFE_CHARACTER.fullmatch(alias) for alias in aliases
        ):
            raise ValueError("Invalid metadata alias list.")
        canonical_match = raw_query.strip() == entity_id if raw_query else False
        fields = [title, *aliases]
        title_match = bool(folded_query and folded_query in fold_metadata(title))
        alias_match = bool(folded_query and any(
            folded_query in fold_metadata(alias) for alias in aliases
        ))
        if folded_query and not (canonical_match or title_match or alias_match):
            return None
    except (ValueError, TypeError) as exc:
        raise DatabaseUnavailable("Metadata projection contract mismatch.") from exc
    return {
        "id": entity_id,
        "kind": prefix,
        "title": title,
        "source_anchor": anchor,
        "match_basis": "canonical_id" if canonical_match else
                       "title" if title_match or not folded_query else "alias",
        "review_status": "unreviewed",
        "source_verification": "NOT_VERIFIED",
        "rights_status": "NOT_ASSESSED",
        "text_available": False,
    }


def search_metadata(store: Any, *, kind: str, query: str = "",
                    cursor: str | None = None, limit: int = 10,
                    language: str = "") -> dict:
    """Scan up to 50 candidates, page by SCANNED ID, not last matched ID.

    Correctness: no matches are skipped between pages. A client must follow
    next_cursor until search_complete=True for a complete (non-ranked) scan.
    """
    folded, clean_cursor, language = validate_search(kind, query, cursor, limit, language)
    operation = ALLOWED_KINDS[kind][1]
    rows = store.query(operation, {
        "cursor": clean_cursor, "language": language,
        "fetch_limit": SCAN_LIMIT + 1,
    })
    if not isinstance(rows, list) or len(rows) > SCAN_LIMIT + 1:
        raise DatabaseUnavailable("Metadata candidate budget exceeded.")
    seen = set()
    matched = []
    scanned = 0
    last = clean_cursor
    exhausted_window = len(rows) > SCAN_LIMIT
    for row in rows[:SCAN_LIMIT]:
        if not isinstance(row, dict):
            raise DatabaseUnavailable("Metadata row format invalid.")
        entity_id = row.get("id")
        try:
            safe_id(entity_id, ALLOWED_KINDS[kind][0])
        except (ValueError, TypeError) as exc:
            raise DatabaseUnavailable("Metadata record identity invalid.") from exc
        if entity_id in seen or (last and entity_id <= last):
            raise DatabaseUnavailable("Metadata rows not canonically ordered.")
        seen.add(entity_id)
        last = entity_id
        scanned += 1
        hit = _safe_hit(row, kind, folded, query)
        if hit is not None:
            matched.append(hit)
            if len(matched) == limit:
                break
    has_more = (scanned < len(rows)) or exhausted_window
    return {
        "schema_version": SEARCH_SCHEMA,
        "kind": kind,
        "items": matched,
        "next_cursor": last if has_more else None,
        "has_more": has_more,
        "search_complete": not has_more,
        "scanned_candidates": scanned,
        "candidate_window_limit": SCAN_LIMIT,
        "corpus_status": "unreviewed_metadata_only",
        "match_order": "canonical_id_scan_not_relevance_ranked",
        "normalization": "unicode_nfkd_casefold_marks_punctuation",
        "text_available": False,
        "source_trail_verified": False,
        "full_text_indexed": False,
    }
