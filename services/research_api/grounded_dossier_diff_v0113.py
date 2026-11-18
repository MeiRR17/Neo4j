"""v0.11.3: compare two *unsigned* grounded Evidence review dossiers offline.

This makes review selection and source-reference metadata drift inspectable.
It does not query Neo4j, prove historical graph deletion, authenticate either
input, validate source licenses or record a human decision. Each input digest
is a local integrity checksum only, not a digital signature.
"""
from __future__ import annotations

from hashlib import sha256
import hmac

from pydantic import ValidationError

from services.research_api.audit_export_v0911 import canonical_bytes
from services.research_api.grounded_dossier_v0112 import (
    _digest as dossier_digest,
    parse_selected_evidence_ids,
)
from services.research_api.grounded_compare_v0111 import parse_passage_ids
from services.research_api.models import GroundedEvidenceDossierEnvelope

VERSION = "0.11.3"
MAX_COMPARISON_BYTES = 48_000
ENVELOPE_KEYS = frozenset({
    "comparison", "comparison_sha256", "comparison_digitally_signed",
})
# These are *observed metadata* fields only. No raw Passage bodies or notes.
COMPARE_FIELDS = (
    "edge_id", "source_passage_id", "target_passage_id",
    "observed_in_passage_ids", "source_ref", "version_id", "rights_tag",
    "edge_review_status", "evidence_review_status", "match_basis",
    "triage_flags", "source_metadata_complete",
)
WARNINGS = {
    "edge_id": "ANCHOR_ID_CHANGED",
    "source_passage_id": "ANCHOR_ID_CHANGED",
    "target_passage_id": "ANCHOR_ID_CHANGED",
    "source_ref": "SOURCE_REFERENCE_CHANGED",
    "version_id": "VERSION_METADATA_CHANGED",
    "rights_tag": "RIGHTS_METADATA_CHANGED",
    "edge_review_status": "REVIEW_STATUS_CHANGED",
    "evidence_review_status": "REVIEW_STATUS_CHANGED",
    "observed_in_passage_ids": "OBSERVED_FOCUS_CHANGED",
    "triage_flags": "TRIAGE_FLAGS_CHANGED",
    "source_metadata_complete": "METADATA_COMPLETENESS_CHANGED",
}


def _validate_dossier(value: object) -> dict:
    """Validate the complete v0.11.2 DTO and its SHA256, without graph reads."""
    if type(value) is not dict or set(value) != {
        "dossier", "dossier_sha256", "dossier_digitally_signed",
    }:
        raise ValueError("Grounded dossier envelope has unexpected fields.")
    try:
        normalized = GroundedEvidenceDossierEnvelope.model_validate(value)
        data = normalized.model_dump(mode="json")
    except (ValidationError, TypeError, ValueError):
        raise ValueError("Invalid bounded grounded dossier DTO.") from None
    # Reject coerced strings, implicit default fields and untrusted additions.
    if value != data or value["dossier_digitally_signed"] is not False:
        raise ValueError("Noncanonical grounded dossier envelope.")
    dossier = data["dossier"]
    ids = dossier["selected_evidence_ids"]
    scopes = dossier["passage_ids"]
    if (tuple(ids) != parse_selected_evidence_ids(",".join(ids))
            or tuple(scopes) != parse_passage_ids(",".join(scopes))
            or dossier["selection_count"] != len(ids)
            or [item["evidence_id"] for item in dossier["selected_items"]] != ids
            or [window["passage_id"] for window in dossier["observed_windows"]] != scopes):
        raise ValueError("Dossier scope, selection, or counts inconsistent.")
    for item in dossier["selected_items"]:
        observed = item["observed_in_passage_ids"]
        if (
            observed != sorted(set(observed))
            or not set(observed).issubset(scopes)
            or item["source_metadata_complete"] is not (
                item["version_id"] is not None and item["rights_tag"] is not None
            )
        ):
            raise ValueError("Dossier Evidence metadata consistency failed.")
    digest = dossier_digest(dossier)
    if not hmac.compare_digest(value["dossier_sha256"], digest):
        raise ValueError("Unsigned dossier checksum mismatch.")
    return dossier


def _sha(value: object) -> str:
    raw = canonical_bytes(value)
    if len(raw) > MAX_COMPARISON_BYTES:
        raise ValueError("Grounded dossier diff exceeded metadata budget.")
    return sha256(raw).hexdigest()


def build_grounded_dossier_diff(before: object, after: object) -> dict:
    """Describe exact selection and metadata differences for one research scope.

    'Deselected' means absent from the *later dossier*, never absent from the
    live graph. An unchanged dossier also does NOT certify the source truth.
    """
    old = _validate_dossier(before)
    new = _validate_dossier(after)
    if (
        old["passage_ids"] != new["passage_ids"]
        or old["query_sha256"] != new["query_sha256"]
        or old["selection_scope"] != new["selection_scope"]
    ):
        raise ValueError("Cannot compare different research queries or Passage scopes.")

    old_items = {x["evidence_id"]: x for x in old["selected_items"]}
    new_items = {x["evidence_id"]: x for x in new["selected_items"]}
    selected_before = set(old_items)
    selected_after = set(new_items)
    newly_selected = sorted(selected_after - selected_before)
    deselected = sorted(selected_before - selected_after)

    changes = []
    unchanged = []
    for evidence_id in sorted(selected_before & selected_after):
        prior = old_items[evidence_id]
        current = new_items[evidence_id]
        fields = [
            {"field": key, "before": prior[key], "after": current[key]}
            for key in COMPARE_FIELDS if prior[key] != current[key]
        ]
        if not fields:
            unchanged.append(evidence_id)
            continue
        warnings = sorted({
            WARNINGS[field["field"]]
            for field in fields if field["field"] in WARNINGS
        })
        changes.append({
            "evidence_id": evidence_id,
            "changed_fields": fields,
            "review_flags": warnings,
            "human_review_required": True,
        })

    # A selected Evidence appearing/disappearing is *selection* movement,
    # not proof of graph deletion or addition. Never synthesize a citation.
    report = {
        "schema_version": VERSION,
        "contract_kind": "dviros.research.unsigned_dossier_diff_draft",
        "passage_ids": old["passage_ids"],
        "query_sha256": old["query_sha256"],
        "before_dossier_sha256": before["dossier_sha256"],
        "after_dossier_sha256": after["dossier_sha256"],
        "before_selected_count": len(selected_before),
        "after_selected_count": len(selected_after),
        "newly_selected_evidence_ids": newly_selected,
        "deselected_evidence_ids": deselected,
        "changed_evidence": changes,
        "unchanged_evidence_ids": unchanged,
        "newly_selected_count": len(newly_selected),
        "deselected_count": len(deselected),
        "changed_count": len(changes),
        "unchanged_count": len(unchanged),
        "before_observed_windows": old["observed_windows"],
        "after_observed_windows": new["observed_windows"],
        "additional_matches_may_exist": (
            old["additional_matches_may_exist"]
            or new["additional_matches_may_exist"]
        ),
        "selection_change_is_graph_mutation": False,
        "all_metadata_human_review_required": True,
        "input_dossiers_authenticated": False,
        "graph_snapshot_verified": False,
        "human_approval_recorded": False,
        "source_rights_verified": False,
        "generated_claim": None,
        "research_release_status": "HOLD",
        "note": (
            "Offline diff of self-checksummed, unsigned bounded Evidence "
            "dossiers. Selection changes are not corpus changes. All source "
            "labels and observed status are unverified metadata; no rights, "
            "source text, historical authenticity or review approval."
        ),
    }
    return {
        "comparison": report,
        "comparison_sha256": _sha(report),
        "comparison_digitally_signed": False,
    }


def verify_grounded_dossier_diff(
    receipt: object, before: object, after: object,
) -> dict:
    """Rebuild from the original unsigned dossiers; never rely on a hash alone."""
    if type(receipt) is not dict or set(receipt) != ENVELOPE_KEYS:
        raise ValueError("Grounded dossier diff envelope invalid.")
    expected = build_grounded_dossier_diff(before, after)
    if (
        receipt != expected
        or type(receipt["comparison_sha256"]) is not str
        or receipt["comparison_digitally_signed"] is not False
    ):
        raise ValueError("Grounded dossier diff changed on replay.")
    comparison = expected["comparison"]
    return {
        "schema_version": VERSION,
        "offline_replay_verified": True,
        "newly_selected_count": comparison["newly_selected_count"],
        "deselected_count": comparison["deselected_count"],
        "changed_count": comparison["changed_count"],
        "unchanged_count": comparison["unchanged_count"],
        "digitally_signed": False,
        "graph_snapshot_verified": False,
        "research_release_status": "HOLD",
    }
