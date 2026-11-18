"""v0.10.6 private, signed review handoff for selected queue-page Evidence.

Accepts only 1–12 sorted canonical Evidence IDs *visible on an independently
verified v0.10.5 page*. Carries metadata anchors and observed change history,
never source text, user notes, decision identities, or authorizations.
This module is offline-only and makes no Neo4j/DvirOS writes.
"""
from __future__ import annotations

from hashlib import sha256
import hmac

from services.research_api.audit_export_v0911 import canonical_bytes
from services.research_api.study_packets_v0100 import (
    CITATION_FIELDS, StudyPacketError, parse_evidence_selector,
)
from services.research_api.study_review_pages_v0105 import verify_review_page

VERSION = "0.10.6"
DOMAIN = b"dviros/research/review-handoff/v0.10.6\n"
MAX_HANDOFF_BYTES = 128_000
ENVELOPE_KEYS = frozenset({
    "handoff", "handoff_sha256", "handoff_hmac_sha256",
})
NOTE = (
    "Observed source-link metadata only; not source text, a scholarly "
    "endorsement, rights clearance, historical influence or human decision."
)


def _bytes(value: object) -> bytes:
    raw = canonical_bytes(value)
    if len(raw) > MAX_HANDOFF_BYTES:
        raise StudyPacketError("Review handoff exceeds bounded metadata size.")
    return raw


def _mac(secret: str, digest: str) -> str:
    # verify_review_page independently validates local protected token length.
    return hmac.new(
        secret.encode("utf-8"),
        DOMAIN + digest.encode("ascii"), sha256,
    ).hexdigest()


def build_review_handoff(
    page_envelope: object, queue_envelope: object, previews: object,
    *, secret: str, evidence_ids: str,
    reason_filter: str = "all", limit: int = 10,
    cursor: str | None = None,
) -> dict:
    """Produce a private handoff constrained to one exact authenticated page.

    A candidate removed from the most recent audit may still carry the
    *last previously observed* metadata reference, explicitly labelled as
    historical rather than an assertion of current graph membership.
    """
    chosen = parse_evidence_selector(evidence_ids)
    verify_review_page(
        page_envelope, queue_envelope, previews, secret=secret,
        reason_filter=reason_filter, limit=limit, cursor=cursor,
    )
    page = page_envelope["page"]
    visible = {item["evidence_id"]: item for item in page["items"]}
    if any(evidence_id not in visible for evidence_id in chosen):
        raise StudyPacketError("Handoff Evidence selection escaped signed page.")
    packet_digests = [packet["packet_sha256"] for packet in previews]
    evidence_windows = [
        {
            row["evidence_id"]: row
            for row in packet["audit_export"]["manifest"]["ordered_links"]
        }
        for packet in previews
    ]
    items = []
    for evidence_id in chosen:
        candidate = visible[evidence_id]
        last_index = next(
            (
                index for index in range(len(evidence_windows) - 1, -1, -1)
                if evidence_id in evidence_windows[index]
            ),
            None,
        )
        last_row = (
            evidence_windows[last_index][evidence_id]
            if last_index is not None else None
        )
        # Reconstruct the complete bounded history from the original signed
        # captures. Explicit null on removal prevents stale evidence from
        # being presented as a current observation.
        observation_history = [
            {
                "capture_index": index,
                "packet_sha256": packet_digests[index],
                "observed_in_audit": evidence_id in window,
                "selected_in_study": (
                    evidence_id in previews[index]["packet"][
                        "selected_evidence_ids"
                    ]
                ),
                "citation_metadata": (
                    {field: window[evidence_id][field]
                     for field in CITATION_FIELDS}
                    if evidence_id in window else None
                ),
            }
            for index, window in enumerate(evidence_windows)
        ]
        # A selection-only candidate is still present in the bounded audit;
        # this fallback handles observed removals without making up a source.
        items.append({
            "evidence_id": evidence_id,
            "queue_review_status": "PENDING_HUMAN_TRIAGE",
            "reason_codes": candidate["reason_codes"],
            "events": candidate["events"],
            "observation_history": observation_history,
            "selected_in_latest_capture": candidate[
                "selected_in_latest_capture"
            ],
            "observed_in_latest_window": candidate[
                "observed_in_latest_window"
            ],
            "last_observed_capture_index": last_index,
            "last_observed_packet_sha256": (
                packet_digests[last_index] if last_index is not None else None
            ),
            "last_observed_citation_metadata": (
                {field: last_row[field] for field in CITATION_FIELDS}
                if last_row is not None else None
            ),
            "source_metadata_is_current_observation": (
                last_index == len(previews) - 1
            ),
            "draft_reviewer_note": None,
            "reviewer_id": None,
            "review_decision": "NOT_RECORDED",
            "human_approved": False,
            "source_rights_verified": False,
        })

    identity = sha256(canonical_bytes({
        "page_sha256": page_envelope["page_sha256"],
        "selected_evidence_ids": list(chosen),
    })).hexdigest()
    handoff = {
        "schema_version": VERSION,
        "contract_kind": "dviros.research.review_handoff_draft",
        "handoff_id": "review-handoff:" + identity,
        "source_work_id": page["source_work_id"],
        "target_work_id": page["target_work_id"],
        "parent_queue_sha256": queue_envelope["queue_sha256"],
        "parent_page_sha256": page_envelope["page_sha256"],
        "reason_filter": reason_filter,
        "page_limit": limit,
        "page_after_cursor": cursor,
        "source_capture_packet_sha256s": packet_digests,
        "selected_evidence_ids": list(chosen),
        "selected_count": len(chosen),
        "items": items,
        "review_state": "DRAFT_NO_HUMAN_DECISION",
        "dviros_workspace_authorization_verified": False,
        "dviros_saved_review_created": False,
        "human_review_approved": False,
        "source_licenses_verified": False,
        "immutable_graph_snapshot_verified": False,
        "trusted_capture_times_verified": False,
        "research_release_status": "HOLD",
        "note": NOTE,
    }
    digest = sha256(_bytes(handoff)).hexdigest()
    return {
        "handoff": handoff,
        "handoff_sha256": digest,
        "handoff_hmac_sha256": _mac(secret, digest),
    }


def verify_review_handoff(
    value: object, page_envelope: object, queue_envelope: object,
    previews: object, *, secret: str, evidence_ids: str,
    reason_filter: str = "all", limit: int = 10,
    cursor: str | None = None,
) -> dict:
    """Replay exact page provenance and candidate selection from originals."""
    if not isinstance(value, dict) or set(value) != ENVELOPE_KEYS:
        raise StudyPacketError("Review handoff envelope invalid.")
    expected = build_review_handoff(
        page_envelope, queue_envelope, previews, secret=secret,
        evidence_ids=evidence_ids, reason_filter=reason_filter,
        limit=limit, cursor=cursor,
    )
    try:
        if (
            value["handoff"] != expected["handoff"]
            or type(value["handoff_sha256"]) is not str
            or type(value["handoff_hmac_sha256"]) is not str
            or not hmac.compare_digest(
                value["handoff_sha256"], expected["handoff_sha256"]
            )
            or not hmac.compare_digest(
                value["handoff_hmac_sha256"],
                expected["handoff_hmac_sha256"],
            )
        ):
            raise StudyPacketError("Review handoff integrity failed.")
    except (TypeError, ValueError):
        raise StudyPacketError("Review handoff integrity failed.") from None
    return {
        "schema_version": VERSION,
        "source_packets_queue_and_page_verified": True,
        "handoff_hmac_verified": True,
        "selected_count": len(expected["handoff"]["selected_evidence_ids"]),
        "human_decisions_recorded": False,
        "licensed_source_rights_verified": False,
        "research_release_status": "HOLD",
    }
