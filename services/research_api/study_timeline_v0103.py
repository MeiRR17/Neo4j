"""v0.10.3 bounded offline study history over independently signed previews.

A DvirOS consumer can inspect the observed evolution of one directed Work-pair
across 2–6 private v0.10.0 packets. Every packet and every v0.10.2 per-step
audit comparison is independently recomputed. Only observed metadata is
compared; no immutable graph snapshot or trusted timestamp is claimed.
"""
from __future__ import annotations

from hashlib import sha256
import hmac

from services.research_api.audit_export_v0911 import canonical_bytes
from services.research_api.study_audit_window_v0102 import (
    compare_study_audit_windows,
)
from services.research_api.study_packets_v0100 import (
    StudyPacketError, verify_study_packet,
)

VERSION = "0.10.3"
MIN_CAPTURES = 2
MAX_CAPTURES = 6
MAX_TIMELINE_BYTES = 240_000
DOMAIN = b"dviros/research/study-observation-timeline/v0.10.3\n"
ENVELOPE_KEYS = frozenset({
    "timeline", "timeline_sha256", "timeline_hmac_sha256",
})


def _canonical(value: object) -> bytes:
    raw = canonical_bytes(value)
    if len(raw) > MAX_TIMELINE_BYTES:
        raise StudyPacketError("Study timeline exceeded private metadata budget.")
    return raw


def _mac(secret: str, digest: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        DOMAIN + digest.encode("ascii"), sha256,
    ).hexdigest()


def build_study_timeline(previews: object, *, secret: str) -> dict:
    """Create a chained, HMAC-sealed metadata-only observation history.

    Capture times are locally reported, not authenticated third-party times.
    Strictly increasing clock values establish an unambiguous *reported*
    order but are not evidence that the graph was frozen in between.
    """
    if (
        type(previews) is not list
        or not MIN_CAPTURES <= len(previews) <= MAX_CAPTURES
    ):
        raise StudyPacketError("Study timeline needs 2–6 signed previews.")

    for preview in previews:
        verify_study_packet(preview, secret=secret)

    first = previews[0]["packet"]
    source, target = first["source_work_id"], first["target_work_id"]
    snapshots = []
    previous_time = -1
    previous_packets = set()
    for index, preview in enumerate(previews):
        packet = preview["packet"]
        if (
            packet["source_work_id"] != source
            or packet["target_work_id"] != target
        ):
            raise StudyPacketError("Study timeline changed directed Work pair.")
        captured_at = packet["audit_captured_at_unix"]
        packet_digest = preview["packet_sha256"]
        if captured_at <= previous_time or packet_digest in previous_packets:
            raise StudyPacketError(
                "Study captures must have distinct ordered reported times."
            )
        previous_packets.add(packet_digest)
        previous_time = captured_at
        rows = preview["audit_export"]["manifest"]["ordered_links"]
        snapshots.append({
            "index": index,
            "captured_at_unix": captured_at,
            "packet_sha256": packet_digest,
            "audit_manifest_sha256": preview["audit_export"]["manifest_sha256"],
            "selected_citation_count": packet["citation_count"],
            "observed_window_count": len(rows),
            "observed_window_rows_sha256": sha256(canonical_bytes(rows)).hexdigest(),
        })

    root = sha256(DOMAIN + canonical_bytes({
        "source_work_id": source,
        "target_work_id": target,
        "first_packet_sha256": snapshots[0]["packet_sha256"],
    })).hexdigest()
    prior = root
    transitions = []
    changed_evidence = set()
    for index in range(len(previews) - 1):
        diff = compare_study_audit_windows(
            previews[index], previews[index + 1], secret=secret,
        )
        report = diff["report"]
        changes = report["window_changes"]
        changed_evidence.update(x["evidence_id"] for x in changes)
        step = {
            "from_index": index,
            "to_index": index + 1,
            "baseline_packet_sha256": snapshots[index]["packet_sha256"],
            "current_packet_sha256": snapshots[index + 1]["packet_sha256"],
            "audit_window_diff_sha256": diff["report_sha256"],
            "window_changes": changes,
            "window_change_count": report["window_change_count"],
            "unselected_window_change_count": report[
                "unselected_window_change_count"
            ],
            "selected_evidence_added": report["selected_evidence_added"],
            "selected_evidence_removed": report["selected_evidence_removed"],
            "audit_receipt_changed": report["audit_receipt_changed"],
            "previous_chain_sha256": prior,
        }
        chained = sha256(DOMAIN + _canonical(step)).hexdigest()
        transitions.append({**step, "chain_sha256": chained})
        prior = chained

    # Detect A -> B -> A patterns that a first/last-only comparison hides.
    # Consecutive identical metadata observations are not considered returns.
    rows_hashes = [x["observed_window_rows_sha256"] for x in snapshots]
    revisited = []
    for index in range(2, len(rows_hashes)):
        digest = rows_hashes[index]
        matching = [older for older in range(index - 1)
                    if rows_hashes[older] == digest
                    and any(x != digest for x in rows_hashes[older + 1:index])]
        if matching:
            revisited.append({
                "capture_index": index,
                "previous_matching_index": matching[-1],
            })

    timeline = {
        "schema_version": VERSION,
        "contract_kind": "dviros.research.study_observation_timeline",
        "source_work_id": source,
        "target_work_id": target,
        "capture_count": len(previews),
        "snapshots": snapshots,
        "transition_count": len(transitions),
        "transitions": transitions,
        "chain_root_sha256": root,
        "chain_tip_sha256": prior,
        "total_window_change_events": sum(
            x["window_change_count"] for x in transitions
        ),
        "unique_changed_evidence_ids": sorted(changed_evidence),
        "revisited_window_states": revisited,
        "has_observed_intermediate_drift": any(
            x["window_change_count"] for x in transitions
        ),
        "private_dviros_studies_saved": False,
        "reviewer_approval_recorded": False,
        "source_rights_verified": False,
        "immutable_corpus_revision_verified": False,
        "trusted_capture_times_verified": False,
        "research_release_status": "HOLD",
    }
    digest = sha256(_canonical(timeline)).hexdigest()
    return {
        "timeline": timeline,
        "timeline_sha256": digest,
        "timeline_hmac_sha256": _mac(secret, digest),
    }


def verify_study_timeline(
    value: object, previews: object, *, secret: str,
) -> dict:
    """Recompute every snapshot, transition and chain link offline."""
    if not isinstance(value, dict) or set(value) != ENVELOPE_KEYS:
        raise StudyPacketError("Study timeline envelope invalid.")
    expected = build_study_timeline(previews, secret=secret)
    try:
        if (
            value["timeline"] != expected["timeline"]
            or type(value["timeline_sha256"]) is not str
            or type(value["timeline_hmac_sha256"]) is not str
            or not hmac.compare_digest(
                value["timeline_sha256"], expected["timeline_sha256"]
            )
            or not hmac.compare_digest(
                value["timeline_hmac_sha256"],
                expected["timeline_hmac_sha256"],
            )
        ):
            raise StudyPacketError("Study timeline integrity failed.")
    except (ValueError, TypeError):
        raise StudyPacketError("Study timeline integrity failed.") from None
    result = expected["timeline"]
    return {
        "schema_version": VERSION,
        "capture_count": result["capture_count"],
        "transition_count": result["transition_count"],
        "total_window_change_events": result["total_window_change_events"],
        "unique_changed_evidence_count": len(
            result["unique_changed_evidence_ids"]
        ),
        "revisited_window_state_count": len(result["revisited_window_states"]),
        "all_source_previews_verified": True,
        "timeline_hmac_verified": True,
        "requires_human_review": result["has_observed_intermediate_drift"],
        "immutable_corpus_revision_verified": False,
        "research_release_status": "HOLD",
    }
