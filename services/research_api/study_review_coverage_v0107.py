"""v0.10.7: complete, signed offline coverage of a private review inbox.

A review page is independently authentic, but one page cannot demonstrate
that *all* filtered candidates were delivered. This module authenticates a
continuous keyset walk from the initial cursor through the terminal page,
then signs a metadata-only coverage receipt. No human decision, license,
graph mutation or DvirOS workspace authorization is implied.
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
    FILTERS, MAX_PAGE_SIZE, verify_review_page,
)

VERSION = "0.10.7"
DOMAIN = b"dviros/research/review-inbox-coverage/v0.10.7\n"
MAX_PAGES = MAX_ITEMS  # Each non-empty page must advance at least one item.
MAX_MANIFEST_BYTES = 300_000
ENVELOPE_KEYS = frozenset({
    "manifest", "manifest_sha256", "manifest_hmac_sha256",
})


def _bytes(value: object) -> bytes:
    raw = canonical_bytes(value)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise StudyPacketError("Review coverage receipt exceeds metadata limit.")
    return raw


def _mac(secret: str, digest: str) -> str:
    # verify_evidence_review_queue validates the protected service secret.
    return hmac.new(
        secret.encode("utf-8"), DOMAIN + digest.encode("ascii"), sha256,
    ).hexdigest()


def build_review_inbox_coverage(
    queue_envelope: object, previews: object, pages: object, *,
    secret: str, reason_filter: str = "all", limit: int = 10,
) -> dict:
    """Verify an entire 1..600 page walk and seal its exact candidate coverage.

    An empty filtered view requires exactly one signed empty page. Every
    other page must consume the previous page's HMAC-bound next cursor;
    missing, duplicated, reordered and appended pages are rejected.
    """
    if (
        type(reason_filter) is not str or reason_filter not in FILTERS
        or type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE
        or type(pages) is not list or not 1 <= len(pages) <= MAX_PAGES
    ):
        raise StudyPacketError("Invalid bounded review coverage arguments.")

    verify_evidence_review_queue(queue_envelope, previews, secret=secret)
    queue = queue_envelope["queue"]
    digest = queue_envelope["queue_sha256"]

    cursor = None
    seen: set[str] = set()
    ordered: list[str] = []
    summaries = []
    filtered_count = None

    for index, envelope in enumerate(pages):
        # Full original study packets + queue + the exact expected page
        # are replayed. A forged cursor cannot reposition the scan.
        verify_review_page(
            envelope, queue_envelope, previews, secret=secret,
            reason_filter=reason_filter, limit=limit, cursor=cursor,
        )
        page = envelope["page"]
        if filtered_count is None:
            filtered_count = page["filtered_candidate_count"]
        elif filtered_count != page["filtered_candidate_count"]:
            raise StudyPacketError("Filtered review count drift.")

        ids = [item["evidence_id"] for item in page["items"]]
        if len(ids) != len(set(ids)) or any(item in seen for item in ids):
            raise StudyPacketError("Duplicate Evidence in review page walk.")
        seen.update(ids)
        ordered.extend(ids)
        summaries.append({
            "page_index": index,
            "page_sha256": envelope["page_sha256"],
            "candidate_count": len(ids),
            "evidence_ids": ids,
        })
        if page["has_more"]:
            if index == len(pages) - 1:
                raise StudyPacketError("Review page walk is incomplete.")
            if not ids or not page["next_cursor"]:
                raise StudyPacketError("Non-advancing review cursor.")
            cursor = page["next_cursor"]
        else:
            if index != len(pages) - 1 or page["next_cursor"] is not None:
                raise StudyPacketError("Pages appended after terminal review page.")
            cursor = None

    if len(ordered) != filtered_count:
        raise StudyPacketError("Review coverage count mismatch.")
    # A nonempty queue may legitimately have zero matches for this filter.
    if not ordered and len(pages) != 1:
        raise StudyPacketError("Empty review view requires one terminal page.")

    manifest = {
        "schema_version": VERSION,
        "contract_kind": "dviros.research.review_inbox_coverage",
        "source_work_id": queue["source_work_id"],
        "target_work_id": queue["target_work_id"],
        "parent_queue_sha256": digest,
        "source_packet_sha256s": [
            packet["packet_sha256"] for packet in previews
        ],
        "reason_filter": reason_filter,
        "page_limit": limit,
        "queue_candidate_count": queue["candidate_count"],
        "filtered_candidate_count": filtered_count,
        "covered_candidate_count": len(ordered),
        "page_count": len(summaries),
        "pages": summaries,
        "ordered_evidence_ids": ordered,
        "first_cursor": None,
        "terminal_cursor": None,
        "keyset_walk_complete": True,
        "dviros_workspace_authorization_verified": False,
        "human_decisions_recorded": False,
        "licensed_source_rights_verified": False,
        "immutable_graph_snapshot_verified": False,
        "research_release_status": "HOLD",
        "note": (
            "Full filtered metadata-page coverage only; no human review "
            "decision, source rights, immutable corpus or production approval."
        ),
    }
    checksum = sha256(_bytes(manifest)).hexdigest()
    return {
        "manifest": manifest,
        "manifest_sha256": checksum,
        "manifest_hmac_sha256": _mac(secret, checksum),
    }


def verify_review_inbox_coverage(
    value: object, queue_envelope: object, previews: object, pages: object, *,
    secret: str, reason_filter: str = "all", limit: int = 10,
) -> dict:
    """Independently replay every source and page; reject altered coverage."""
    if type(value) is not dict or set(value) != ENVELOPE_KEYS:
        raise StudyPacketError("Invalid review coverage envelope.")
    expected = build_review_inbox_coverage(
        queue_envelope, previews, pages, secret=secret,
        reason_filter=reason_filter, limit=limit,
    )
    try:
        if (
            value["manifest"] != expected["manifest"]
            or type(value["manifest_sha256"]) is not str
            or type(value["manifest_hmac_sha256"]) is not str
            or not hmac.compare_digest(
                value["manifest_sha256"], expected["manifest_sha256"]
            )
            or not hmac.compare_digest(
                value["manifest_hmac_sha256"],
                expected["manifest_hmac_sha256"],
            )
        ):
            raise StudyPacketError("Signed review coverage integrity failed.")
    except (TypeError, ValueError):
        raise StudyPacketError("Signed review coverage integrity failed.") from None

    return {
        "schema_version": VERSION,
        "complete_page_walk_verified": True,
        "queue_and_source_packets_verified": True,
        "manifest_hmac_verified": True,
        "covered_candidate_count": expected["manifest"][
            "covered_candidate_count"
        ],
        "page_count": expected["manifest"]["page_count"],
        "human_decisions_recorded": False,
        "research_release_status": "HOLD",
    }
