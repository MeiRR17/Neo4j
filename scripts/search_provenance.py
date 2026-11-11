"""v0.8.11 conservative source/edition/evidence provenance observation.

Hashes the *exposed metadata fields* of three fixed database labels. Does not
read original documents, prove provider hashes, certify rights, or freeze the
graph transactionally. Only these signed, bounded client GETs are used.
"""
from __future__ import annotations

import hashlib
from urllib.parse import quote

from research_graph.ontology import require_canonical_id
from scripts.search_capture import CaptureError, digest, encode
from services.research_api.provenance import KINDS, MAX_PAGE, safe_provenance_item

SCHEMA = "0.8.11"
MAX_PAGES = 25
MAX_ROWS = 500
KINDS_ORDER = tuple(sorted(KINDS))
PAGE_FIELDS = frozenset({
    "schema_version", "kind", "items", "has_more", "search_complete",
    "next_cursor", "rights_independently_verified", "source_bytes_verified",
    "source_text_available", "corpus_snapshot_isolation",
})
SCOPE = "bounded_observed_source_edition_evidence_metadata_only"


def target(kind: str, cursor: str = "") -> str:
    if kind not in KINDS:
        raise CaptureError("Provenance kind unsupported.")
    raw = "/v1/provenance/metadata?kind=" + kind + "&limit=" + str(MAX_PAGE)
    if cursor:
        try:
            validated = require_canonical_id(cursor)
        except (ValueError, TypeError):
            raise CaptureError("Invalid provenance page cursor.") from None
        if not validated.startswith(KINDS[kind] + ":"):
            raise CaptureError("Provenance cursor kind mismatch.")
        raw += "&cursor=" + quote(cursor, safe="")
    return raw


def checked_page(page: object, kind: str, previous: str) -> tuple[str, list[dict]]:
    if not isinstance(page, dict) or set(page) != PAGE_FIELDS:
        raise CaptureError("Provenance page structure invalid.")
    if (page["schema_version"] != SCHEMA or page["kind"] != kind or
        type(page["has_more"]) is not bool or
        type(page["search_complete"]) is not bool or
        page["has_more"] == page["search_complete"] or
        page["rights_independently_verified"] is not False or
        page["source_bytes_verified"] is not False or
        page["source_text_available"] is not False or
        page["corpus_snapshot_isolation"] is not False):
        raise CaptureError("Provenance page trust boundary invalid.")
    rows = page["items"]
    if not isinstance(rows, list) or len(rows) > MAX_PAGE:
        raise CaptureError("Provenance page exceeds fixed item budget.")
    last = previous
    safe_rows = []
    for row in rows:
        try:
            item = safe_provenance_item(row, kind)
        except (ValueError, TypeError, RuntimeError):
            raise CaptureError("Provenance item invalid or unsafe.") from None
        if last and item["id"] <= last:
            raise CaptureError("Provenance ordering/uniqueness invalid.")
        last = item["id"]
        safe_rows.append(item)
    cursor = page["next_cursor"]
    if page["has_more"]:
        if not safe_rows or cursor != last:
            raise CaptureError("Provenance next cursor does not match final item.")
    elif cursor is not None:
        raise CaptureError("Finished provenance page has a cursor.")
    return cursor or "", safe_rows


def observe_provenance(fetch) -> dict:
    entries = []
    for kind in KINDS_ORDER:
        previous = ""
        cursor = ""
        count = 0
        absent_versions = 0
        frame_hash = hashlib.sha256()
        complete = False
        for _ in range(MAX_PAGES):
            page = fetch(target(kind, cursor))
            following, safe_rows = checked_page(page, kind, previous)
            count += len(safe_rows)
            if count > MAX_ROWS:
                raise CaptureError("Provenance observation exceeds pilot bound.")
            for row in safe_rows:
                raw = encode(row)
                frame_hash.update(len(raw).to_bytes(4, "big"))
                frame_hash.update(raw)
                if ((kind == "sources" and row["checksum_sha256"] is None) or
                    (kind == "editions" and row["version_id"] is None) or
                    (kind == "evidence" and row["version_id"] is None)):
                    absent_versions += 1
            if page["search_complete"]:
                complete = True
                break
            if not following or (cursor and following <= cursor):
                raise CaptureError("Provenance page cursor stalled.")
            if not safe_rows:
                raise CaptureError("Non-terminal provenance page was empty.")
            previous = safe_rows[-1]["id"]
            cursor = following
        if not complete:
            raise CaptureError("Provenance observation incomplete at page cap.")
        entries.append({
            "kind": kind, "records": count,
            "visible_metadata_sha256": frame_hash.hexdigest(),
            "missing_checksum_or_version": absent_versions,
        })
    core = {
        "schema_version": SCHEMA,
        "scope": SCOPE,
        "observations": entries,
        "source_bytes_verified": False,
        "source_rights_verified": False,
        "graph_relationships_covered": False,
        "corpus_snapshot_isolation_guaranteed": False,
        "source_metadata_hash_is_a_provider_claim": True,
    }
    return {**core, "observation_sha256": digest(encode(core))}


def validate_provenance_observation(obj: object) -> None:
    required = {"schema_version", "scope", "observations",
                "source_bytes_verified", "source_rights_verified",
                "graph_relationships_covered", "corpus_snapshot_isolation_guaranteed",
                "source_metadata_hash_is_a_provider_claim", "observation_sha256"}
    if not isinstance(obj, dict) or set(obj) != required:
        raise CaptureError("Provenance observation envelope invalid.")
    if (obj["schema_version"] != SCHEMA or obj["scope"] != SCOPE or
        obj["source_bytes_verified"] is not False or
        obj["source_rights_verified"] is not False or
        obj["graph_relationships_covered"] is not False or
        obj["corpus_snapshot_isolation_guaranteed"] is not False or
        obj["source_metadata_hash_is_a_provider_claim"] is not True):
        raise CaptureError("Provenance observation trust status invalid.")
    entries = obj["observations"]
    if (not isinstance(entries, list) or len(entries) != len(KINDS_ORDER) or
        [x.get("kind") if isinstance(x, dict) else None for x in entries]
          != list(KINDS_ORDER)):
        raise CaptureError("Incomplete provenance observation kind set.")
    for e in entries:
        if set(e) != {"kind", "records", "visible_metadata_sha256",
                       "missing_checksum_or_version"}:
            raise CaptureError("Provenance summary fields invalid.")
        n, missing, hexdigest = (
            e["records"], e["missing_checksum_or_version"],
            e["visible_metadata_sha256"])
        if (type(n) is not int or type(missing) is not int or
            not 0 <= missing <= n <= MAX_ROWS or
            not isinstance(hexdigest, str) or len(hexdigest) != 64 or
            any(c not in "0123456789abcdef" for c in hexdigest)):
            raise CaptureError("Provenance summary count/hash invalid.")
    unsigned = {k: v for k, v in obj.items() if k != "observation_sha256"}
    if obj["observation_sha256"] != digest(encode(unsigned)):
        raise CaptureError("Provenance observation fingerprint mismatch.")
