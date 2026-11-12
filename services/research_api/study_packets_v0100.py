"""v0.10.0 phase 1: bounded, HMAC-sealed research study citation packet.

Produces a *draft preview* derived from the full independently verified
v0.9.11 two-pass Work-pair observation. Its exact Evidence IDs, metadata,
review statuses and version/rights tags can be transferred to a future
DvirOS Postgres study record without turning metadata into approved claims.
Neo4j remains READ ONLY. This does not store a note or review decision.
"""
from __future__ import annotations

from hashlib import sha256
import hmac
import re

from services.research_api.audit_export_v0911 import (
    canonical_bytes, export_work_link_audit, verify_audit_export,
)
from services.research_api.work_comparison import _id

VERSION = "0.10.0"
MAX_SELECT = 12
MAX_SELECTOR_CHARS = 1800
MAX_PACKET_BYTES = 96_000
DOMAIN = b"dviros/research/study-citation-packet/v0.10.0\n"
HEX = re.compile(r"^[a-f0-9]{64}$")
CITATION_FIELDS = (
    "edge_id", "evidence_id", "source_work_id", "target_work_id",
    "source_passage_id", "target_passage_id", "source_ref", "target_ref",
    "evidence_source_ref", "version_id", "rights_tag",
    "edge_review_status", "evidence_review_status",
)
PACKET_KEYS = frozenset({
    "schema_version", "packet_id", "source_work_id", "target_work_id",
    "selected_evidence_ids", "citations", "citation_count",
    "audit_manifest_sha256", "audit_query_template_sha256",
    "audit_captured_at_unix", "annotation_slots", "annotation_write_status",
    "review_decision_status", "dviros_postgres_record_created",
    "graph_snapshot_verified", "licensed_source_rights_verified",
    "historical_influence_proven", "research_release_status",
    "note",
})
ENVELOPE_KEYS = frozenset({
    "packet", "packet_sha256", "packet_hmac_sha256", "audit_export",
})
NOTE = (
    "Draft observed-link metadata only. DvirOS Postgres must own notes, "
    "review decisions and access control. No licensing, immutable graph "
    "snapshot or independent human endorsement is proven."
)


class StudyPacketError(ValueError):
    """Fail closed on malformed or forged draft citations."""


def parse_evidence_selector(value: object) -> tuple[str, ...]:
    if (type(value) is not str or not 1 <= len(value) <= MAX_SELECTOR_CHARS
            or value.startswith(",") or value.endswith(",")
            or any(c.isspace() for c in value)):
        raise StudyPacketError("Invalid bounded evidence selection.")
    parts = value.split(",")
    if not 1 <= len(parts) <= MAX_SELECT or len(set(parts)) != len(parts):
        raise StudyPacketError("Duplicate or oversized Evidence selection.")
    try:
        ids = tuple(_id(item, "evidence", request=True) for item in parts)
    except (TypeError, ValueError):
        raise StudyPacketError("Noncanonical Evidence selector.") from None
    if tuple(sorted(ids)) != ids:
        raise StudyPacketError("Evidence IDs must be sorted for stable replay.")
    return ids


def _mac(secret: str, digest: str) -> str:
    if type(secret) is not str or not 40 <= len(secret) <= 256:
        raise StudyPacketError("Protected study packet token invalid.")
    if type(digest) is not str or HEX.fullmatch(digest) is None:
        raise StudyPacketError("Study packet digest invalid.")
    return hmac.new(
        secret.encode("utf-8"), DOMAIN + digest.encode("ascii"),
        sha256,
    ).hexdigest()


def _project(audit: dict, chosen: tuple[str, ...]) -> dict:
    manifest = audit["manifest"]
    candidates = {
        row["evidence_id"]: row
        for row in manifest["ordered_links"]
    }
    if any(item not in candidates for item in chosen):
        raise LookupError("One or more Evidence IDs absent from selected Work pair.")
    # Preserve requested (sorted) canonical IDs, not arbitrary graph order.
    rows = [{
        **{field: candidates[evidence_id][field] for field in CITATION_FIELDS},
        "claim_kind": "OBSERVED_SOURCE_LINK",
        "citation_scope": "metadata_reference_only",
        "source_rights_verified": False,
        "interpretation_human_approved": False,
    } for evidence_id in chosen]
    identity = sha256(canonical_bytes({
        "audit_manifest_sha256": audit["manifest_sha256"],
        "selected_evidence_ids": list(chosen),
    })).hexdigest()
    return {
        "schema_version": VERSION,
        "packet_id": "study-packet:" + identity,
        "source_work_id": manifest["source_work_id"],
        "target_work_id": manifest["target_work_id"],
        "selected_evidence_ids": list(chosen),
        "citations": rows,
        "citation_count": len(rows),
        "audit_manifest_sha256": audit["manifest_sha256"],
        "audit_query_template_sha256": manifest["query_template_sha256"],
        "audit_captured_at_unix": manifest["captured_at_unix"],
        "annotation_slots": [
            {"evidence_id": item, "draft_note": None,
             "state": "NOT_SAVED", "reviewer_id": None}
            for item in chosen
        ],
        "annotation_write_status": "PREVIEW_ONLY_DVIROS_OWNED",
        "review_decision_status": "NO_DECISION_RECORDED",
        "dviros_postgres_record_created": False,
        "graph_snapshot_verified": False,
        "licensed_source_rights_verified": False,
        "historical_influence_proven": False,
        "research_release_status": "HOLD",
        "note": NOTE,
    }


def _packet_bytes(packet: object) -> bytes:
    raw = canonical_bytes(packet)
    if len(raw) > MAX_PACKET_BYTES:
        raise StudyPacketError("Study packet exceeded preview size.")
    return raw


def verify_study_packet(value: object, *, secret: str) -> dict:
    """Offline replay against the complete original two-pass audit export."""
    if not isinstance(value, dict) or set(value) != ENVELOPE_KEYS:
        raise StudyPacketError("Study packet envelope projection invalid.")
    try:
        verify_audit_export(value["audit_export"], secret=secret)
        packet = value["packet"]
        if not isinstance(packet, dict) or set(packet) != PACKET_KEYS:
            raise StudyPacketError("Study packet manifest projection invalid.")
        chosen = parse_evidence_selector(
            ",".join(packet["selected_evidence_ids"]))
        expected = _project(value["audit_export"], chosen)
        if packet != expected:
            raise StudyPacketError("Evidence citation or review state drift.")
        raw = _packet_bytes(packet)
        digest = sha256(raw).hexdigest()
        supplied_digest = value["packet_sha256"]
        supplied_mac = value["packet_hmac_sha256"]
        if (type(supplied_digest) is not str or
                not HEX.fullmatch(supplied_digest) or
                type(supplied_mac) is not str or
                not HEX.fullmatch(supplied_mac) or
                not hmac.compare_digest(digest, supplied_digest) or
                not hmac.compare_digest(_mac(secret, digest), supplied_mac)):
            raise StudyPacketError("Draft study packet integrity invalid.")
    except (ValueError, TypeError, KeyError, OverflowError, LookupError):
        raise StudyPacketError("Draft study evidence verification failed.") from None
    return {
        "schema_version": VERSION,
        "packet_sha256": digest,
        "citation_count": len(chosen),
        "all_citations_present_in_signed_audit": True,
        "service_hmac_verified": True,
        "independent_source_rights_verified": False,
        "human_approval_recorded": False,
        "study_persisted_to_postgres": False,
        "graph_snapshot_verified": False,
        "research_release_status": "HOLD",
    }


def preview_study_packet(
    store, *, source_work_id: str, target_work_id: str,
    evidence_ids: str, secret: str, now: int | None = None,
) -> dict:
    # Validate both canonical Work IDs and all selected Evidence IDs
    # before touching Neo4j.
    try:
        source = _id(source_work_id, "work", request=True)
        target = _id(target_work_id, "work", request=True)
    except (ValueError, TypeError):
        raise StudyPacketError("Invalid Work scope.") from None
    if source == target:
        raise StudyPacketError("Two distinct Works required.")
    chosen = parse_evidence_selector(evidence_ids)
    _mac(secret, "0" * 64)
    audit = export_work_link_audit(
        store, source_work_id=source, target_work_id=target,
        secret=secret, now=now,
    )
    packet = _project(audit, chosen)
    digest = sha256(_packet_bytes(packet)).hexdigest()
    value = {
        "packet": packet,
        "packet_sha256": digest,
        "packet_hmac_sha256": _mac(secret, digest),
        "audit_export": audit,
    }
    verify_study_packet(value, secret=secret)
    return value
