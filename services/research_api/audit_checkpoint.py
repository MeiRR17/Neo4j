"""v0.9.10 signed one-page audit checkpoint, with bounded replay detection.

A token HMAC-binds a prior 1..20-link metadata window, direction, size,
edge keys and query-template revision to the local service token. On the
next request the *immediately preceding* window is re-read and compared
before advancing. This detects changes in that observed window only.
It cannot provide a multi-request transaction, notice all concurrent
changes, verify rights, or certify historical interpretation.
"""
from __future__ import annotations

import base64
from binascii import Error as Base64DecodeError
from hashlib import sha256
import hmac
import json
import re
import time

from services.research_api.queries import READ_OPERATIONS
from services.research_api.work_link_audit import (
    MAX_AUDIT_PAGE, audit_work_link_page,
)
from services.research_api.work_comparison import _id
from services.research_api.db import DatabaseUnavailable

VERSION = "0.9.10"
DOMAIN = b"dviros/research/audit-page-checkpoint/v0.9.10\n"
TOKEN_TTL_SECONDS = 600
MAX_TOKEN_CHARS = 1400
MAX_CANONICAL_BYTES = 50000
TOKEN_KEYS = frozenset({
    "v", "source", "target", "limit", "after", "last",
    "window_sha256", "query_sha256", "issued", "expires",
})
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_-]+$")
SAFE_HEX = re.compile(r"^[0-9a-f]{64}$")


class AuditWindowDrift(RuntimeError):
    """The previously observed bounded page no longer matches its witness."""


def _encoded(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=True, allow_nan=False,
        ).encode("ascii")
    except (ValueError, TypeError, UnicodeError):
        raise DatabaseUnavailable("Audit checkpoint canonicalization failed.") from None
    if len(encoded) > MAX_CANONICAL_BYTES:
        raise DatabaseUnavailable("Audit metadata exceeded checkpoint budget.")
    return encoded


def _fingerprint(page: dict) -> str:
    # Includes every metadata field in each included link and status counters.
    # The prior lookahead record is not part of the returned window; its
    # presence is captured by has_more and next_cursor.
    relevant = {
        "links": page["links"],
        "has_more": page["has_more"],
        "next_cursor": page["next_cursor"],
        "observed_window_denominator": page["observed_window_denominator"],
        "joint_approved_status_links": page["joint_approved_status_links"],
        "contested_status_links": page["contested_status_links"],
        "pending_status_links": page["pending_status_links"],
    }
    return sha256(_encoded(relevant)).hexdigest()


def _query_fingerprint() -> str:
    return sha256(
        READ_OPERATIONS["analysis_work_cross_link_page"].encode("utf-8")
    ).hexdigest()


def _mac(secret: str, raw: bytes) -> str:
    # Domain separation: same protected service secret may be used for bearer
    # auth but never treats a raw token as an arbitrary-message MAC.
    return hmac.new(secret.encode("utf-8"), DOMAIN + raw, sha256).hexdigest()


def _issue(secret: str, page: dict, *, after: str | None,
           issued: int) -> str | None:
    if not page["has_more"]:
        return None
    last = page["next_cursor"]
    if not isinstance(last, str):
        raise DatabaseUnavailable("Missing audit continuation key.")
    capsule = {
        "v": VERSION,
        "source": page["source_work_id"],
        "target": page["target_work_id"],
        "limit": page["requested_limit"],
        "after": after,
        "last": last,
        "window_sha256": _fingerprint(page),
        "query_sha256": _query_fingerprint(),
        "issued": issued,
        "expires": issued + TOKEN_TTL_SECONDS,
    }
    raw = _encoded(capsule)
    token = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    signed = token + "." + _mac(secret, raw)
    if len(signed) > MAX_TOKEN_CHARS:
        raise DatabaseUnavailable("Unexpected checkpoint length.")
    return signed


def _verify(token: str, *, source: str, target: str, limit: int,
            secret: str, now: int) -> dict:
    if type(token) is not str or not 100 <= len(token) <= MAX_TOKEN_CHARS:
        raise ValueError("Invalid audit checkpoint.")
    pieces = token.split(".")
    if (len(pieces) != 2 or not SAFE_TOKEN.fullmatch(pieces[0]) or
            not SAFE_HEX.fullmatch(pieces[1])):
        raise ValueError("Invalid audit checkpoint.")
    try:
        raw = base64.b64decode(
            pieces[0] + "=" * (-len(pieces[0]) % 4),
            altchars=b"-_", validate=True,
        )
        if (base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
                != pieces[0]):
            raise ValueError
        if not hmac.compare_digest(_mac(secret, raw), pieces[1]):
            raise ValueError
        value = json.loads(raw.decode("ascii"))
    except (ValueError, UnicodeError, TypeError, Base64DecodeError):
        raise ValueError("Invalid audit checkpoint.") from None
    if not isinstance(value, dict) or set(value) != TOKEN_KEYS:
        raise ValueError("Invalid audit checkpoint.")
    issued, expires = value["issued"], value["expires"]
    if (value["v"] != VERSION or value["source"] != source or
            value["target"] != target or type(value["limit"]) is not int or
            value["limit"] != limit or type(issued) is not int or
            type(expires) is not int or expires != issued + TOKEN_TTL_SECONDS or
            not issued - 30 <= now <= expires or
            value["query_sha256"] != _query_fingerprint() or
            type(value["window_sha256"]) is not str or
            not SAFE_HEX.fullmatch(value["window_sha256"])):
        raise ValueError("Audit checkpoint expired, mismatched or invalid.")
    if value["after"] is not None:
        try:
            _id(value["after"], "edge", request=True)
        except (ValueError, TypeError):
            raise ValueError("Invalid audit checkpoint.") from None
    try:
        _id(value["last"], "edge", request=True)
    except (ValueError, TypeError):
        raise ValueError("Invalid audit checkpoint.") from None
    if value["after"] is not None and value["last"] <= value["after"]:
        raise ValueError("Invalid audit checkpoint.")
    return value


def checked_audit_page(store, *, source_work_id: str,
                       target_work_id: str, limit: int = 10,
                       checkpoint: str | None = None,
                       secret: str, now: int | None = None) -> dict:
    source = _id(source_work_id, "work", request=True)
    target = _id(target_work_id, "work", request=True)
    if source == target or type(limit) is not int or not 1 <= limit <= MAX_AUDIT_PAGE:
        raise ValueError("Distinct Works and a bounded audit size required.")
    if type(secret) is not str or len(secret) < 40:
        raise ValueError("Protected audit signing secret unavailable.")
    current = int(time.time()) if now is None else now
    if type(current) is not int or current < 0:
        raise ValueError("Invalid audit checkpoint clock.")
    previous_checked = False
    after = None
    if checkpoint is not None:
        capsule = _verify(
            checkpoint, source=source, target=target,
            limit=limit, secret=secret, now=current,
        )
        after = capsule["last"]
        previous = audit_work_link_page(
            store, source_work_id=source, target_work_id=target,
            after_edge_id=capsule["after"], limit=limit,
        )
        if (not previous["has_more"] or
                previous["next_cursor"] != capsule["last"] or
                not hmac.compare_digest(
                    _fingerprint(previous), capsule["window_sha256"]
                )):
            raise AuditWindowDrift(
                "Previously observed bounded audit window changed."
            )
        previous_checked = True
    page = audit_work_link_page(
        store, source_work_id=source, target_work_id=target,
        after_edge_id=after, limit=limit,
    )
    return {
        "schema_version": VERSION,
        "page": page,
        "checkpoint_token": _issue(
            secret, page, after=after, issued=current,
        ),
        "previous_page_reverified": previous_checked,
        "drift_detection_scope": "immediately_previous_bounded_page_only",
        "snapshot_consistency_verified": False,
        "entire_audit_chain_reverified": False,
        "source_rights_verified": False,
        "historical_influence_proven": False,
        "research_release_status": "HOLD",
        "note": (
            "The preceding bounded page was re-read when resuming. "
            "Other pages, preceding rows and concurrent changes can escape "
            "detection; no transaction snapshot, corpus completeness, "
            "source rights or historical influence is verified."
        ),
    }
