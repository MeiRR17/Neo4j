#!/usr/bin/env python3
"""v0.8.10: observe a bounded full-search metadata projection and index state.

Reads the existing signed private API; never queries arbitrary Cypher, logs
source text or approves copyright. Two equal observations are evidence of
*observed projection* stability only, not a transactionally frozen corpus.
"""
from __future__ import annotations

import hashlib
from urllib.parse import quote

from scripts.search_capture import CaptureError, check_page, digest, encode, target_for
from scripts.search_review_workflow import _query_catalog
from services.research_api.metadata_search import ALLOWED_KINDS

SCHEMA = "0.8.10"
MAX_REVISION_PAGES = 25
MAX_REVISION_HITS = 500
CAPABILITY_KEYS = frozenset({
    "schema_version", "kind", "index_version", "index_status",
    "indexed_prefix_ready", "index_coverage", "bounded_scan_supported",
    "scan_candidate_window_limit", "scan_requires_cursor_completion",
    "alias_matching_on_index", "full_text_indexed",
    "source_trail_verified", "text_available", "corpus_status",
})
STATUSES = frozenset({"ready", "missing", "not_online", "empty", "incomplete"})


def checked_capability(payload: object, kind: str, mode: str) -> dict:
    if (not isinstance(payload, dict) or set(payload) != CAPABILITY_KEYS or
        payload.get("schema_version") != "0.8.5" or payload.get("kind") != kind or
        payload.get("index_version") != "search_key_v1" or
        payload.get("index_status") not in STATUSES or
        type(payload.get("indexed_prefix_ready")) is not bool or
        payload.get("indexed_prefix_ready") != (payload.get("index_status") == "ready") or
        payload.get("bounded_scan_supported") is not True or
        payload.get("scan_candidate_window_limit") != 50 or
        payload.get("scan_requires_cursor_completion") is not True or
        payload.get("alias_matching_on_index") is not False or
        payload.get("full_text_indexed") is not False or
        payload.get("source_trail_verified") is not False or
        payload.get("text_available") is not False or
        payload.get("corpus_status") != "unreviewed_metadata_only"):
        raise CaptureError("Index capability provenance contract invalid.")
    coverage = payload["index_coverage"]
    if coverage is not None:
        if (not isinstance(coverage, dict) or set(coverage) != {
            "total", "covered", "complete"
        } or type(coverage["total"]) is not int or
            type(coverage["covered"]) is not int or
            type(coverage["complete"]) is not bool or
            not 0 <= coverage["covered"] <= coverage["total"] <= 1_000_000 or
            coverage["complete"] != (coverage["total"] > 0 and
                                    coverage["covered"] == coverage["total"])):
            raise CaptureError("Index capability coverage contract invalid.")
    if payload["index_status"] == "ready" and (
        coverage is None or not coverage["complete"]
    ):
        raise CaptureError("Ready index must have complete coverage.")
    if mode == "indexed" and not payload["indexed_prefix_ready"]:
        raise CaptureError("Indexed capture revision requires a ready physical index.")
    return {
        "schema": "0.8.5",
        "index_version": payload["index_version"],
        "index_status": payload["index_status"],
        "index_coverage": coverage,
    }


def observe_projection(catalog: dict, fetch, *, mode: str) -> dict:
    """Read all visible titles/anchors in each queried kind, plus index status.

    This is not a checksum of hidden source text, aliases, all graph edges,
    editions, reviewer decisions or on-disk transactions.
    """
    _, questions = _query_catalog(catalog)
    if mode not in ("scan", "indexed"):
        raise CaptureError("Revision observation mode invalid.")
    summaries = []
    for kind in sorted({case["kind"] for case in questions}):
        capability_target = (
            "/v1/search/metadata/indexed/capability?kind=" + quote(kind)
        )
        capability = checked_capability(fetch(capability_target), kind, mode)
        case = {"kind": kind, "query": "", "language": ""}
        cursor = ""
        previous_id = ""
        count = 0
        hasher = hashlib.sha256()
        finished = False
        for page_number in range(MAX_REVISION_PAGES):
            page = fetch(target_for(case, "scan", cursor))
            next_cursor, previous_id = check_page(
                page, case, "scan", cursor, previous_id)
            count += len(page["items"])
            if count > MAX_REVISION_HITS:
                raise CaptureError("Observed metadata exceeds pilot size.")
            # Canonical JSON frames encode ALL visible safe hit fields in
            # stable canonical-ID order without logging titles/anchors.
            for hit in page["items"]:
                raw = encode(hit)
                hasher.update(len(raw).to_bytes(4, "big"))
                hasher.update(raw)
            if page["search_complete"]:
                finished = True
                break
            if not next_cursor or (cursor and next_cursor <= cursor):
                raise CaptureError("Revision scan cursor stalled.")
            cursor = next_cursor
        if not finished:
            raise CaptureError("Revision scan hit page budget before completion.")
        summaries.append({
            "kind": kind,
            "visible_metadata_records": count,
            "visible_metadata_sha256": hasher.hexdigest(),
            "index": capability,
        })
    observed = {
        "schema_version": SCHEMA,
        "scope": "bounded_visible_metadata_search_projection_only",
        "snapshot_isolation_guaranteed": False,
        "corpus_immutable_revision_verified": False,
        "alias_edition_source_text_not_covered": True,
        "observations": summaries,
    }
    return {**observed, "observation_sha256": digest(encode(observed))}


def validate_observation(value: object, kinds: set[str], *, mode: str) -> None:
    """Offline shape and fingerprint check; the capture manifest HMAC binds it."""
    keys = {
        "schema_version", "scope", "snapshot_isolation_guaranteed",
        "corpus_immutable_revision_verified", "alias_edition_source_text_not_covered",
        "observations", "observation_sha256",
    }
    if not isinstance(value, dict) or set(value) != keys:
        raise CaptureError("Revision observation structure invalid.")
    if (value["schema_version"] != SCHEMA or
        value["scope"] != "bounded_visible_metadata_search_projection_only" or
        value["snapshot_isolation_guaranteed"] is not False or
        value["corpus_immutable_revision_verified"] is not False or
        value["alias_edition_source_text_not_covered"] is not True):
        raise CaptureError("Revision observation trust boundary invalid.")
    observations = value["observations"]
    if (not isinstance(observations, list) or
        [x.get("kind") if isinstance(x, dict) else None for x in observations]
            != sorted(kinds)):
        raise CaptureError("Revision observation kind set incomplete.")
    for obj in observations:
        if not isinstance(obj, dict) or set(obj) != {
            "kind", "visible_metadata_records", "visible_metadata_sha256", "index"
        }:
            raise CaptureError("Revision observation entry invalid.")
        n, sha = obj["visible_metadata_records"], obj["visible_metadata_sha256"]
        if type(n) is not int or not 0 <= n <= MAX_REVISION_HITS:
            raise CaptureError("Revision observation count invalid.")
        if (not isinstance(sha, str) or len(sha) != 64 or
            any(ch not in "0123456789abcdef" for ch in sha)):
            raise CaptureError("Revision observation hash invalid.")
        cap = obj["index"]
        if (not isinstance(cap, dict) or set(cap) != {
            "schema", "index_version", "index_status", "index_coverage"
        } or cap["schema"] != "0.8.5" or
            cap["index_version"] != "search_key_v1" or
            cap["index_status"] not in STATUSES):
            raise CaptureError("Revision index summary invalid.")
        if mode == "indexed" and cap["index_status"] != "ready":
            raise CaptureError("Revision index readiness regressed.")
        cov = cap["index_coverage"]
        if cov is not None:
            if (not isinstance(cov, dict) or set(cov) != {
                "total", "covered", "complete"
            } or type(cov["total"]) is not int or
                type(cov["covered"]) is not int or
                type(cov["complete"]) is not bool or
                not 0 <= cov["covered"] <= cov["total"] <= 1_000_000 or
                cov["complete"] != (cov["total"] > 0 and
                                   cov["total"] == cov["covered"])):
                raise CaptureError("Revision coverage malformed.")
        if cap["index_status"] == "ready" and (
            cov is None or not cov["complete"]
        ):
            raise CaptureError("Revision ready index lacks coverage.")
    unsigned = {key: val for key, val in value.items()
                if key != "observation_sha256"}
    if value["observation_sha256"] != digest(encode(unsigned)):
        raise CaptureError("Revision observation fingerprint mismatch.")
