"""v0.10.9: select Evidence across multiple signed inbox pages for review.

The v0.10.6 handoff is intentionally page-scoped. This module creates one
metadata-only review bundle from 1–12 canonical Evidence IDs on *different*
v0.10.5 pages after independently verifying all six v0.10.8 triage views.
It carries original per-page v0.10.6 handoff proofs, including historical
source observations; no graph writes, user approvals or licensing decisions.
"""
from __future__ import annotations

from hashlib import sha256
import hmac

from services.research_api.audit_export_v0911 import canonical_bytes
from services.research_api.study_packets_v0100 import (
    StudyPacketError, parse_evidence_selector,
)
from services.research_api.study_review_handoff_v0106 import (
    build_review_handoff,
)
from services.research_api.study_review_matrix_v0108 import (
    verify_review_triage_matrix,
)

VERSION = "0.10.9"
DOMAIN = b"dviros/research/cross-page-handoff/v0.10.9\n"
MAX_BUNDLE_BYTES = 240_000
ENVELOPE_KEYS = frozenset({
    "bundle", "bundle_sha256", "bundle_hmac_sha256",
})


def _seal(secret: str, bundle: object) -> tuple[str, str]:
    raw = canonical_bytes(bundle)
    if len(raw) > MAX_BUNDLE_BYTES:
        raise StudyPacketError("Cross-page handoff exceeds metadata budget.")
    digest = sha256(raw).hexdigest()
    mac = hmac.new(
        secret.encode("utf-8"), DOMAIN + digest.encode("ascii"), sha256,
    ).hexdigest()
    return digest, mac


def build_cross_page_review_bundle(
    matrix_envelope: object, queue_envelope: object, previews: object,
    coverages: object, pages_by_filter: object, *,
    secret: str, evidence_ids: str, limit: int = 10,
) -> dict:
    """Produce an offline draft using the complete, signed six-filter inbox.

    Selection may span any number of all-filter pages but includes at most
    12 Evidence IDs. Every selected Evidence must belong to the exact
    authenticated matrix; every page-scoped handoff is re-derived from its
    original signed page and all study source packets.
    """
    chosen = parse_evidence_selector(evidence_ids)
    verify_review_triage_matrix(
        matrix_envelope, queue_envelope, previews, coverages, pages_by_filter,
        secret=secret, limit=limit,
    )
    matrix = matrix_envelope["matrix"]
    rows = {row["evidence_id"]: row for row in matrix["rows"]}
    if any(evidence_id not in rows for evidence_id in chosen):
        raise StudyPacketError("Selected Evidence absent from signed triage matrix.")

    all_pages = pages_by_filter["all"]
    selected = set(chosen)
    found: set[str] = set()
    handoffs = []
    lookup: dict[str, dict] = {}

    for index, page in enumerate(all_pages):
        on_page = sorted(
            row["evidence_id"] for row in page["page"]["items"]
            if row["evidence_id"] in selected
        )
        if not on_page:
            continue
        if any(evidence_id in found for evidence_id in on_page):
            raise StudyPacketError("Cross-page Evidence selection duplicated.")
        found.update(on_page)
        cursor = page["page"]["after_cursor"]
        handoff = build_review_handoff(
            page, queue_envelope, previews, secret=secret,
            evidence_ids=",".join(on_page), reason_filter="all",
            limit=limit, cursor=cursor,
        )
        for evidence_id in on_page:
            lookup[evidence_id] = {
                "page_index": index,
                "page_sha256": page["page_sha256"],
                "handoff_sha256": handoff["handoff_sha256"],
            }
        handoffs.append({
            "page_index": index,
            "page_sha256": page["page_sha256"],
            "selected_evidence_ids": on_page,
            "handoff": handoff,
        })

    if found != selected:
        raise StudyPacketError("Selection not covered by signed all-filter pages.")

    selected_rows = []
    for evidence_id in chosen:
        row = rows[evidence_id]
        selected_rows.append({
            "evidence_id": evidence_id,
            "reason_codes": row["reason_codes"],
            "matched_filters": row["matched_filters"],
            "selected_in_latest_capture": row[
                "selected_in_latest_capture"
            ],
            "observed_in_latest_window": row[
                "observed_in_latest_window"
            ],
            "page_index": lookup[evidence_id]["page_index"],
            "page_sha256": lookup[evidence_id]["page_sha256"],
            "handoff_sha256": lookup[evidence_id]["handoff_sha256"],
            "review_decision": "NOT_RECORDED",
            "human_approved": False,
            "source_rights_verified": False,
        })

    bundle_id = sha256(canonical_bytes({
        "matrix_sha256": matrix_envelope["matrix_sha256"],
        "selected_evidence_ids": list(chosen),
    })).hexdigest()

    bundle = {
        "schema_version": VERSION,
        "contract_kind": "dviros.research.cross_page_review_draft",
        "bundle_id": "cross-page-review:" + bundle_id,
        "source_work_id": matrix["source_work_id"],
        "target_work_id": matrix["target_work_id"],
        "parent_queue_sha256": matrix["parent_queue_sha256"],
        "parent_matrix_sha256": matrix_envelope["matrix_sha256"],
        "all_filter_coverage_sha256": coverages["all"]["manifest_sha256"],
        "source_packet_sha256s": matrix["source_packet_sha256s"],
        "page_limit": limit,
        "selected_evidence_ids": list(chosen),
        "selected_count": len(chosen),
        "source_page_count": len(handoffs),
        "selected_rows": selected_rows,
        # Complete original authenticated handoff envelopes preserve the
        # exact observed-vs-selected per-capture metadata without invention.
        "page_handoffs": handoffs,
        "review_state": "DRAFT_NO_HUMAN_DECISION",
        "dviros_workspace_authorization_verified": False,
        "dviros_saved_review_created": False,
        "human_review_approved": False,
        "source_licenses_verified": False,
        "immutable_graph_snapshot_verified": False,
        "trusted_capture_times_verified": False,
        "research_release_status": "HOLD",
        "note": (
            "Metadata-only draft for authorized human triage. Source links "
            "may be historical, never automatically approved or licensed."
        ),
    }
    digest, mac = _seal(secret, bundle)
    return {
        "bundle": bundle,
        "bundle_sha256": digest,
        "bundle_hmac_sha256": mac,
    }


def verify_cross_page_review_bundle(
    value: object, matrix_envelope: object, queue_envelope: object,
    previews: object, coverages: object, pages_by_filter: object, *,
    secret: str, evidence_ids: str, limit: int = 10,
) -> dict:
    """Independent exact-source replay and immutable receipt comparison."""
    if type(value) is not dict or set(value) != ENVELOPE_KEYS:
        raise StudyPacketError("Cross-page review bundle envelope malformed.")
    expected = build_cross_page_review_bundle(
        matrix_envelope, queue_envelope, previews, coverages, pages_by_filter,
        secret=secret, evidence_ids=evidence_ids, limit=limit,
    )
    try:
        if (
            value["bundle"] != expected["bundle"]
            or type(value["bundle_sha256"]) is not str
            or type(value["bundle_hmac_sha256"]) is not str
            or not hmac.compare_digest(
                value["bundle_sha256"], expected["bundle_sha256"]
            )
            or not hmac.compare_digest(
                value["bundle_hmac_sha256"], expected["bundle_hmac_sha256"]
            )
        ):
            raise StudyPacketError("Cross-page review replay integrity failed.")
    except (TypeError, ValueError):
        raise StudyPacketError("Cross-page review replay integrity failed.") from None

    result = expected["bundle"]
    return {
        "schema_version": VERSION,
        "six_filter_matrix_verified": True,
        "all_selected_page_handoffs_verified": True,
        "bundle_hmac_verified": True,
        "selected_count": result["selected_count"],
        "source_page_count": result["source_page_count"],
        "human_decisions_recorded": False,
        "research_release_status": "HOLD",
    }
