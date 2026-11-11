"""v0.9.11 bounded, two-pass Work link observation and HMAC-sealed export.

Only existing registered read-only metadata queries are used. Two matching
sequential traversals detect observable intervening mutations, but do NOT
establish a Neo4j transaction snapshot, immutable corpus, independent
source authenticity, verified copyright, or complete scholarly review.
"""
from __future__ import annotations

from hashlib import sha256
import hmac
import json
import re
import time

from research_graph.ontology import REVIEW_STATUSES
from services.research_api.db import DatabaseUnavailable
from services.research_api.queries import READ_OPERATIONS
from services.research_api.work_comparison import _id, _text, LINK_FIELDS
from services.research_api.work_link_audit import audit_work_link_page
from services.research_api.audit_checkpoint import AuditWindowDrift

VERSION = "0.9.11"
PAGE_SIZE = 20
MAX_PAGES = 5
MAX_LINKS = PAGE_SIZE * MAX_PAGES
MAX_BYTES = 250_000
DOMAIN = b"dviros/research/two-pass-audit-export/v0.9.11\n"
HEX = re.compile(r"^[0-9a-f]{64}$")
MANIFEST_KEYS = frozenset({
    "schema_version", "source_work_id", "target_work_id",
    "ordered_links", "observed_link_count", "pages_per_pass",
    "query_template_sha256", "captured_at_unix",
    "observation_scope", "sequential_passes_matched",
    "graph_snapshot_verified", "corpus_revision_immutable",
    "independently_licensed_sources_verified",
    "historical_influence_proven", "research_release_status",
    "note",
})
ENVELOPE_KEYS = frozenset({
    "manifest", "manifest_sha256", "receipt_hmac_sha256",
})


def canonical_bytes(value: object) -> bytes:
    try:
        data = json.dumps(
            value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise ValueError("Invalid audit export encoding.") from None
    if len(data) > MAX_BYTES:
        raise ValueError("Audit export exceeded canonical byte budget.")
    return data


def _template_sha256() -> str:
    names = ("analysis_work_cross_link_page", "analysis_work_descriptor")
    templates = {name: READ_OPERATIONS[name] for name in names}
    return sha256(canonical_bytes(templates)).hexdigest()


def _sign(secret: str, manifest_hash: str) -> str:
    if type(secret) is not str or not 40 <= len(secret) <= 256:
        raise ValueError("Protected export secret is invalid.")
    # Domain-separated service HMAC. This authenticates knowledge of the
    # local key, not a third-party or independent scholarly signature.
    return hmac.new(
        secret.encode("utf-8"), DOMAIN + manifest_hash.encode("ascii"),
        sha256,
    ).hexdigest()


def _walk(store, source: str, target: str) -> tuple[list[dict], int]:
    cursor = None
    previous_edge = ""
    seen_evidence = set()
    gathered: list[dict] = []
    for page_number in range(1, MAX_PAGES + 1):
        page = audit_work_link_page(
            store, source_work_id=source, target_work_id=target,
            after_edge_id=cursor, limit=PAGE_SIZE,
        )
        links = page["links"]
        if (page["source_work_id"] != source or
                page["target_work_id"] != target or
                page["requested_limit"] != PAGE_SIZE or
                page["observed_window_denominator"] != len(links) or
                not isinstance(links, list) or len(links) > PAGE_SIZE):
            raise DatabaseUnavailable("Audit export page shape invalid.")
        for row in links:
            edge_id = row["edge_id"]
            evidence_id = row["evidence_id"]
            if (edge_id <= previous_edge or evidence_id in seen_evidence or
                    len(gathered) >= MAX_LINKS):
                raise DatabaseUnavailable("Audit export crossed identity bound.")
            previous_edge = edge_id
            seen_evidence.add(evidence_id)
            gathered.append(row)
        if not page["has_more"]:
            if page["next_cursor"] is not None:
                raise DatabaseUnavailable("Exhausted audit has a cursor.")
            return gathered, page_number
        if (page_number == MAX_PAGES or not links or
                page["next_cursor"] != links[-1]["edge_id"]):
            raise DatabaseUnavailable(
                "Audit export exceeded bounded five-page capacity."
            )
        cursor = page["next_cursor"]
    raise DatabaseUnavailable("Audit export exceeded bounded page count.")


def _validate_manifest(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != MANIFEST_KEYS:
        raise ValueError("Audit export manifest fields invalid.")
    if (value["schema_version"] != VERSION or
            value["observation_scope"] != "two_sequential_bounded_reads_only" or
            value["sequential_passes_matched"] is not True or
            value["graph_snapshot_verified"] is not False or
            value["corpus_revision_immutable"] is not False or
            value["independently_licensed_sources_verified"] is not False or
            value["historical_influence_proven"] is not False or
            value["research_release_status"] != "HOLD" or
            value["query_template_sha256"] != _template_sha256()):
        raise ValueError("Audit export overstates verification.")
    source = _id(value["source_work_id"], "work", request=True)
    target = _id(value["target_work_id"], "work", request=True)
    if source == target:
        raise ValueError("Audit export requires two distinct Works.")
    rows = value["ordered_links"]
    pages = value["pages_per_pass"]
    count = value["observed_link_count"]
    timestamp = value["captured_at_unix"]
    if (not isinstance(rows, list) or len(rows) > MAX_LINKS or
            type(count) is not int or count != len(rows) or
            type(pages) is not int or not 1 <= pages <= MAX_PAGES or
            type(timestamp) is not int or not 0 <= timestamp <= 4_102_444_800 or
            type(value["note"]) is not str or
            len(value["note"]) > 500):
        raise ValueError("Audit export counts, clock or size invalid.")
    if count > pages * PAGE_SIZE or count <= (pages - 1) * PAGE_SIZE:
        raise ValueError("Audit export page boundary invalid.")
    previous_edge = ""
    seen_evidence = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != LINK_FIELDS:
            raise ValueError("Audit export link projection invalid.")
        if (_id(row["source_work_id"], "work") != source or
                _id(row["target_work_id"], "work") != target or
                _id(row["source_passage_id"], "passage") ==
                    _id(row["target_passage_id"], "passage")):
            raise ValueError("Audit export link Work ownership invalid.")
        edge = _id(row["edge_id"], "edge")
        evidence = _id(row["evidence_id"], "evidence")
        if edge <= previous_edge or evidence in seen_evidence:
            raise ValueError("Audit export link ordering invalid.")
        previous_edge = edge
        seen_evidence.add(evidence)
        for status in ("edge_review_status", "evidence_review_status"):
            if type(row[status]) is not str or row[status] not in REVIEW_STATUSES:
                raise ValueError("Audit export review status invalid.")
        for key, maximum, required in (
            ("source_ref", 512, True), ("target_ref", 512, True),
            ("evidence_source_ref", 512, False),
            ("version_id", 256, False), ("rights_tag", 128, False),
        ):
            _text(row[key], maximum, required=required)
    return value


def verify_audit_export(export: object, *, secret: str) -> dict:
    """Verify integrity without querying Neo4j; does NOT verify source truth."""
    if not isinstance(export, dict) or set(export) != ENVELOPE_KEYS:
        raise ValueError("Invalid audit export envelope.")
    manifest = export["manifest"]
    raw = canonical_bytes(manifest)
    digest = sha256(raw).hexdigest()
    given_hash = export["manifest_sha256"]
    provided = export["receipt_hmac_sha256"]
    if (type(given_hash) is not str or not HEX.fullmatch(given_hash) or
            type(provided) is not str or not HEX.fullmatch(provided) or
            not hmac.compare_digest(digest, given_hash) or
            not hmac.compare_digest(_sign(secret, digest), provided)):
        raise ValueError("Audit export checksum or HMAC mismatch.")
    _validate_manifest(manifest)
    return {
        "schema_version": VERSION,
        "manifest_sha256": digest,
        "hmac_verified_with_local_service_secret": True,
        "observed_link_count": len(manifest["ordered_links"]),
        "two_observations_reported_equal": True,
        "graph_snapshot_verified": False,
        "corpus_revision_immutable": False,
        "source_rights_verified": False,
        "research_release_status": "HOLD",
    }


def export_work_link_audit(store, *, source_work_id: str,
                           target_work_id: str, secret: str,
                           now: int | None = None) -> dict:
    source = _id(source_work_id, "work", request=True)
    target = _id(target_work_id, "work", request=True)
    if source == target:
        raise ValueError("Distinct Works required.")
    # Reject configuration failures *before* reading the graph.
    _sign(secret, "0" * 64)
    captured = int(time.time()) if now is None else now
    if type(captured) is not int or not 0 <= captured <= 4_102_444_800:
        raise ValueError("Invalid export capture clock.")
    initial, first_pages = _walk(store, source, target)
    repeat, second_pages = _walk(store, source, target)
    if (first_pages != second_pages or
            not hmac.compare_digest(
                sha256(canonical_bytes(initial)).digest(),
                sha256(canonical_bytes(repeat)).digest(),
            )):
        raise AuditWindowDrift("Two bounded audit observations diverged.")
    manifest = {
        "schema_version": VERSION,
        "source_work_id": source,
        "target_work_id": target,
        "ordered_links": initial,
        "observed_link_count": len(initial),
        "pages_per_pass": first_pages,
        "query_template_sha256": _template_sha256(),
        "captured_at_unix": captured,
        "observation_scope": "two_sequential_bounded_reads_only",
        "sequential_passes_matched": True,
        "graph_snapshot_verified": False,
        "corpus_revision_immutable": False,
        "independently_licensed_sources_verified": False,
        "historical_influence_proven": False,
        "research_release_status": "HOLD",
        "note": (
            "Two bounded read traversals produced identical metadata; "
            "this is not a transaction snapshot, immutable graph revision, "
            "source license, or scholarly provenance approval."
        ),
    }
    _validate_manifest(manifest)
    digest = sha256(canonical_bytes(manifest)).hexdigest()
    envelope = {
        "manifest": manifest, "manifest_sha256": digest,
        "receipt_hmac_sha256": _sign(secret, digest),
    }
    # Independent parser validates exactly what clients will receive.
    verify_audit_export(envelope, secret=secret)
    return envelope
