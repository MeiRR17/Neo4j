"""v0.12.1 private HMAC receipt for one completed read-only research tool run.

A receipt binds exactly one validated v0.12.0 plan and completed execution.
Offline verification requires the original local service key, NOT graph access.
The local key is not a researcher identity, trusted clock, immutable graph
revision, independent edition-rights check, or publication authorization.
"""
from __future__ import annotations

from hashlib import sha256
import hmac
import re

from pydantic import ValidationError

from research_graph.ontology import require_canonical_id
from services.research_api.audit_export_v0911 import canonical_bytes
from services.research_api.models import ResearchToolPlan, ResearchToolExecution
from services.research_api.research_tool_runner_v0120 import (
    OPERATIONS, RESPONSE_MODELS, _review_cards,
    plan_read_only_research_tool, run_read_only_research_tool,
)

VERSION = "0.12.1"
DOMAIN = b"dviros/neo/read-only-research-run/v0.12.1\n"
MAX_EXECUTION_BYTES = 160_000
MAX_RECEIPT_BYTES = 8_192
HEX_SHA256 = re.compile(r"[a-f0-9]{64}\Z")


def _canonical_object(value: object, model: type, name: str) -> dict:
    if type(value) is not dict:
        raise ValueError("Invalid " + name + " envelope.")
    try:
        normalized = model.model_validate(value).model_dump(mode="json")
    except (ValidationError, ValueError, TypeError):
        raise ValueError("Invalid " + name + " contract.") from None
    if normalized != value:
        raise ValueError("Noncanonical " + name + " contract.")
    return normalized


def _valid_plan(value: object) -> dict:
    plan = _canonical_object(value, ResearchToolPlan, "tool plan")
    params = plan["parameters"]
    name = plan["operation"]
    if name not in OPERATIONS or params["operation"] != name:
        raise ValueError("Unregistered tool in plan.")
    scopes = params["passage_ids"]
    if (
        len(scopes) < OPERATIONS[name]["min_scopes"]
        or len(scopes) > OPERATIONS[name]["max_scopes"]
        or len(set(scopes)) != len(scopes)
        or (len(scopes) > 1 and scopes != sorted(scopes))
        or params["scheduled_graph_reads"] != len(scopes)
        or params["total_links_observation_bound"] != len(scopes) * 20
        or params["max_links_per_graph_read"] != 20
        or params["read_budget"] < len(scopes)
        or params["candidate_limit"] > OPERATIONS[name]["max_candidates"]
    ):
        raise ValueError("Research tool plan bounds are inconsistent.")
    for passage_id in scopes:
        try:
            require_canonical_id(passage_id)
        except (TypeError, ValueError):
            raise ValueError("Invalid canonical Passage ID.") from None
        if not passage_id.startswith("passage:"):
            raise ValueError("Unexpected graph scope.")
    selected = params["selected_evidence_ids"]
    if (
        (name == "review_dossier" and not 1 <= len(selected) <= 8)
        or (name != "review_dossier" and selected)
        or selected != sorted(set(selected))
    ):
        raise ValueError("Invalid selected Evidence in plan.")
    for evidence_id in selected:
        try:
            require_canonical_id(evidence_id)
        except (TypeError, ValueError):
            raise ValueError("Invalid canonical Evidence ID.") from None
        if not evidence_id.startswith("evidence:"):
            raise ValueError("Unexpected Evidence selection.")
    fingerprint = sha256(canonical_bytes({
        "schema_version": "0.12.0", "parameters": params,
    })).hexdigest()
    if not hmac.compare_digest(
        fingerprint, plan["request_checkpoint_sha256"]
    ):
        raise ValueError("Research tool plan checkpoint does not match scope.")
    return plan


def _valid_execution(plan: dict, value: object) -> dict:
    result = _canonical_object(value, ResearchToolExecution, "tool execution")
    operation = plan["operation"]
    if (
        result["tool_operation"] != operation
        or result["request_checkpoint_sha256"]
        != plan["request_checkpoint_sha256"]
        or result["scheduled_graph_reads"]
        != plan["parameters"]["scheduled_graph_reads"]
        or result["returned_card_count"] != len(result["evidence_cards"])
        or [p["phase"] for p in result["phase_log"]] != [
            "INPUTS_CHECKED", "FIXED_READ_ONLY_RETRIEVAL",
            "EVIDENCE_CARDS_PROJECTED",
        ]
    ):
        raise ValueError("Execution does not match the planned tool.")
    nested = _canonical_object(
        result["tool_result"], RESPONSE_MODELS[operation], "tool output",
    )
    if (
        result["evidence_cards"] != _review_cards(operation, nested)
        or result["returned_card_count"] > plan["parameters"]["candidate_limit"]
    ):
        raise ValueError("Evidence cards differ from validated tool output.")
    if operation == "source_context":
        if nested["passage_id"] != plan["parameters"]["passage_ids"][0]:
            raise ValueError("Source context changed Passage scope.")
    elif operation == "compare_contexts":
        if nested["passage_ids"] != plan["parameters"]["passage_ids"]:
            raise ValueError("Comparison changed Passage scope.")
    elif operation == "review_dossier":
        dossier = nested["dossier"]
        if (
            dossier["passage_ids"] != plan["parameters"]["passage_ids"]
            or dossier["selected_evidence_ids"] !=
            plan["parameters"]["selected_evidence_ids"]
            or dossier["query_sha256"] != plan["parameters"]["query_sha256"]
        ):
            raise ValueError("Review dossier changed request scope.")
    return result


def _secure_secret(secret: object) -> bytes:
    if (
        type(secret) is not str or not 40 <= len(secret) <= 256
        or any(ch.isspace() for ch in secret)
    ):
        raise ValueError("Invalid research service signing secret.")
    return secret.encode("utf-8")


def _digest_bounded(value: object, maximum: int) -> str:
    raw = canonical_bytes(value)
    if len(raw) > maximum:
        raise ValueError("Signed research run metadata budget exceeded.")
    return sha256(raw).hexdigest()


def _signed_receipt(plan: dict, execution: dict, secret: str) -> dict:
    execution_digest = _digest_bounded(execution, MAX_EXECUTION_BYTES)
    receipt = {
        "schema_version": VERSION,
        "contract_kind": "dviros.neo.signed_read_only_tool_execution",
        "tool_operation": plan["operation"],
        "request_checkpoint_sha256": plan["request_checkpoint_sha256"],
        "execution_sha256": execution_digest,
        "scheduled_graph_reads": execution["scheduled_graph_reads"],
        "returned_card_count": execution["returned_card_count"],
        "ordered_evidence_ids": [
            card["evidence_id"] for card in execution["evidence_cards"]
        ],
        "execution_status": "COMPLETED_REVIEW_PREVIEW",
        "provenance_scope": "single_bounded_read_only_observation",
        "hmac_verified_by_local_service_secret": True,
        "reviewer_identity_verified": False,
        "durable_job_state_created": False,
        "immutable_graph_snapshot_verified": False,
        "independent_source_rights_verified": False,
        "human_research_approval_recorded": False,
        "research_release_status": "HOLD",
    }
    digest = _digest_bounded(receipt, MAX_RECEIPT_BYTES)
    mac = hmac.new(
        _secure_secret(secret),
        DOMAIN + digest.encode("ascii"),
        sha256,
    ).hexdigest()
    return {
        "receipt": receipt,
        "receipt_sha256": digest,
        "receipt_hmac_sha256": mac,
    }


def build_signed_research_tool_run(
    store, *, secret: str, operation: str, passage_ids: str, query: str,
    evidence_ids: str | None = None, limit: int = 8, read_budget: int = 3,
    request_checkpoint_sha256: str,
) -> dict:
    """Execute one already-planned read-only tool and HMAC its exact output."""
    plan = plan_read_only_research_tool(
        operation=operation, passage_ids=passage_ids, query=query,
        evidence_ids=evidence_ids, limit=limit, read_budget=read_budget,
    )
    if (
        type(request_checkpoint_sha256) is not str
        or not HEX_SHA256.fullmatch(request_checkpoint_sha256)
        or not hmac.compare_digest(
            plan["request_checkpoint_sha256"], request_checkpoint_sha256
        )
    ):
        raise ValueError("Research tool run checkpoint mismatch.")
    _secure_secret(secret)  # Fail before graph reads on bad configuration.
    execution = run_read_only_research_tool(
        store, operation=operation, passage_ids=passage_ids, query=query,
        evidence_ids=evidence_ids, limit=limit, read_budget=read_budget,
        request_checkpoint_sha256=request_checkpoint_sha256,
    )
    _valid_plan(plan)
    _valid_execution(plan, execution)
    return {
        "plan": plan,
        "execution": execution,
        "signed_receipt": _signed_receipt(plan, execution, secret),
    }


def verify_signed_research_tool_run(value: object, *, secret: str) -> dict:
    """Offline verify typed plan, typed output and HMAC; never read Neo4j."""
    if type(value) is not dict or set(value) != {
        "plan", "execution", "signed_receipt",
    }:
        raise ValueError("Signed research run envelope invalid.")
    plan = _valid_plan(value["plan"])
    execution = _valid_execution(plan, value["execution"])
    supplied = value["signed_receipt"]
    if type(supplied) is not dict or set(supplied) != {
        "receipt", "receipt_sha256", "receipt_hmac_sha256",
    }:
        raise ValueError("Signed research receipt envelope invalid.")
    expected = _signed_receipt(plan, execution, secret)
    if (
        type(supplied["receipt_sha256"]) is not str
        or type(supplied["receipt_hmac_sha256"]) is not str
        or not HEX_SHA256.fullmatch(supplied["receipt_sha256"])
        or not HEX_SHA256.fullmatch(supplied["receipt_hmac_sha256"])
        or supplied["receipt"] != expected["receipt"]
        or not hmac.compare_digest(
            supplied["receipt_sha256"], expected["receipt_sha256"]
        )
        or not hmac.compare_digest(
            supplied["receipt_hmac_sha256"], expected["receipt_hmac_sha256"]
        )
    ):
        raise ValueError("Signed research tool receipt verification failed.")
    return {
        "schema_version": VERSION,
        "typed_execution_verified": True,
        "local_service_hmac_verified": True,
        "tool_operation": plan["operation"],
        "returned_card_count": execution["returned_card_count"],
        "graph_reads_during_verification": 0,
        "reviewer_identity_verified": False,
        "immutable_graph_snapshot_verified": False,
        "research_release_status": "HOLD",
    }
