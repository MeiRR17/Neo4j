"""v0.8.11 read-only, schema-bound source/edition/evidence metadata projection.

Claims about source rights and the original source bytes are NEVER inferred.
This is a private, bounded authenticated API, not an export of source text.
"""
from __future__ import annotations

import re

from research_graph.ontology import CLAIM_KINDS, REVIEW_STATUSES, require_canonical_id
from services.research_api.db import DatabaseUnavailable

SCHEMA = "0.8.11"
KINDS = {"sources": "source", "editions": "edition", "evidence": "evidence"}
MAX_PAGE = 20
SHA256 = re.compile(r"^[a-f0-9]{64}$")
EXPECTED = {
    "sources": frozenset({
        "id", "provider", "source_uri", "version_id", "rights_tag",
        "checksum_sha256",
    }),
    "editions": frozenset({
        "id", "work_id", "version_id", "language", "rights_tag",
        "rights_review_status", "allowed_text_redistribution",
    }),
    "evidence": frozenset({
        "id", "source_record_id", "version_id", "rights_tag",
        "claim_kind", "review_status",
    }),
}


def _canonical(value, prefix):
    try:
        result = require_canonical_id(value)
    except (ValueError, TypeError):
        raise DatabaseUnavailable("Provenance canonical ID invalid.") from None
    if not result.startswith(prefix + ":"):
        raise DatabaseUnavailable("Provenance ID type mismatch.")
    return result


def _text(value, *, max_length=500, nullable=True):
    if value is None and nullable:
        return
    if (not isinstance(value, str) or not value or len(value) > max_length
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)):
        raise DatabaseUnavailable("Provenance metadata field invalid.")


def safe_provenance_item(raw: object, kind: str) -> dict:
    if kind not in KINDS or not isinstance(raw, dict) or set(raw) != EXPECTED[kind]:
        raise DatabaseUnavailable("Provenance projection contains unknown fields.")
    _canonical(raw["id"], KINDS[kind])
    for key, value in raw.items():
        if key in ("id", "allowed_text_redistribution"):
            continue
        if key in ("work_id", "source_record_id"):
            _canonical(value, "work" if key == "work_id" else "source")
        else:
            _text(value, max_length=700 if key == "source_uri" else 300)
    if kind == "sources":
        checksum = raw["checksum_sha256"]
        if checksum is not None and not SHA256.fullmatch(checksum):
            raise DatabaseUnavailable("Source checksum format invalid.")
    if kind == "editions":
        # A metadata listing cannot establish redistribution rights.
        # Historical null means unknown/absent, not consent.
        if raw["allowed_text_redistribution"] not in (None, False):
            raise DatabaseUnavailable("Edition redistribution status is out of scope.")
    if kind == "evidence":
        if raw["claim_kind"] not in CLAIM_KINDS or raw["review_status"] not in REVIEW_STATUSES:
            raise DatabaseUnavailable("Evidence review vocabulary invalid.")
    return dict(raw)


def provenance_page(store, *, kind: str, cursor: str | None, limit: int) -> dict:
    if kind not in KINDS or type(limit) is not int or not 1 <= limit <= MAX_PAGE:
        raise ValueError("Unsupported provenance kind/page limit.")
    clean_cursor = ""
    if cursor is not None:
        try:
            validated = require_canonical_id(cursor)
        except (ValueError, TypeError):
            raise ValueError("Invalid provenance cursor.") from None
        if not validated.startswith(KINDS[kind] + ":"):
            raise ValueError("Provenance cursor kind mismatch.")
        clean_cursor = validated
    rows = store.query(
        "provenance_" + kind, {"cursor": clean_cursor, "fetch_limit": limit + 1}
    )
    if not isinstance(rows, list) or len(rows) > limit + 1:
        raise DatabaseUnavailable("Bounded provenance query returned invalid rows.")
    records = []
    last = clean_cursor
    for row in rows:
        item = safe_provenance_item(row, kind)
        if last and item["id"] <= last:
            raise DatabaseUnavailable("Provenance identifiers out of order.")
        last = item["id"]
        records.append(item)
    has_more = len(records) > limit
    kept = records[:limit]
    return {
        "schema_version": SCHEMA, "kind": kind,
        "items": kept,
        "has_more": has_more, "search_complete": not has_more,
        "next_cursor": kept[-1]["id"] if has_more and kept else None,
        "rights_independently_verified": False,
        "source_bytes_verified": False,
        "source_text_available": False,
        "corpus_snapshot_isolation": False,
    }
