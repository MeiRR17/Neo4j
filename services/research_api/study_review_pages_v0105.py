"""v0.10.5 authenticated, bounded offline review-candidate pagination.

Creates deterministic *metadata-only* pages from a previously signed
v0.10.4 Evidence review queue. HMAC-bound keyset cursors cannot be reused
with a different queue, filter, or page size. This is not a DvirOS human
review endpoint and does not record user decisions.
"""
from __future__ import annotations

import base64
from hashlib import sha256
import hmac
import json
import re

from services.research_api.audit_export_v0911 import canonical_bytes
from services.research_api.study_packets_v0100 import StudyPacketError
from services.research_api.study_review_queue_v0104 import (
    verify_evidence_review_queue,
)

VERSION = "0.10.5"
DOMAIN = b"dviros/research/review-candidate-page/v0.10.5\n"
CURSOR_DOMAIN = b"dviros/research/review-candidate-keyset/v0.10.5\n"
MAX_PAGE_BYTES = 200_000
MAX_PAGE_SIZE = 20
MAX_CURSOR_CHARS = 1024
FILTERS = frozenset({
    "all", "source_or_review", "membership", "selection",
    "other_metadata", "returned_state",
})
ENVELOPE_KEYS = frozenset({"page", "page_sha256", "page_hmac_sha256"})
CURSOR_FIELDS = frozenset({
    "schema_version", "queue_sha256", "reason_filter", "page_size",
    "last_rank", "last_evidence_id",
})
HEX64 = re.compile(r"^[0-9a-f]{64}$")
TOKEN = re.compile(r"^[A-Za-z0-9_-]+\.[0-9a-f]{64}$")


def _canonical(value: object) -> bytes:
    raw = canonical_bytes(value)
    if len(raw) > MAX_PAGE_BYTES:
        raise StudyPacketError("Review page metadata exceeded size budget.")
    return raw


def _seal(secret: str, digest: str) -> str:
    return hmac.new(
        secret.encode("utf-8"), DOMAIN + digest.encode("ascii"), sha256,
    ).hexdigest()


def _rank(item: dict) -> int:
    """Stable operational display order; never a scholarly risk assessment."""
    reasons = set(item["reason_codes"])
    if reasons & {"REVIEW_STATUS_CHANGED", "SOURCE_METADATA_CHANGED"}:
        return 0
    if reasons & {"OBSERVED_WINDOW_ADDED", "OBSERVED_WINDOW_REMOVED"}:
        return 1
    if reasons & {"SELECTION_ADDED", "SELECTION_REMOVED"}:
        return 2
    if "OTHER_METADATA_CHANGED" in reasons:
        return 3
    return 4


def _matches(item: dict, reason_filter: str) -> bool:
    codes = set(item["reason_codes"])
    if reason_filter == "all":
        return True
    if reason_filter == "source_or_review":
        return bool(codes & {"REVIEW_STATUS_CHANGED", "SOURCE_METADATA_CHANGED"})
    if reason_filter == "membership":
        return bool(codes & {"OBSERVED_WINDOW_ADDED", "OBSERVED_WINDOW_REMOVED"})
    if reason_filter == "selection":
        return bool(codes & {"SELECTION_ADDED", "SELECTION_REMOVED"})
    if reason_filter == "other_metadata":
        return "OTHER_METADATA_CHANGED" in codes
    return item["returned_to_prior_observed_state"] is True


def _key(item: dict) -> tuple[int, str]:
    return (_rank(item), item["evidence_id"])


def _encode_cursor(secret: str, values: dict) -> str:
    raw = canonical_bytes(values)
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    mac = hmac.new(
        secret.encode("utf-8"), CURSOR_DOMAIN + raw, sha256,
    ).hexdigest()
    result = encoded + "." + mac
    if len(result) > MAX_CURSOR_CHARS:
        raise StudyPacketError("Review cursor length exceeded.")
    return result


def _decode_cursor(secret: str, value: object, *, queue_sha256: str,
                   reason_filter: str, page_size: int) -> tuple[int, str]:
    if (type(value) is not str or not 1 <= len(value) <= MAX_CURSOR_CHARS
            or not TOKEN.fullmatch(value)):
        raise StudyPacketError("Malformed signed review cursor.")
    encoded, supplied_mac = value.split(".")
    try:
        raw = base64.b64decode(
            encoded + "=" * (-len(encoded) % 4), altchars=b"-_",
            validate=True,
        )
        if (base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
                != encoded or len(raw) > 800):
            raise ValueError("Noncanonical cursor encoding.")
        expected_mac = hmac.new(
            secret.encode("utf-8"), CURSOR_DOMAIN + raw, sha256,
        ).hexdigest()
        if not hmac.compare_digest(supplied_mac, expected_mac):
            raise ValueError("Incorrect cursor HMAC.")
        data = json.loads(raw.decode("utf-8"))
        if (not isinstance(data, dict)
                or set(data) != CURSOR_FIELDS
                or canonical_bytes(data) != raw
                or data["schema_version"] != VERSION
                or data["queue_sha256"] != queue_sha256
                or data["reason_filter"] != reason_filter
                or type(data["page_size"]) is not int
                or data["page_size"] != page_size
                or type(data["last_rank"]) is not int
                or not 0 <= data["last_rank"] <= 4
                or type(data["last_evidence_id"]) is not str):
            raise ValueError("Cursor scope or canonical fields invalid.")
        return data["last_rank"], data["last_evidence_id"]
    except (UnicodeError, ValueError, TypeError, KeyError, OverflowError):
        raise StudyPacketError("Review cursor authentication failed.") from None


def page_review_candidates(
    queue_envelope: object, previews: object, *, secret: str,
    reason_filter: str = "all", limit: int = 10,
    cursor: str | None = None,
) -> dict:
    """Derive a stable HMAC-sealed keyset page from authentic source packets."""
    if (type(reason_filter) is not str or reason_filter not in FILTERS
            or type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE):
        raise StudyPacketError("Unsupported filter or bounded page size.")
    # Source previews, entire queue and its HMAC are rechecked before paging.
    verify_evidence_review_queue(queue_envelope, previews, secret=secret)
    q = queue_envelope["queue"]
    digest = queue_envelope["queue_sha256"]
    if type(digest) is not str or HEX64.fullmatch(digest) is None:
        raise StudyPacketError("Review queue digest malformed.")
    candidates = sorted(
        (item for item in q["items"] if _matches(item, reason_filter)),
        key=_key,
    )
    start = 0
    if cursor is not None:
        last = _decode_cursor(
            secret, cursor, queue_sha256=digest,
            reason_filter=reason_filter, page_size=limit,
        )
        matching_indices = [
            index for index, item in enumerate(candidates)
            if _key(item) == last
        ]
        if len(matching_indices) != 1:
            raise StudyPacketError("Review keyset cursor no longer in view.")
        start = matching_indices[0] + 1
        if start >= len(candidates):
            raise StudyPacketError("Review cursor points beyond end of view.")
    included = candidates[start:start + limit]
    has_more = start + len(included) < len(candidates)
    next_cursor = None
    if has_more:
        last_rank, last_evidence_id = _key(included[-1])
        next_cursor = _encode_cursor(secret, {
            "schema_version": VERSION,
            "queue_sha256": digest,
            "reason_filter": reason_filter,
            "page_size": limit,
            "last_rank": last_rank,
            "last_evidence_id": last_evidence_id,
        })
    page = {
        "schema_version": VERSION,
        "contract_kind": "dviros.research.review_candidate_page",
        "source_work_id": q["source_work_id"],
        "target_work_id": q["target_work_id"],
        "parent_queue_sha256": digest,
        "reason_filter": reason_filter,
        "requested_limit": limit,
        "after_cursor": cursor,
        "total_queue_candidate_count": q["candidate_count"],
        "filtered_candidate_count": len(candidates),
        "page_candidate_count": len(included),
        "items": included,
        "has_more": has_more,
        "next_cursor": next_cursor,
        "display_order": "operational_reason_family_then_canonical_evidence_id",
        "item_approval_implemented": False,
        "dviros_user_authorization_verified": False,
        "licensed_source_rights_verified": False,
        "research_release_status": "HOLD",
    }
    body_sha = sha256(_canonical(page)).hexdigest()
    return {
        "page": page,
        "page_sha256": body_sha,
        "page_hmac_sha256": _seal(secret, body_sha),
    }


def verify_review_page(
    receipt: object, queue_envelope: object, previews: object,
    *, secret: str, reason_filter: str = "all",
    limit: int = 10, cursor: str | None = None,
) -> dict:
    """Recompute exact source queue, cursor, page order and HMAC offline."""
    if not isinstance(receipt, dict) or set(receipt) != ENVELOPE_KEYS:
        raise StudyPacketError("Review page receipt envelope invalid.")
    expected = page_review_candidates(
        queue_envelope, previews, secret=secret,
        reason_filter=reason_filter, limit=limit, cursor=cursor,
    )
    try:
        if (receipt["page"] != expected["page"]
                or type(receipt["page_sha256"]) is not str
                or type(receipt["page_hmac_sha256"]) is not str
                or not hmac.compare_digest(
                    receipt["page_sha256"], expected["page_sha256"]
                )
                or not hmac.compare_digest(
                    receipt["page_hmac_sha256"],
                    expected["page_hmac_sha256"],
                )):
            raise StudyPacketError("Review page replay integrity failed.")
    except (ValueError, TypeError):
        raise StudyPacketError("Review page replay integrity failed.") from None
    return {
        "schema_version": VERSION,
        "source_queue_and_packets_verified": True,
        "page_hmac_verified": True,
        "page_candidate_count": expected["page"]["page_candidate_count"],
        "has_more": expected["page"]["has_more"],
        "reviewer_decisions_recorded": False,
        "research_release_status": "HOLD",
    }
