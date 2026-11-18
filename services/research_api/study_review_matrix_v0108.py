"""v0.10.8: signed six-filter reconciliation for private Evidence triage.

Consumes all six v0.10.7 coverage receipts and their original signed pages.
Recomputes every source before reconciling overlap and mutually nonexclusive
reason families. Not an endorsement, review decision or corpus snapshot.
"""
from __future__ import annotations

from hashlib import sha256
import hmac

from services.research_api.audit_export_v0911 import canonical_bytes
from services.research_api.study_packets_v0100 import StudyPacketError
from services.research_api.study_review_queue_v0104 import (
    MAX_ITEMS, verify_evidence_review_queue,
)
from services.research_api.study_review_pages_v0105 import (
    FILTERS, MAX_PAGE_SIZE,
)
from services.research_api.study_review_coverage_v0107 import (
    verify_review_inbox_coverage,
)

VERSION = "0.10.8"
DOMAIN = b"dviros/research/cross-filter-triage/v0.10.8\n"
FILTER_ORDER = (
    "all", "source_or_review", "membership", "selection",
    "other_metadata", "returned_state",
)
assert frozenset(FILTER_ORDER) == FILTERS
MAX_MATRIX_BYTES = 500_000
ENVELOPE_KEYS = frozenset({
    "matrix", "matrix_sha256", "matrix_hmac_sha256",
})


def _matches_reason(item: dict, reason_filter: str) -> bool:
    """Independent reason-family projection over the signed queue."""
    codes = set(item["reason_codes"])
    if reason_filter == "all":
        return True
    if reason_filter == "source_or_review":
        return bool(codes & {"SOURCE_METADATA_CHANGED", "REVIEW_STATUS_CHANGED"})
    if reason_filter == "membership":
        return bool(codes & {"OBSERVED_WINDOW_ADDED", "OBSERVED_WINDOW_REMOVED"})
    if reason_filter == "selection":
        return bool(codes & {"SELECTION_ADDED", "SELECTION_REMOVED"})
    if reason_filter == "other_metadata":
        return "OTHER_METADATA_CHANGED" in codes
    if reason_filter == "returned_state":
        return item["returned_to_prior_observed_state"] is True
    raise StudyPacketError("Invalid review reason family.")


def _seal_bytes(matrix: object) -> tuple[str, bytes]:
    raw = canonical_bytes(matrix)
    if len(raw) > MAX_MATRIX_BYTES:
        raise StudyPacketError("Cross-filter matrix exceeds bounded metadata size.")
    return sha256(raw).hexdigest(), raw


def _mac(secret: str, digest: str) -> str:
    # v0.10.7 verifies the same owner-protected service secret.
    return hmac.new(
        secret.encode("utf-8"),
        DOMAIN + digest.encode("ascii"), sha256,
    ).hexdigest()


def build_review_triage_matrix(
    queue_envelope: object, previews: object, coverages: object,
    pages_by_filter: object, *, secret: str, limit: int = 10,
) -> dict:
    """Reconcile every signed view and make overlapping triage reasons explicit.

    The exact six-filter set is mandatory, including zero-match views. All
    source packets, queues, each page walk and every coverage receipt are
    independently recomputed before aggregation. No filter equals approval.
    """
    if (
        type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE
        or type(coverages) is not dict
        or type(pages_by_filter) is not dict
        or set(coverages) != FILTERS
        or set(pages_by_filter) != FILTERS
    ):
        raise StudyPacketError("Six exact review filters and bounded page limit required.")

    verify_evidence_review_queue(queue_envelope, previews, secret=secret)
    queue = queue_envelope["queue"]
    candidates = queue["items"]
    if len(candidates) > MAX_ITEMS:
        raise StudyPacketError("Review matrix candidate limit exceeded.")
    indexed = {item["evidence_id"]: item for item in candidates}
    if len(indexed) != len(candidates):
        raise StudyPacketError("Duplicate canonical Evidence in review queue.")

    view_summaries = []
    memberships: dict[str, list[str]] = {
        evidence_id: [] for evidence_id in indexed
    }
    for name in FILTER_ORDER:
        # Not just an outer HMAC: replay the original queue, study captures
        # and all keyset pages through the existing complete-view verifier.
        verify_review_inbox_coverage(
            coverages[name], queue_envelope, previews, pages_by_filter[name],
            secret=secret, reason_filter=name, limit=limit,
        )
        manifest = coverages[name]["manifest"]
        ids = manifest["ordered_evidence_ids"]
        expected = {
            evidence_id for evidence_id, item in indexed.items()
            if _matches_reason(item, name)
        }
        if len(ids) != len(expected) or set(ids) != expected:
            raise StudyPacketError("Reconciled review reason-family membership drift.")
        for evidence_id in ids:
            memberships[evidence_id].append(name)
        view_summaries.append({
            "reason_filter": name,
            "coverage_sha256": coverages[name]["manifest_sha256"],
            "page_count": manifest["page_count"],
            "candidate_count": manifest["covered_candidate_count"],
            "candidate_ids_sha256": sha256(
                canonical_bytes(sorted(ids))
            ).hexdigest(),
        })

    # An explicit sorted, queryable cross-filter routing matrix for DvirOS.
    # The reason filters can overlap; counts must not be summed as disjoint.
    rows = [
        {
            "evidence_id": evidence_id,
            "reason_codes": indexed[evidence_id]["reason_codes"],
            "matched_filters": memberships[evidence_id],
            "matched_specific_filter_count": len(memberships[evidence_id]) - 1,
            "selected_in_latest_capture": indexed[evidence_id][
                "selected_in_latest_capture"
            ],
            "observed_in_latest_window": indexed[evidence_id][
                "observed_in_latest_window"
            ],
            "returned_to_prior_observed_state": indexed[evidence_id][
                "returned_to_prior_observed_state"
            ],
            "human_review_approved": False,
            "licensed_source_rights_verified": False,
        }
        for evidence_id in sorted(indexed)
    ]
    if any(not row["matched_filters"] or row["matched_filters"][0] != "all"
           for row in rows):
        raise StudyPacketError("All-candidate review filter is incomplete.")

    overlaps = sum(row["matched_specific_filter_count"] > 1 for row in rows)
    all_only = sum(row["matched_specific_filter_count"] == 0 for row in rows)
    matrix = {
        "schema_version": VERSION,
        "contract_kind": "dviros.research.signed_cross_filter_triage",
        "source_work_id": queue["source_work_id"],
        "target_work_id": queue["target_work_id"],
        "parent_queue_sha256": queue_envelope["queue_sha256"],
        "source_packet_sha256s": [
            preview["packet_sha256"] for preview in previews
        ],
        "page_limit": limit,
        "required_filters": list(FILTER_ORDER),
        "filter_summaries": view_summaries,
        "candidate_count": len(rows),
        "overlapping_specific_filter_candidate_count": overlaps,
        "no_specific_filter_candidate_count": all_only,
        "rows": rows,
        "all_six_complete_views_verified": True,
        "dviros_workspace_authorization_verified": False,
        "human_review_decisions_recorded": False,
        "licensed_source_rights_verified": False,
        "immutable_graph_snapshot_verified": False,
        "research_release_status": "HOLD",
        "note": (
            "Operational source-metadata classification only; filters may "
            "overlap. No human review, source rights or publication approval."
        ),
    }
    digest, _ = _seal_bytes(matrix)
    return {
        "matrix": matrix,
        "matrix_sha256": digest,
        "matrix_hmac_sha256": _mac(secret, digest),
    }


def verify_review_triage_matrix(
    value: object, queue_envelope: object, previews: object,
    coverages: object, pages_by_filter: object, *,
    secret: str, limit: int = 10,
) -> dict:
    """Fail closed unless each source, six views and the matrix replay exactly."""
    if type(value) is not dict or set(value) != ENVELOPE_KEYS:
        raise StudyPacketError("Signed review matrix envelope invalid.")
    expected = build_review_triage_matrix(
        queue_envelope, previews, coverages, pages_by_filter,
        secret=secret, limit=limit,
    )
    try:
        if (
            value["matrix"] != expected["matrix"]
            or type(value["matrix_sha256"]) is not str
            or type(value["matrix_hmac_sha256"]) is not str
            or not hmac.compare_digest(
                value["matrix_sha256"], expected["matrix_sha256"]
            )
            or not hmac.compare_digest(
                value["matrix_hmac_sha256"], expected["matrix_hmac_sha256"]
            )
        ):
            raise StudyPacketError("Signed review matrix replay failed.")
    except (TypeError, ValueError):
        raise StudyPacketError("Signed review matrix replay failed.") from None

    matrix = expected["matrix"]
    return {
        "schema_version": VERSION,
        "all_six_complete_views_verified": True,
        "matrix_hmac_verified": True,
        "candidate_count": matrix["candidate_count"],
        "overlapping_specific_filter_candidate_count": matrix[
            "overlapping_specific_filter_candidate_count"
        ],
        "no_specific_filter_candidate_count": matrix[
            "no_specific_filter_candidate_count"
        ],
        "human_review_decisions_recorded": False,
        "research_release_status": "HOLD",
    }
