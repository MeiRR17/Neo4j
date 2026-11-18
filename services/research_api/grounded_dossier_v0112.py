"""v0.11.2: review-only Evidence dossier from bounded grounded graph contexts.

This offline-safe, default-off API component packages explicitly selected
Evidence IDs from the v0.11.1 source-reference comparison, with deterministic
metadata provenance and SHA256 for local change detection. A hash is NOT a
signature or corpus snapshot, and is never a license or scholarly approval.
"""
from __future__ import annotations

from hashlib import sha256

from research_graph.ontology import require_canonical_id
from services.research_api.audit_export_v0911 import canonical_bytes
from services.research_api.grounded_compare_v0111 import (
    compare_grounded_passage_contexts, parse_passage_ids,
)
from services.research_api.grounded_context_v0110 import _terms

VERSION = "0.11.2"
MAX_SELECTED_EVIDENCE = 8
MAX_SELECTION_CHARS = 1400
MAX_DOSSIER_BYTES = 24_000


def parse_selected_evidence_ids(value: object) -> tuple[str, ...]:
    """Validate selection and ordering before reading any source metadata."""
    if type(value) is not str or not 1 <= len(value) <= MAX_SELECTION_CHARS:
        raise ValueError("Invalid Evidence selection.")
    identifiers = value.split(",")
    if not 1 <= len(identifiers) <= MAX_SELECTED_EVIDENCE:
        raise ValueError("Require 1–8 canonical Evidence IDs.")
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Duplicate Evidence selection.")
    if identifiers != sorted(identifiers):
        raise ValueError("Evidence selection must be sorted.")
    for identifier in identifiers:
        try:
            require_canonical_id(identifier)
        except (ValueError, TypeError):
            raise ValueError("Canonical Evidence ID required.") from None
        if not identifier.startswith("evidence:"):
            raise ValueError("Only Evidence IDs may be selected.")
    return tuple(identifiers)


def _digest(value: object) -> str:
    raw = canonical_bytes(value)
    if len(raw) > MAX_DOSSIER_BYTES:
        raise ValueError("Grounded Evidence dossier exceeds metadata budget.")
    return sha256(raw).hexdigest()


def build_grounded_evidence_dossier(
    store, *, passage_ids: str, query: str, evidence_ids: str,
) -> dict:
    """Export chosen in-window source anchors, never create research claims.

    Results are only from the bounded 2–3 Passage v0.11.1 preview; this
    routine cannot retrieve omitted pages, licensed content or extra edges.
    """
    identifiers = parse_selected_evidence_ids(evidence_ids)
    # Validate all scopes before the first query.
    scopes = parse_passage_ids(passage_ids)
    _terms(query)

    # Read the maximum 12 deterministic preview contexts to minimize the
    # chance of an omitted item; still NOT an exhaustive corpus traversal.
    comparison = compare_grounded_passage_contexts(
        store, passage_ids=",".join(scopes), query=query, limit=12,
    )
    available = {
        item["evidence_id"]: item for item in comparison["contexts"]
    }
    if any(identifier not in available for identifier in identifiers):
        raise ValueError("Selected Evidence is absent from bounded grounding results.")

    groups = {
        group["source_ref"]: group
        for group in comparison["reference_groups"]
    }
    candidates = []
    for identifier in identifiers:
        item = available[identifier]
        group = groups[item["source_ref"]]
        issues = list(group["uncertainty_codes"])
        candidates.append({
            "evidence_id": identifier,
            "edge_id": item["edge_id"],
            "source_passage_id": item["source_passage_id"],
            "target_passage_id": item["target_passage_id"],
            "observed_in_passage_ids": list(item["observed_in_passage_ids"]),
            "source_ref": item["source_ref"],
            "version_id": item["version_id"],
            "rights_tag": item["rights_tag"],
            "edge_review_status": item["edge_review_status"],
            "evidence_review_status": item["evidence_review_status"],
            "match_basis": item["match_basis"],
            "triage_flags": issues,
            "source_metadata_complete": (
                item["version_id"] is not None and
                item["rights_tag"] is not None
            ),
            "human_review_approved": False,
            "source_rights_independently_verified": False,
            "quote_verified_against_edition": False,
        })

    # Only the hashed query is persisted in this metadata-only artifact;
    # never treat user query text or provider metadata as instructions.
    payload = {
        "schema_version": VERSION,
        "contract_kind": "dviros.research.grounded_evidence_dossier_draft",
        "passage_ids": list(scopes),
        "query_sha256": sha256(query.encode("utf-8")).hexdigest(),
        "selection_count": len(identifiers),
        "selected_evidence_ids": list(identifiers),
        "selected_items": candidates,
        "observed_windows": comparison["passage_windows"],
        "additional_matches_may_exist": comparison[
            "additional_matches_may_exist"
        ],
        "selection_scope": "bounded_returned_source_reference_metadata",
        "generated_claim": None,
        "human_review_required": True,
        "human_approval_recorded": False,
        "source_text_available": False,
        "source_rights_independently_verified": False,
        "graph_snapshot_verified": False,
        "corpus_completeness_verified": False,
        "research_release_status": "HOLD",
        "note": (
            "Draft, metadata-only Evidence selection for human review. "
            "Source tags, versions and graph review labels are observed, "
            "not independently authenticated source rights, citations, "
            "scholarly conclusions or immutable graph snapshots."
        ),
    }
    return {
        "dossier": payload,
        "dossier_sha256": _digest(payload),
        "dossier_digitally_signed": False,
    }


def verify_grounded_evidence_dossier(
    value: object, store, *, passage_ids: str, query: str, evidence_ids: str,
) -> dict:
    """Rebuild from live bounded reads; refuse if any metadata or IDs drift.

    Re-computation across separate graph reads is not snapshot verification.
    The SHA256 prevents accidental modification only; it is NOT secret-key
    authentication or protection against an adversary replacing both files.
    """
    if type(value) is not dict or set(value) != {
        "dossier", "dossier_sha256", "dossier_digitally_signed",
    }:
        raise ValueError("Malformed Evidence dossier envelope.")
    expected = build_grounded_evidence_dossier(
        store, passage_ids=passage_ids, query=query, evidence_ids=evidence_ids,
    )
    if (value != expected or type(value["dossier_sha256"]) is not str or
            value["dossier_digitally_signed"] is not False):
        raise ValueError("Evidence dossier differs from current bounded read.")
    return {
        "schema_version": VERSION,
        "dossier_recomputed": True,
        "selected_count": expected["dossier"]["selection_count"],
        "dossier_digitally_signed": False,
        "graph_snapshot_verified": False,
        "human_approval_recorded": False,
        "research_release_status": "HOLD",
    }
