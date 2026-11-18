"""v0.11.1: compare bounded, observed Evidence anchors across Passage windows.

This is a feature-flagged *metadata* grounding aid. It reuses the strict
v0.11.0 graph read/projection, deduplicates one Evidence seen from two focus
Passages, and surfaces source-version/review/rights metadata divergence for
human triage. It cannot verify quotations, genuine contradictions or rights.
"""
from __future__ import annotations

from services.research_api.db import DatabaseUnavailable
from services.research_api.grounded_context_v0110 import (
    MAX_WINDOW, _terms, grounded_context_preview,
)
from research_graph.ontology import require_canonical_id

VERSION = "0.11.1"
MAX_PASSAGES = 3
MIN_PASSAGES = 2
MAX_CONTEXTS = 12
MAX_IDS_CHARS = 600

_STATUS_CONTESTED = frozenset({"rejected", "disputed"})


def parse_passage_ids(raw: object) -> tuple[str, ...]:
    """Validate *all* graph scopes before any DB read or partial response."""
    if type(raw) is not str or not 1 <= len(raw) <= MAX_IDS_CHARS:
        raise ValueError("Bounded Passage ID list required.")
    values = raw.split(",")
    if not MIN_PASSAGES <= len(values) <= MAX_PASSAGES:
        raise ValueError("Require two or three canonical Passage IDs.")
    if len(values) != len(set(values)):
        raise ValueError("Duplicate Passage scope.")
    for value in values:
        try:
            require_canonical_id(value)
        except (TypeError, ValueError):
            raise ValueError("Canonical Passage ID required.") from None
        if not value.startswith("passage:"):
            raise ValueError("Only Passage IDs are allowed.")
    return tuple(sorted(values))


def _compatibility(existing: dict, observed: dict) -> None:
    """One Evidence must never change provenance across focus windows."""
    immutable = (
        "edge_id", "evidence_id", "source_passage_id",
        "target_passage_id", "source_ref", "version_id", "rights_tag",
        "edge_review_status", "evidence_review_status", "match_basis",
    )
    if any(existing[name] != observed[name] for name in immutable):
        raise DatabaseUnavailable(
            "Inconsistent Evidence metadata across observed Passage windows."
        )


def _reference_group(source_ref: str, contexts: list[dict]) -> dict:
    """Exact source-ref byte equality only; never inferred textual identity."""
    versions = sorted({
        entry["version_id"] for entry in contexts
        if entry["version_id"] is not None
    })
    rights = sorted({
        entry["rights_tag"] for entry in contexts
        if entry["rights_tag"] is not None
    })
    review_statuses = sorted({
        status
        for entry in contexts
        for status in (
            entry["edge_review_status"], entry["evidence_review_status"]
        )
    })
    issues = []
    if len(versions) > 1:
        issues.append("OBSERVED_VERSION_ID_DIVERGENCE")
    if len(rights) > 1:
        issues.append("OBSERVED_RIGHTS_TAG_DIVERGENCE")
    if len(review_statuses) > 1:
        issues.append("OBSERVED_REVIEW_STATUS_DIVERGENCE")
    if any(status in _STATUS_CONTESTED for status in review_statuses):
        issues.append("CONTESTED_REVIEW_STATUS_OBSERVED")
    if any(entry["version_id"] is None for entry in contexts):
        issues.append("MISSING_VERSION_METADATA")
    if any(entry["rights_tag"] is None for entry in contexts):
        issues.append("MISSING_RIGHTS_METADATA")
    return {
        "source_ref": source_ref,
        "evidence_ids": sorted(entry["evidence_id"] for entry in contexts),
        "observed_passage_ids": sorted({
            pid for entry in contexts for pid in entry["observed_in_passage_ids"]
        }),
        "version_id_variants": versions,
        "rights_tag_variants": rights,
        "review_status_variants": review_statuses,
        "uncertainty_codes": issues,
        "disagreement_is_scholarly_conflict": False,
        "source_text_verified": False,
        "source_rights_verified": False,
    }


def compare_grounded_passage_contexts(
    store, *, passage_ids: str, query: str, limit: int = 10,
) -> dict:
    """Build a deterministic, capped cross-Passage metadata review preview.

    Reuses fixed read-only graph access, with <=3 database queries and
    <=20 observed links per Passage. Human reviewers must verify citations,
    editions, permissions and conflicting interpretations separately.
    """
    ids = parse_passage_ids(passage_ids)
    _terms(query)
    if type(limit) is not int or not 1 <= limit <= MAX_CONTEXTS:
        raise ValueError("Invalid bounded cross-Passage context limit.")

    candidates: dict[str, dict] = {}
    windows = []
    observed_matches = 0
    more_may_exist = False
    for passage_id in ids:
        preview = grounded_context_preview(
            store, passage_id=passage_id, query=query, limit=10,
        )
        windows.append({
            "passage_id": passage_id,
            "observed_window_limit": MAX_WINDOW,
            "matched_in_observed_window": preview[
                "matched_in_observed_window"
            ],
            "observed_window_truncated": preview[
                "observed_window_truncated"
            ],
            "additional_matches_may_exist": preview[
                "additional_matches_may_exist"
            ],
        })
        observed_matches += preview["matched_in_observed_window"]
        more_may_exist |= preview["additional_matches_may_exist"]
        for entry in preview["contexts"]:
            evidence_id = entry["evidence_id"]
            if evidence_id not in candidates:
                candidates[evidence_id] = {
                    **entry,
                    "observed_in_passage_ids": [passage_id],
                }
            else:
                _compatibility(candidates[evidence_id], entry)
                candidates[evidence_id]["observed_in_passage_ids"].append(
                    passage_id
                )

    ranked = sorted(candidates.values(), key=lambda row: (
        row["match_basis"] != "SOURCE_REF_EXACT_SUBSTRING",
        row["source_ref"], row["evidence_id"], row["edge_id"],
    ))
    contexts = ranked[:limit]
    if len(ranked) > limit:
        more_may_exist = True

    grouped: dict[str, list[dict]] = {}
    for entry in contexts:
        grouped.setdefault(entry["source_ref"], []).append(entry)
    references = [
        _reference_group(source_ref, grouped[source_ref])
        for source_ref in sorted(grouped)
    ]
    status = (
        "CONTEXTS_FOUND" if contexts
        else "INCOMPLETE_NO_MATCH" if more_may_exist
        else "NO_METADATA_MATCH"
    )
    return {
        "schema_version": VERSION,
        "feature": "GRAPH_RAG_CROSS_PASSAGE_METADATA_COMPARE",
        "passage_ids": list(ids),
        "retrieval_status": status,
        "passage_windows": windows,
        "contexts": contexts,
        "reference_groups": references,
        "matched_observations_in_sampled_windows": observed_matches,
        "distinct_evidence_in_bounded_results": len(ranked),
        "returned_context_count": len(contexts),
        "returned_contexts_truncated": len(ranked) > limit,
        "additional_matches_may_exist": more_may_exist,
        "generated_answer": None,
        "human_review_required": True,
        "scholarly_conflict_verified": False,
        "source_text_available": False,
        "source_rights_verified": False,
        "graph_snapshot_verified": False,
        "whole_corpus_retrieval_verified": False,
        "research_release_status": "HOLD",
        "note": (
            "Exact source-ref grouping within sampled observed graph windows "
            "only. Metadata drift and status variants are triage signals, "
            "not licensed citations, actual scholarly contradictions, "
            "complete corpus coverage or model-approved claims."
        ),
    }
