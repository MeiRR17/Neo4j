"""v0.10.2 offline comparison of the full bounded, signed Work-pair audit.

The v0.10.1 replay reports changes in the 1–12 selected citations only.
This companion report compares ALL observed Evidence rows (at most 100)
in the two authenticated v0.9.11 audit windows already embedded in the
v0.10.0 study preview envelopes. It does not query or modify Neo4j.
"""
from __future__ import annotations

from hashlib import sha256
import hmac

from services.research_api.audit_export_v0911 import canonical_bytes
from services.research_api.study_packets_v0100 import (
    StudyPacketError, verify_study_packet,
)
from services.research_api.study_replay_v0101 import compare_study_packets
from services.research_api.work_comparison import LINK_FIELDS

VERSION = "0.10.2"
DOMAIN = b"dviros/research/study-audit-window-diff/v0.10.2\n"
MAX_REPORT_BYTES = 96_000
ENVELOPE_KEYS = frozenset({
    "report", "report_sha256", "report_hmac_sha256",
})


def _bytes(value: object) -> bytes:
    raw = canonical_bytes(value)
    if len(raw) > MAX_REPORT_BYTES:
        raise StudyPacketError("Audit window diff exceeded report budget.")
    return raw


def _seal(secret: str, digest: str) -> str:
    # Both full source packet validators check the protected secret length.
    return hmac.new(
        secret.encode("utf-8"), DOMAIN + digest.encode("ascii"), sha256,
    ).hexdigest()


def compare_study_audit_windows(
    baseline: object, current: object, *, secret: str,
) -> dict:
    """Fail closed on forged previews, scope changes or clock rollback.

    The audit is complete only within the bounded directed Work-pair
    observation; it is never proof of an immutable graph/corpus snapshot.
    """
    verify_study_packet(baseline, secret=secret)
    verify_study_packet(current, secret=secret)
    selected_comparison = compare_study_packets(
        baseline, current, secret=secret,
    )["comparison"]
    old, new = baseline["audit_export"], current["audit_export"]
    before = {
        row["evidence_id"]: row
        for row in old["manifest"]["ordered_links"]
    }
    after = {
        row["evidence_id"]: row
        for row in new["manifest"]["ordered_links"]
    }
    old_selected = set(baseline["packet"]["selected_evidence_ids"])
    new_selected = set(current["packet"]["selected_evidence_ids"])
    changes = []
    for evidence_id in sorted(before.keys() | after.keys()):
        left, right = before.get(evidence_id), after.get(evidence_id)
        if left is None:
            kind, fields = "ADDED", []
        elif right is None:
            kind, fields = "REMOVED", []
        else:
            fields = [
                field for field in sorted(LINK_FIELDS)
                if left[field] != right[field]
            ]
            if not fields:
                continue
            kind = "MODIFIED"
        changes.append({
            "evidence_id": evidence_id,
            "kind": kind,
            "changed_fields": fields,
            "selected_in_baseline": evidence_id in old_selected,
            "selected_in_current": evidence_id in new_selected,
        })

    unselected_changes = sum(
        not item["selected_in_baseline"]
        and not item["selected_in_current"] for item in changes
    )
    report = {
        "schema_version": VERSION,
        "contract_kind": "dviros.research.study_audit_window_diff",
        "source_work_id": baseline["packet"]["source_work_id"],
        "target_work_id": baseline["packet"]["target_work_id"],
        "baseline_packet_sha256": baseline["packet_sha256"],
        "current_packet_sha256": current["packet_sha256"],
        "baseline_audit_manifest_sha256": old["manifest_sha256"],
        "current_audit_manifest_sha256": new["manifest_sha256"],
        "baseline_observed_link_count": len(before),
        "current_observed_link_count": len(after),
        "baseline_selected_count": len(old_selected),
        "current_selected_count": len(new_selected),
        "selected_evidence_added": sorted(new_selected - old_selected),
        "selected_evidence_removed": sorted(old_selected - new_selected),
        "window_changes": changes,
        "window_change_count": len(changes),
        "unselected_window_change_count": unselected_changes,
        "window_metadata_changed": bool(changes),
        "selected_citation_metadata_changed": (
            selected_comparison["metadata_changed"]
        ),
        "audit_receipt_changed": (
            old["manifest_sha256"] != new["manifest_sha256"]
        ),
        "trusted_timestamp_verified": False,
        "entire_corpus_revision_verified": False,
        "immutable_graph_snapshot_verified": False,
        "source_licenses_verified": False,
        "human_review_approved": False,
        "dviros_study_saved": False,
        "research_release_status": "HOLD",
    }
    digest = sha256(_bytes(report)).hexdigest()
    return {
        "report": report,
        "report_sha256": digest,
        "report_hmac_sha256": _seal(secret, digest),
    }


def verify_study_audit_window_diff(
    value: object, baseline: object, current: object, *, secret: str,
) -> dict:
    """Recompute from both original signed packets, never trust output flags."""
    if not isinstance(value, dict) or set(value) != ENVELOPE_KEYS:
        raise StudyPacketError("Audit window diff envelope invalid.")
    expected = compare_study_audit_windows(
        baseline, current, secret=secret,
    )
    try:
        if (
            value["report"] != expected["report"]
            or type(value["report_sha256"]) is not str
            or type(value["report_hmac_sha256"]) is not str
            or not hmac.compare_digest(
                value["report_sha256"], expected["report_sha256"]
            )
            or not hmac.compare_digest(
                value["report_hmac_sha256"], expected["report_hmac_sha256"]
            )
        ):
            raise StudyPacketError("Audit window diff verification failed.")
    except (TypeError, ValueError):
        raise StudyPacketError("Audit window diff verification failed.") from None
    report = expected["report"]
    return {
        "schema_version": VERSION,
        "source_packets_verified": True,
        "window_diff_hmac_verified": True,
        "window_change_count": report["window_change_count"],
        "unselected_window_change_count": report[
            "unselected_window_change_count"
        ],
        "review_required": bool(
            report["window_metadata_changed"]
            or report["selected_evidence_added"]
            or report["selected_evidence_removed"]
        ),
        "entire_corpus_revision_verified": False,
        "human_review_approved": False,
        "research_release_status": "HOLD",
    }
