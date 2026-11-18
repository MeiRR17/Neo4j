"""v0.10.1 offline comparison of independently sealed Neo study previews.

This detects citation/edition/review metadata changes before DvirOS elects
to reopen a saved study. No database writes, authorization decisions,
source-rights grants, or immutable corpus claims are made here.
"""
from __future__ import annotations

from hashlib import sha256
import hmac

from services.research_api.audit_export_v0911 import canonical_bytes
from services.research_api.study_packets_v0100 import (
    CITATION_FIELDS, StudyPacketError, verify_study_packet,
)

VERSION = "0.10.1"
DOMAIN = b"dviros/research/study-packet-replay-diff/v0.10.1\\n"
MAX_COMPARISON_BYTES = 24_000
ENVELOPE_KEYS = frozenset({
    "comparison", "comparison_sha256", "comparison_hmac_sha256",
})
# Review status and edition/reference fields are compared independently,
# never converted to inferred approval, influence, or licensing.
ROW_FIELDS = CITATION_FIELDS + ("claim_kind", "citation_scope")


def _comparison_bytes(value: object) -> bytes:
    raw = canonical_bytes(value)
    if len(raw) > MAX_COMPARISON_BYTES:
        raise StudyPacketError("Study comparison exceeded metadata budget.")
    return raw


def _comparison_mac(secret: str, digest: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        DOMAIN + digest.encode("ascii"), sha256,
    ).hexdigest()


def compare_study_packets(
    baseline: object, current: object, *, secret: str,
) -> dict:
    """Compare two authentic private preview envelopes with the same Work pair.

    A changed observation is not proof that the graph was snapshotted. The
    result is an integrity-sealed review aid, not a persisted user decision.
    """
    verify_study_packet(baseline, secret=secret)
    verify_study_packet(current, secret=secret)
    old, new = baseline["packet"], current["packet"]
    if (
        old["source_work_id"] != new["source_work_id"]
        or old["target_work_id"] != new["target_work_id"]
    ):
        raise StudyPacketError("Study replay Work scope changed.")
    if new["audit_captured_at_unix"] < old["audit_captured_at_unix"]:
        raise StudyPacketError("Study replay observation time went backwards.")

    before = {row["evidence_id"]: row for row in old["citations"]}
    after = {row["evidence_id"]: row for row in new["citations"]}
    changes = []
    for evidence_id in sorted(before.keys() | after.keys()):
        left, right = before.get(evidence_id), after.get(evidence_id)
        if left is None:
            changes.append({
                "evidence_id": evidence_id, "kind": "ADDED",
                "changed_fields": [],
            })
        elif right is None:
            changes.append({
                "evidence_id": evidence_id, "kind": "REMOVED",
                "changed_fields": [],
            })
        else:
            fields = [field for field in ROW_FIELDS
                      if left[field] != right[field]]
            if fields:
                changes.append({
                    "evidence_id": evidence_id, "kind": "MODIFIED",
                    "changed_fields": fields,
                })

    report = {
        "schema_version": VERSION,
        "contract_kind": "dviros.research.study_packet_replay_diff",
        "source_work_id": old["source_work_id"],
        "target_work_id": old["target_work_id"],
        "baseline_packet_id": old["packet_id"],
        "current_packet_id": new["packet_id"],
        "baseline_packet_sha256": baseline["packet_sha256"],
        "current_packet_sha256": current["packet_sha256"],
        "baseline_audit_manifest_sha256": old["audit_manifest_sha256"],
        "current_audit_manifest_sha256": new["audit_manifest_sha256"],
        "baseline_captured_at_unix": old["audit_captured_at_unix"],
        "current_captured_at_unix": new["audit_captured_at_unix"],
        "baseline_evidence_count": len(before),
        "current_evidence_count": len(after),
        "changes": changes,
        "metadata_changed": bool(changes),
        "audit_receipt_changed": (
            old["audit_manifest_sha256"] != new["audit_manifest_sha256"]
        ),
        "dviros_authorization_verified": False,
        "dviros_study_persisted": False,
        "human_review_decision_recorded": False,
        "licensed_source_rights_verified": False,
        "immutable_graph_snapshot_verified": False,
        "research_release_status": "HOLD",
    }
    digest = sha256(_comparison_bytes(report)).hexdigest()
    return {
        "comparison": report,
        "comparison_sha256": digest,
        "comparison_hmac_sha256": _comparison_mac(secret, digest),
    }


def verify_study_comparison(
    value: object, baseline: object, current: object, *, secret: str,
) -> dict:
    """Offline verification of source previews and exact expected diff."""
    if not isinstance(value, dict) or set(value) != ENVELOPE_KEYS:
        raise StudyPacketError("Study comparison envelope invalid.")
    expected = compare_study_packets(baseline, current, secret=secret)
    try:
        if (
            value["comparison"] != expected["comparison"]
            or type(value["comparison_sha256"]) is not str
            or type(value["comparison_hmac_sha256"]) is not str
            or not hmac.compare_digest(
                value["comparison_sha256"], expected["comparison_sha256"]
            )
            or not hmac.compare_digest(
                value["comparison_hmac_sha256"],
                expected["comparison_hmac_sha256"],
            )
        ):
            raise StudyPacketError("Study comparison integrity failed.")
    except (TypeError, ValueError):
        raise StudyPacketError("Study comparison integrity failed.") from None
    return {
        "schema_version": VERSION,
        "source_packets_verified": True,
        "comparison_hmac_verified": True,
        "changed_citation_count": len(expected["comparison"]["changes"]),
        "review_required": expected["comparison"]["metadata_changed"],
        "dviros_study_persisted": False,
        "human_review_decision_recorded": False,
        "research_release_status": "HOLD",
    }
