"""v0.12.0: bounded read-only research-tool registry and checkpointed execution.

Neo-only first slice of the DvirOS agent-tool integration. No autonomous LLM,
dynamic Cypher, graph mutation, saved tasks or human approval. An unkeyed
request checkpoint binds a validated plan to an execution *request*, but
provides no identity proof or resumable persisted job state.
"""
from __future__ import annotations

from hashlib import sha256
import hmac

from pydantic import ValidationError

from research_graph.ontology import require_canonical_id
from services.research_api.audit_export_v0911 import canonical_bytes
from services.research_api.db import DatabaseUnavailable
from services.research_api.grounded_context_v0110 import (
    _terms, grounded_context_preview,
)
from services.research_api.grounded_compare_v0111 import (
    parse_passage_ids, compare_grounded_passage_contexts,
)
from services.research_api.grounded_dossier_v0112 import (
    parse_selected_evidence_ids, build_grounded_evidence_dossier,
)
from services.research_api.models import (
    GroundedContextPreview, GroundedCrossPassagePreview,
    GroundedEvidenceDossierEnvelope,
)

VERSION = "0.12.0"
MAX_READS = 3
MAX_CARDS = 12
OPERATIONS = {
    "source_context": {
        "description": "One canonical Passage, fixed source-link metadata retrieval",
        "min_scopes": 1, "max_scopes": 1, "max_candidates": 10,
        "source_code_version": "0.11.0",
    },
    "compare_contexts": {
        "description": "Two-to-three Passage source-reference metadata comparison",
        "min_scopes": 2, "max_scopes": 3, "max_candidates": 12,
        "source_code_version": "0.11.1",
    },
    "review_dossier": {
        "description": "Selected 1-8 Evidence metadata-only draft dossier",
        "min_scopes": 2, "max_scopes": 3, "max_candidates": 8,
        "source_code_version": "0.11.2",
    },
}
RESPONSE_MODELS = {
    "source_context": GroundedContextPreview,
    "compare_contexts": GroundedCrossPassagePreview,
    "review_dossier": GroundedEvidenceDossierEnvelope,
}


def read_only_tool_catalog() -> dict:
    """No dynamic operation registration or mutation permission exists."""
    return {
        "schema_version": VERSION,
        "registry": [
            {
                "operation": name,
                **spec,
                "read_only": True,
                "provider_or_llm_calls": False,
                "writes_allowed": False,
                "human_approval_implied": False,
            }
            for name, spec in OPERATIONS.items()
        ],
        "max_graph_reads_per_execution": MAX_READS,
        "graph_writes_allowed": False,
        "dynamic_query_execution_allowed": False,
        "research_release_status": "HOLD",
    }


def _validated_request(
    *, operation: object, passage_ids: object, query: object,
    evidence_ids: object, limit: object, read_budget: object,
) -> tuple[dict, str, str]:
    if type(operation) is not str or operation not in OPERATIONS:
        raise ValueError("Unregistered or unsafe research tool.")
    spec = OPERATIONS[operation]
    if type(passage_ids) is not str or not 1 <= len(passage_ids) <= 600:
        raise ValueError("Invalid bounded Passage scope.")
    if spec["min_scopes"] == 1:
        if "," in passage_ids:
            raise ValueError("Single-Passage tool requires one canonical Passage.")
        try:
            require_canonical_id(passage_ids)
        except (TypeError, ValueError):
            raise ValueError("Canonical Passage ID required.") from None
        if not passage_ids.startswith("passage:"):
            raise ValueError("Only Passage IDs are permitted.")
        scopes = (passage_ids,)
    else:
        scopes = parse_passage_ids(passage_ids)
    _terms(query)
    if type(limit) is not int or not 1 <= limit <= spec["max_candidates"]:
        raise ValueError("Tool candidate limit exceeds fixed capacity.")
    if type(read_budget) is not int or not 1 <= read_budget <= MAX_READS:
        raise ValueError("Invalid research read budget.")
    if len(scopes) > read_budget:
        raise ValueError("Planned fixed graph reads exceed request budget.")
    if operation == "review_dossier":
        selected = parse_selected_evidence_ids(evidence_ids)
    elif evidence_ids is not None:
        raise ValueError("Evidence selection only allowed for review dossier.")
    else:
        selected = ()

    parameters = {
        "operation": operation,
        "passage_ids": list(scopes),
        "query_sha256": sha256(query.encode("utf-8")).hexdigest(),
        "selected_evidence_ids": list(selected),
        "candidate_limit": limit,
        "read_budget": read_budget,
        "scheduled_graph_reads": len(scopes),
        "max_links_per_graph_read": 20,
        "total_links_observation_bound": 20 * len(scopes),
    }
    return parameters, ",".join(scopes), ",".join(selected)


def plan_read_only_research_tool(
    *, operation: str, passage_ids: str, query: str,
    evidence_ids: str | None = None, limit: int = 10,
    read_budget: int = 3,
) -> dict:
    """Prepare a deterministic stateless plan without querying the graph."""
    params, _, _ = _validated_request(
        operation=operation, passage_ids=passage_ids, query=query,
        evidence_ids=evidence_ids, limit=limit, read_budget=read_budget,
    )
    # Checkpoint is intentionally *not* a signature; bearer authentication
    # is a separate API responsibility. No secret or query text is persisted.
    fingerprint = sha256(canonical_bytes({
        "schema_version": VERSION, "parameters": params,
    })).hexdigest()
    return {
        "schema_version": VERSION,
        "plan_status": "READY_TO_EXECUTE",
        "operation": operation,
        "parameters": params,
        "request_checkpoint_sha256": fingerprint,
        "checkpoint_authenticates_reviewer": False,
        "checkpoint_persists_execution_state": False,
        "graph_read_only": True,
        "graph_reads_executed": 0,
        "provider_or_llm_calls": False,
        "research_release_status": "HOLD",
    }


def _review_cards(operation: str, result: dict) -> list[dict]:
    """Project existing validated metadata only, never source text or notes."""
    records = (
        result["dossier"]["selected_items"] if operation == "review_dossier"
        else result["contexts"]
    )
    cards = []
    for item in records[:MAX_CARDS]:
        cards.append({
            "evidence_id": item["evidence_id"],
            "edge_id": item["edge_id"],
            "source_passage_id": item["source_passage_id"],
            "target_passage_id": item["target_passage_id"],
            "source_ref": item["source_ref"],
            "version_id": item["version_id"],
            "rights_tag": item["rights_tag"],
            "evidence_review_status": item["evidence_review_status"],
            "human_approved": False,
            "source_rights_verified": False,
            "source_text_available": False,
        })
    return cards


def run_read_only_research_tool(
    store, *, operation: str, passage_ids: str, query: str,
    evidence_ids: str | None = None, limit: int = 10,
    read_budget: int = 3, request_checkpoint_sha256: str,
) -> dict:
    """Execute exactly one registered fixed read-only tool on a matched plan.

    Re-running the same request is a **fresh observation**, not a resume of
    saved work. Returned step records are synchronous completed-phase
    markers, not a live progress stream or background job.
    """
    plan = plan_read_only_research_tool(
        operation=operation, passage_ids=passage_ids, query=query,
        evidence_ids=evidence_ids, limit=limit, read_budget=read_budget,
    )
    expected = plan["request_checkpoint_sha256"]
    if (
        type(request_checkpoint_sha256) is not str
        or len(request_checkpoint_sha256) != 64
        or not hmac.compare_digest(expected, request_checkpoint_sha256)
    ):
        raise ValueError("Research tool checkpoint or request scope differs.")

    _, scope, selected = _validated_request(
        operation=operation, passage_ids=passage_ids, query=query,
        evidence_ids=evidence_ids, limit=limit, read_budget=read_budget,
    )
    if operation == "source_context":
        output = grounded_context_preview(
            store, passage_id=scope, query=query, limit=limit,
        )
    elif operation == "compare_contexts":
        output = compare_grounded_passage_contexts(
            store, passage_ids=scope, query=query, limit=limit,
        )
    elif operation == "review_dossier":
        output = build_grounded_evidence_dossier(
            store, passage_ids=scope, query=query, evidence_ids=selected,
        )
    else:  # Defense in depth; _validated_request already refuses this.
        raise ValueError("Unregistered research operation.")

    try:
        typed = RESPONSE_MODELS[operation].model_validate(output)
        result = typed.model_dump(mode="json")
    except (ValidationError, ValueError, TypeError):
        raise DatabaseUnavailable("Research tool returned unsafe source projection.") from None

    cards = _review_cards(operation, result)
    return {
        "schema_version": VERSION,
        "tool_operation": operation,
        "request_checkpoint_sha256": expected,
        "execution_status": "COMPLETED_REVIEW_PREVIEW",
        "phase_log": [
            {"phase": "INPUTS_CHECKED", "status": "COMPLETED"},
            {"phase": "FIXED_READ_ONLY_RETRIEVAL", "status": "COMPLETED"},
            {"phase": "EVIDENCE_CARDS_PROJECTED", "status": "COMPLETED"},
        ],
        "scheduled_graph_reads": plan["parameters"]["scheduled_graph_reads"],
        "max_source_links_per_read": 20,
        "returned_card_count": len(cards),
        "evidence_cards": cards,
        "tool_result": result,
        "stateless_replay_only": True,
        "execution_state_persisted": False,
        "human_review_required": True,
        "graph_writes_performed": False,
        "provider_or_llm_calls": False,
        "human_approval_recorded": False,
        "source_rights_verified": False,
        "research_release_status": "HOLD",
    }
