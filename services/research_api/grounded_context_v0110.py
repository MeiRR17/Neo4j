"""v0.11.0 GraphRAG foundation: bounded source-reference context, no generation.

This first, feature-flagged vertical slice reuses the fixed read-only
analysis_source_links graph query and its strict evidence projection checks.
Only observed SOURCE_LINK metadata is returned, NEVER source text, quotations,
model answers, human approval, or evidence of historical influence.
"""
from __future__ import annotations

import re
import unicodedata

from services.research_api.analytics import analysis_page
from services.research_api.db import DatabaseUnavailable

VERSION = "0.11.0"
MAX_CONTEXTS = 10
MAX_WINDOW = 20
MAX_QUERY_CHARS = 120
MAX_QUERY_TERMS = 12
MAX_TERM_CHARS = 64
_TOKEN = re.compile(r"\w+", flags=re.UNICODE)


def _fold(value: str) -> str:
    """Case/diacritic-normalize *matching only*, never rewrite source IDs."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(
        ch for ch in normalized
        if unicodedata.category(ch) != "Mn"
    )


def _terms(query: object) -> tuple[str, ...]:
    if (type(query) is not str or not 2 <= len(query) <= MAX_QUERY_CHARS
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in query)):
        raise ValueError("Invalid bounded source-reference search.")
    terms = tuple(dict.fromkeys(_TOKEN.findall(_fold(query))))
    if (not 1 <= len(terms) <= MAX_QUERY_TERMS
            or any(len(word) > MAX_TERM_CHARS for word in terms)):
        raise ValueError("Invalid source-reference terms.")
    return terms


def grounded_context_preview(
    store, *, passage_id: str, query: str, limit: int = 10,
) -> dict:
    """Find exact graph evidence anchors without generating a prose answer.

    Every candidate is a raw observed-link metadata reference. Even graph
    review_status='approved' is not proof of rights, verified passage text or
    human scholarly approval for this new research task.
    """
    terms = _terms(query)
    if type(limit) is not int or not 1 <= limit <= MAX_CONTEXTS:
        raise ValueError("Invalid bounded result limit.")

    # analysis_page validates canonical passage scope, projection allowlist,
    # edge/evidence IDs, statuses, bounded graph rows and read-only query.
    # A 20-row observed window may be truncated; do not imply completeness.
    page = analysis_page(
        store, kind="source-links", passage_id=passage_id, limit=MAX_WINDOW,
    )
    seen_evidence: set[str] = set()
    candidates = []
    for row in page["items"]:
        evidence_id = row["evidence_id"]
        if evidence_id in seen_evidence:
            raise DatabaseUnavailable("Duplicate grounding Evidence ID.")
        seen_evidence.add(evidence_id)
        source_ref = row["source_ref"]
        if source_ref is None:
            continue
        folded = _fold(source_ref)
        if not all(token in folded for token in terms):
            continue
        exact = _fold(query.strip()) in folded
        candidates.append({
            "edge_id": row["id"],
            "evidence_id": evidence_id,
            "source_passage_id": row["source_passage_id"],
            "target_passage_id": row["target_passage_id"],
            "source_ref": source_ref,
            "version_id": row["version_id"],
            "rights_tag": row["rights_tag"],
            "edge_review_status": row["review_status"],
            "evidence_review_status": row["evidence_review_status"],
            "match_basis": (
                "SOURCE_REF_EXACT_SUBSTRING" if exact
                else "SOURCE_REF_ALL_TERMS"
            ),
            "observed_source_link_only": True,
            "source_text_available": False,
            "human_claim_approved": False,
            "source_rights_verified": False,
        })
    # Deterministic ranking; provider titles/refs are untrusted metadata
    # and NEVER interpreted as prompt instructions or AI response content.
    ranked = sorted(candidates, key=lambda row: (
        row["match_basis"] != "SOURCE_REF_EXACT_SUBSTRING",
        row["evidence_id"], row["edge_id"],
    ))
    included = ranked[:limit]
    incomplete = page["has_more"]
    status = (
        "CANDIDATES_FOUND" if included else
        "WINDOW_TRUNCATED_NO_MATCH" if incomplete else
        "NO_METADATA_MATCH"
    )
    return {
        "schema_version": VERSION,
        "feature": "GRAPH_RAG_METADATA_CONTEXT_PREVIEW",
        "passage_id": passage_id,
        "retrieval_status": status,
        "contexts": included,
        "matched_in_observed_window": len(ranked),
        "candidate_limit": limit,
        "observed_window_limit": MAX_WINDOW,
        "observed_window_truncated": incomplete,
        "additional_matches_may_exist": incomplete or len(ranked) > limit,
        "generated_answer": None,
        "claim_approved": False,
        "licensed_source_text_available": False,
        "independent_source_rights_verified": False,
        "graph_snapshot_verified": False,
        "historical_influence_proven": False,
        "research_release_status": "HOLD",
        "note": (
            "Source-reference metadata matching only; no quotation, source "
            "text, model generation, licensed rights, or scholarly conclusion. "
            "A bounded graph window does not prove complete retrieval."
        ),
    }
