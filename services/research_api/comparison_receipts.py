"""v0.9.4 deterministic digest of one bounded observed Work comparison.

This is an unsigned, local hash of *returned metadata*, not a signature,
database snapshot, independently verified research source, or archive receipt.
"""
from __future__ import annotations

from hashlib import sha256
import json

from services.research_api.db import DatabaseUnavailable
from services.research_api.queries import READ_OPERATIONS
from services.research_api.work_comparison import compare_works

CANONICALIZATION = "json-sort-keys-utf8-v1"
TEMPLATES = ("analysis_work_cross_links", "analysis_work_descriptor")
MAX_HASH_INPUT = 160_000


def canonical_bytes(value: object) -> bytes:
    """Sort object keys, preserve array order, no whitespace or NaN, UTF-8.

    The input is already strict, validated and bounded by compare_works.
    The digest does NOT prove that two independent reads saw one snapshot.
    """
    try:
        encoded = json.dumps(
            value, sort_keys=True, ensure_ascii=False,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise DatabaseUnavailable("Invalid observation receipt data.") from None
    if len(encoded) > MAX_HASH_INPUT:
        raise DatabaseUnavailable("Observation receipt input exceeds budget.")
    return encoded


def query_templates_sha256() -> str:
    # Version-pinned on-disk Cypher query templates, not live DB revision.
    template_map = {name: READ_OPERATIONS[name] for name in TEMPLATES}
    return sha256(canonical_bytes(template_map)).hexdigest()


def comparison_receipt(store, *, left_work_id: str, right_work_id: str,
                       limit: int = 10) -> dict:
    comparison = compare_works(
        store, left_work_id=left_work_id,
        right_work_id=right_work_id, limit=limit,
    )
    count = (len(comparison["left_to_right"]["links"]) +
             len(comparison["right_to_left"]["links"]))
    if count > 20:
        raise DatabaseUnavailable("Observation exceeds bounded comparison count.")
    truncated = (
        comparison["left_work"]["author_sample_truncated"] or
        comparison["right_work"]["author_sample_truncated"] or
        comparison["left_to_right"]["has_more"] or
        comparison["right_to_left"]["has_more"]
    )
    return {
        "schema_version": "0.9.4",
        "comparison": comparison,
        "canonicalization": CANONICALIZATION,
        "observation_sha256": sha256(canonical_bytes(comparison)).hexdigest(),
        "fixed_query_templates_sha256": query_templates_sha256(),
        "observed_link_count": count,
        "sample_window_truncated": bool(truncated),
        "comparison_snapshot_verified": False,
        "verified_corpus_coverage": False,
        "receipt_digitally_signed": False,
        "source_rights_verified": False,
        "historical_influence_proven": False,
        "research_release_status": "HOLD",
        "note": (
            "Unsigned SHA-256 of one bounded, sequentially observed metadata "
            "response; matching digests show matching encoded output, not "
            "snapshot isolation, completeness, source authenticity, "
            "historical influence or source-rights approval."
        ),
    }
