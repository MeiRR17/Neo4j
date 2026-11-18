"""v0.10.4 evidence-by-evidence human review queue from signed study history.

Offline and read-only. Transforms the complete, bounded v0.10.3 study
timeline into deterministic reviewer *candidates*. A queue item is never
a reviewer decision, a source license, an influence claim or a graph write.
"""
from __future__ import annotations

from hashlib import sha256
import hmac

from services.research_api.audit_export_v0911 import canonical_bytes
from services.research_api.study_packets_v0100 import StudyPacketError
from services.research_api.study_timeline_v0103 import build_study_timeline

VERSION = "0.10.4"
DOMAIN = b"dviros/research/evidence-review-queue/v0.10.4\n"
MAX_QUEUE_BYTES = 240_000
MAX_ITEMS = 600  # At most six captures, each with <=100 observed Evidence.
ENVELOPE_KEYS = frozenset({"queue", "queue_sha256", "queue_hmac_sha256"})

SOURCE_FIELDS = frozenset({
    "source_ref", "target_ref", "evidence_source_ref", "version_id",
    "rights_tag", "source_passage_id", "target_passage_id",
})
REVIEW_FIELDS = frozenset({"edge_review_status", "evidence_review_status"})


def _bytes(obj: object) -> bytes:
    raw = canonical_bytes(obj)
    if len(raw) > MAX_QUEUE_BYTES:
        raise StudyPacketError("Evidence review queue exceeded metadata budget.")
    return raw


def _mac(secret: str, digest: str) -> str:
    # build_study_timeline authenticates all original packets and token length.
    return hmac.new(
        secret.encode("utf-8"),
        DOMAIN + digest.encode("ascii"), sha256,
    ).hexdigest()


def _revisited(states: list[str | None]) -> bool:
    """Detect an evidence-level A -> B -> A within observed row fingerprints."""
    for current in range(2, len(states)):
        for previous in range(current - 1):
            if (states[previous] == states[current]
                    and any(state != states[current]
                            for state in states[previous + 1:current])):
                return True
    return False


def build_evidence_review_queue(previews: object, *, secret: str) -> dict:
    """Produce an authenticated metadata-only review inbox, without approval.

    Includes selected-citation changes even when audit rows remain identical,
    plus unselected audit changes the v0.10.1 selected-only diff cannot see.
    """
    timeline_envelope = build_study_timeline(previews, secret=secret)
    timeline = timeline_envelope["timeline"]
    windows = [
        {row["evidence_id"]: row
         for row in p["audit_export"]["manifest"]["ordered_links"]}
        for p in previews
    ]
    selected = [
        set(p["packet"]["selected_evidence_ids"]) for p in previews
    ]
    grouped: dict[str, list[dict]] = {}

    for step in timeline["transitions"]:
        start = step["from_index"]
        end = step["to_index"]
        changed_rows = {
            row["evidence_id"]: row for row in step["window_changes"]
        }
        added_selection = set(step["selected_evidence_added"])
        removed_selection = set(step["selected_evidence_removed"])
        impacted = set(changed_rows) | added_selection | removed_selection
        for evidence_id in sorted(impacted):
            row = changed_rows.get(evidence_id)
            fields = row["changed_fields"] if row else []
            reasons = set()
            if row:
                if row["kind"] == "ADDED":
                    reasons.add("OBSERVED_WINDOW_ADDED")
                elif row["kind"] == "REMOVED":
                    reasons.add("OBSERVED_WINDOW_REMOVED")
                if REVIEW_FIELDS.intersection(fields):
                    reasons.add("REVIEW_STATUS_CHANGED")
                if SOURCE_FIELDS.intersection(fields):
                    reasons.add("SOURCE_METADATA_CHANGED")
                if (set(fields) - REVIEW_FIELDS - SOURCE_FIELDS):
                    reasons.add("OTHER_METADATA_CHANGED")
            if evidence_id in added_selection:
                reasons.add("SELECTION_ADDED")
            if evidence_id in removed_selection:
                reasons.add("SELECTION_REMOVED")

            grouped.setdefault(evidence_id, []).append({
                "from_index": start,
                "to_index": end,
                "window_change_kind": row["kind"] if row else "NONE",
                "changed_fields": fields,
                "selected_before": evidence_id in selected[start],
                "selected_after": evidence_id in selected[end],
                "observed_before": evidence_id in windows[start],
                "observed_after": evidence_id in windows[end],
                "reason_codes": sorted(reasons),
            })

    if len(grouped) > MAX_ITEMS:
        raise StudyPacketError("Too many distinct bounded review candidates.")

    items = []
    for evidence_id in sorted(grouped):
        events = grouped[evidence_id]
        states = [
            sha256(canonical_bytes(window[evidence_id])).hexdigest()
            if evidence_id in window else None
            for window in windows
        ]
        items.append({
            "evidence_id": evidence_id,
            "review_status": "PENDING_HUMAN_TRIAGE",
            "reason_codes": sorted({
                code for event in events for code in event["reason_codes"]
            }),
            "event_count": len(events),
            "events": events,
            "selected_in_initial_capture": evidence_id in selected[0],
            "selected_in_latest_capture": evidence_id in selected[-1],
            "observed_in_initial_window": evidence_id in windows[0],
            "observed_in_latest_window": evidence_id in windows[-1],
            "returned_to_prior_observed_state": _revisited(states),
            "unselected_window_drift": any(
                event["window_change_kind"] != "NONE"
                and not event["selected_before"] and not event["selected_after"]
                for event in events
            ),
            "human_approved": False,
            "source_rights_verified": False,
        })

    queue = {
        "schema_version": VERSION,
        "contract_kind": "dviros.research.evidence_review_queue",
        "source_work_id": timeline["source_work_id"],
        "target_work_id": timeline["target_work_id"],
        "capture_count": timeline["capture_count"],
        "timeline_sha256": timeline_envelope["timeline_sha256"],
        "timeline_chain_tip_sha256": timeline["chain_tip_sha256"],
        "candidate_count": len(items),
        "items": items,
        "unselected_window_candidate_count": sum(
            item["unselected_window_drift"] for item in items
        ),
        "selection_only_candidate_count": sum(
            all(event["window_change_kind"] == "NONE"
                for event in item["events"])
            for item in items
        ),
        "returned_state_candidate_count": sum(
            item["returned_to_prior_observed_state"] for item in items
        ),
        "requires_human_triage": bool(items),
        "reviewer_decisions_recorded": False,
        "dviros_workspace_authorized": False,
        "dviros_saved_study_created": False,
        "source_licenses_verified": False,
        "immutable_corpus_revision_verified": False,
        "trusted_timestamps_verified": False,
        "research_release_status": "HOLD",
    }
    digest = sha256(_bytes(queue)).hexdigest()
    return {
        "queue": queue,
        "queue_sha256": digest,
        "queue_hmac_sha256": _mac(secret, digest),
    }


def verify_evidence_review_queue(
    value: object, previews: object, *, secret: str,
) -> dict:
    """Independently rederive the candidate queue from all signed originals."""
    if not isinstance(value, dict) or set(value) != ENVELOPE_KEYS:
        raise StudyPacketError("Evidence review queue envelope invalid.")
    expected = build_evidence_review_queue(previews, secret=secret)
    try:
        if (
            value["queue"] != expected["queue"]
            or type(value["queue_sha256"]) is not str
            or type(value["queue_hmac_sha256"]) is not str
            or not hmac.compare_digest(
                value["queue_sha256"], expected["queue_sha256"]
            )
            or not hmac.compare_digest(
                value["queue_hmac_sha256"], expected["queue_hmac_sha256"]
            )
        ):
            raise StudyPacketError("Evidence review queue integrity failed.")
    except (ValueError, TypeError):
        raise StudyPacketError("Evidence review queue integrity failed.") from None
    queue = expected["queue"]
    return {
        "schema_version": VERSION,
        "all_original_previews_verified": True,
        "queue_hmac_verified": True,
        "capture_count": queue["capture_count"],
        "candidate_count": queue["candidate_count"],
        "unselected_window_candidate_count": queue[
            "unselected_window_candidate_count"
        ],
        "selection_only_candidate_count": queue[
            "selection_only_candidate_count"
        ],
        "returned_state_candidate_count": queue[
            "returned_state_candidate_count"
        ],
        "requires_human_triage": queue["requires_human_triage"],
        "reviewer_decisions_recorded": False,
        "research_release_status": "HOLD",
    }
