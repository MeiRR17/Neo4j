#!/usr/bin/env python3
"""v0.8.9 signed, bounded, localhost-only metadata search capture.

Each request is an exact DvirOS bearer/HMAC GET using a new nonce. Frozen
metadata-only responses and their cursor/request trace are written privately.
No read can change the Neo4j graph; no search relevance is inferred.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sys
import time
from urllib import error, parse, request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.search_quality_eval import (
    MAX_BYTES, QualityEvidenceError, SCHEMA as SNAPSHOT_SCHEMA,
    evaluate_pages, read_evidence,
)
from scripts.search_review_workflow import (
    _query_catalog, _write_private,
)
from services.research_api.config import api_token_path, load_token
from services.research_api.metadata_search import ALLOWED_KINDS, safe_id
from services.research_api.signature import (
    CLIENT_ID, sign_request, signature_key_path,
)
from scripts.smoke import NoRedirect

SCHEMA = "0.8.9"
MAX_PAGE_BYTES = 64000
MAX_REQUESTS = 150
MAX_PAGES_PER_QUERY = 12
MAX_HITS_PER_QUERY = 200
PAGE_LIMIT = 20
REQUEST_TIMEOUT = 8
HMAC_DOMAIN = b"neo4j-search-capture-v0.8.9\n"
HIT_KEYS = frozenset({
    "id", "kind", "title", "source_anchor", "match_basis", "review_status",
    "source_verification", "rights_status", "text_available",
})
PAGE_KEYS = {
    "0.8.2": frozenset({
        "schema_version", "kind", "items", "next_cursor", "has_more",
        "search_complete", "scanned_candidates", "candidate_window_limit",
        "corpus_status", "match_order", "normalization", "text_available",
        "source_trail_verified", "full_text_indexed",
    }),
    "0.8.3": frozenset({
        "schema_version", "kind", "items", "next_cursor", "has_more",
        "search_complete", "match_order", "index_version", "index_coverage",
        "alias_matching_available", "full_text_indexed",
        "source_trail_verified", "text_available", "corpus_status",
    }),
}


class CaptureError(ValueError):
    """Never forward private request, result or credential details."""


def encode(obj: object) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True,
                       indent=2) + "\n").encode("utf-8")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def target_for(case: dict, mode: str, cursor: str) -> str:
    if mode not in ("scan", "indexed") or case["kind"] not in ALLOWED_KINDS:
        raise CaptureError("Unsupported search capture mode or kind.")
    path = ("/v1/search/metadata" if mode == "scan"
            else "/v1/search/metadata/indexed")
    params = [
        ("kind", case["kind"]), ("query", case["query"]),
        ("limit", str(PAGE_LIMIT)),
    ]
    if case["language"]:
        params.append(("language", case["language"]))
    if cursor:
        try:
            safe_id(cursor, ALLOWED_KINDS[case["kind"]][0])
        except (ValueError, TypeError):
            raise CaptureError("Invalid request cursor.") from None
        params.append(("cursor", cursor))
    return path + "?" + parse.urlencode(params, quote_via=parse.quote, safe="")


def loopback_origin(value: str) -> str:
    try:
        u = parse.urlsplit(value)
        if (u.scheme != "http" or u.hostname != "127.0.0.1" or
            u.username is not None or u.password is not None or
            u.path not in ("", "/") or u.query or u.fragment or
            u.port is None or u.netloc != "127.0.0.1:" + str(u.port)):
            raise ValueError("Invalid local origin.")
    except ValueError:
        raise CaptureError("Capture requires literal 127.0.0.1 HTTP port.") from None
    return "http://127.0.0.1:" + str(u.port)


def check_page(page: object, case: dict, mode: str, cursor: str,
               last_id: str) -> tuple[str | None, str]:
    schema = "0.8.2" if mode == "scan" else "0.8.3"
    if not isinstance(page, dict) or page.get("schema_version") != schema:
        raise CaptureError("Unsupported search response schema.")
    must = {"schema_version", "kind", "items", "has_more",
            "search_complete", "next_cursor"}
    if not must.issubset(page) or set(page) - PAGE_KEYS[schema]:
        raise CaptureError("Unsupported response projection.")
    if (page["kind"] != case["kind"] or
        type(page["has_more"]) is not bool or
        type(page["search_complete"]) is not bool or
        page["has_more"] == page["search_complete"] or
        page.get("text_available") is not False or
        page.get("source_trail_verified") is not False or
        page.get("full_text_indexed") is not False or
        page.get("corpus_status") != "unreviewed_metadata_only"):
        raise CaptureError("Unsafe response or pagination status.")
    if schema == "0.8.2":
        if (page.get("candidate_window_limit") != 50 or
            page.get("match_order") != "canonical_id_scan_not_relevance_ranked"):
            raise CaptureError("Bounded scan semantics invalid.")
    elif (page.get("index_version") != "search_key_v1" or
          page.get("match_order") != "indexed_title_prefix_canonical_id" or
          page.get("alias_matching_available") is not False):
        raise CaptureError("Indexed-prefix semantics invalid.")
    items = page["items"]
    if not isinstance(items, list) or len(items) > PAGE_LIMIT:
        raise CaptureError("Page exceeded row limit.")
    last = last_id
    for hit in items:
        if not isinstance(hit, dict) or set(hit) != HIT_KEYS:
            raise CaptureError("Unexpected metadata hit fields.")
        try:
            ident = safe_id(hit["id"], ALLOWED_KINDS[case["kind"]][0])
        except (ValueError, TypeError):
            raise CaptureError("Result canonical ID invalid.") from None
        if (last and ident <= last) or (cursor and ident <= cursor):
            raise CaptureError("Result pagination order invalid.")
        if (hit["kind"] != ALLOWED_KINDS[case["kind"]][0] or
            hit["review_status"] != "unreviewed" or
            hit["source_verification"] != "NOT_VERIFIED" or
            hit["rights_status"] != "NOT_ASSESSED" or
            hit["text_available"] is not False):
            raise CaptureError("Rights/review metadata invalid.")
        last = ident
    next_cursor = page["next_cursor"]
    if page["has_more"]:
        try:
            safe_id(next_cursor, ALLOWED_KINDS[case["kind"]][0])
        except (ValueError, TypeError):
            raise CaptureError("Pagination cursor missing/invalid.") from None
        if (cursor and next_cursor <= cursor) or (last and next_cursor < last):
            raise CaptureError("Pagination cursor does not advance.")
        if schema == "0.8.3" and (not items or next_cursor != last):
            raise CaptureError("Indexed cursor differs from final hit.")
    elif next_cursor is not None:
        raise CaptureError("Completed page must have null cursor.")
    return next_cursor, last


class SignedLoopbackClient:
    """Proxy-free, redirect-free loopback caller; no arbitrary endpoint."""

    def __init__(self, base_url: str, *, token_path: Path | None = None,
                 key_path: Path | None = None, opener=None):
        self.origin = loopback_origin(base_url)
        self.bearer = load_token(token_path or api_token_path())
        self.key = load_token(key_path or signature_key_path())
        self.opener = opener if opener is not None else request.build_opener(
            request.ProxyHandler({}), NoRedirect())

    def fetch(self, target: str) -> dict:
        capabilities = {
            "/v1/search/metadata/indexed/capability?kind=" + kind
            for kind in ALLOWED_KINDS
        }
        if not isinstance(target, str) or not (
            target.startswith("/v1/search/metadata?") or
            target.startswith("/v1/search/metadata/indexed?") or
            target in capabilities
        ):
            raise CaptureError("Unapproved signed request target.")
        now = int(time.time())
        nonce = secrets.token_hex(16)
        headers = {
            "Authorization": "Bearer " + self.bearer,
            "X-DvirOS-Client": CLIENT_ID,
            "X-DvirOS-Timestamp": str(now),
            "X-DvirOS-Nonce": nonce,
            "X-DvirOS-Signature": sign_request(
                self.key, "GET", target, now, nonce),
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        }
        req = request.Request(self.origin + target, headers=headers, method="GET")
        try:
            with self.opener.open(req, timeout=REQUEST_TIMEOUT) as response:
                if response.status != 200:
                    raise CaptureError("Signed service status not successful.")
                body = response.read(MAX_PAGE_BYTES + 1)
                if len(body) > MAX_PAGE_BYTES:
                    raise CaptureError("Signed page exceeds byte budget.")
                payload = json.loads(body.decode("utf-8"))
        except (error.URLError, OSError, ValueError, UnicodeError):
            raise CaptureError("Signed localhost request failed.") from None
        if not isinstance(payload, dict):
            raise CaptureError("Signed response JSON envelope invalid.")
        return payload


def trace_pages(catalog: dict, snapshot: dict, *, mode: str) -> tuple[list, int]:
    _, cases = _query_catalog(catalog)
    if not isinstance(snapshot, dict) or set(snapshot) != {
        "schema_version", "responses"
    } or snapshot["schema_version"] != SNAPSHOT_SCHEMA:
        raise CaptureError("Snapshot envelope invalid.")
    records = snapshot["responses"]
    if not isinstance(records, list) or len(records) != len(cases):
        raise CaptureError("Snapshot case count invalid.")
    trace = []
    count = 0
    for case, record in zip(cases, records):
        if not isinstance(record, dict) or set(record) != {"id", "pages"} or (
            record["id"] != case["id"]
        ):
            raise CaptureError("Snapshot case IDs/order invalid.")
        pages = record["pages"]
        if not isinstance(pages, list) or not 1 <= len(pages) <= MAX_PAGES_PER_QUERY:
            raise CaptureError("Snapshot page count invalid.")
        cursor, last = "", ""
        total = 0
        steps = []
        for i, page in enumerate(pages):
            count += 1
            if count > MAX_REQUESTS:
                raise CaptureError("Snapshot exceeds request budget.")
            target = target_for(case, mode, cursor)
            following, last = check_page(page, case, mode, cursor, last)
            total += len(page["items"])
            if total > MAX_HITS_PER_QUERY:
                raise CaptureError("Snapshot exceeds result budget.")
            steps.append({
                "page": i + 1,
                "request_target_sha256": digest(target.encode("utf-8")),
                "input_cursor_sha256": digest(cursor.encode("utf-8")),
                "response_sha256": digest(encode(page)),
                "next_cursor_sha256": digest((following or "").encode("utf-8")),
                "returned": len(page["items"]),
                "completed": page["search_complete"],
            })
            if page["search_complete"] and i != len(pages) - 1:
                raise CaptureError("Snapshot contains pages after completion.")
            cursor = following or ""
        if not pages[-1]["search_complete"]:
            raise CaptureError("Snapshot paging incomplete.")
        try:
            evaluate_pages(record, {"kind": case["kind"], "labels": {}})
        except QualityEvidenceError:
            raise CaptureError("Snapshot failed rights/safety validation.") from None
        trace.append({"id": case["id"], "mode": mode, "steps": steps})
    return trace, count


def manifest_mac(unsigned: dict, key: str) -> str:
    if not isinstance(key, str) or len(key) < 40:
        raise CaptureError("Manifest signing key invalid.")
    return hmac.new(key.encode("utf-8"), HMAC_DOMAIN + encode(unsigned),
                    hashlib.sha256).hexdigest()


def collect(catalog: dict, fetch, *, mode: str, catalog_sha: str,
            key: str, revision_probe=None) -> tuple[dict, dict]:
    _, cases = _query_catalog(catalog)
    if mode not in ("scan", "indexed"):
        raise CaptureError("Invalid capture mode.")
    kinds = {case["kind"] for case in cases}
    revision_before = None
    if revision_probe is not None:
        from scripts.search_revision import validate_observation
        revision_before = revision_probe()
        validate_observation(revision_before, kinds, mode=mode)
    responses = []
    calls = 0
    for case in cases:
        pages = []
        cursor, last = "", ""
        count = 0
        for _ in range(MAX_PAGES_PER_QUERY):
            if calls >= MAX_REQUESTS:
                raise CaptureError("Request budget exhausted without completion.")
            page = fetch(target_for(case, mode, cursor))
            calls += 1
            following, last = check_page(page, case, mode, cursor, last)
            count += len(page["items"])
            if count > MAX_HITS_PER_QUERY:
                raise CaptureError("Per-question result budget exceeded.")
            pages.append(page)
            if page["search_complete"]:
                break
            cursor = following
        else:
            raise CaptureError("Page budget exhausted without completion.")
        responses.append({"id": case["id"], "pages": pages})
    snapshot = {"schema_version": SNAPSHOT_SCHEMA, "responses": responses}
    if len(encode(snapshot)) > MAX_BYTES:
        raise CaptureError("Frozen snapshot byte budget exceeded.")
    trace, verified_calls = trace_pages(catalog, snapshot, mode=mode)
    if calls != verified_calls:
        raise CaptureError("Internal request-count discrepancy.")
    if revision_probe is not None:
        revision_after = revision_probe()
        validate_observation(revision_after, kinds, mode=mode)
        if revision_before != revision_after:
            raise CaptureError("Observed metadata/index revision drifted during capture.")
    unsigned = {
        "schema_version": "0.8.10" if revision_probe is not None else SCHEMA,
        "mode": mode,
        "catalog_sha256": catalog_sha,
        "snapshot_sha256": digest(encode(snapshot)),
        "request_count": calls, "trace": trace,
        "client_signed_get_requests": True,
        "independent_server_attestation": False,
        "source_rights_verified": False,
        "independent_human_review_verified": False,
        "release_status": "HOLD",
    }
    if revision_before is not None:
        # HMAC-bound observed projection only, never a full immutable
        # corpus or database transaction revision.
        unsigned["revision_observation"] = revision_before
    return snapshot, {**unsigned, "manifest_hmac": manifest_mac(unsigned, key)}


def verify(catalog: dict, snapshot: dict, manifest: dict, *, catalog_sha: str,
           snapshot_sha: str, key: str) -> int:
    required = {"schema_version", "mode", "catalog_sha256", "snapshot_sha256",
                "request_count", "trace", "client_signed_get_requests",
                "independent_server_attestation", "source_rights_verified",
                "independent_human_review_verified", "release_status",
                "manifest_hmac"}
    if not isinstance(manifest, dict):
        raise CaptureError("Manifest envelope invalid.")
    schema = manifest.get("schema_version")
    if schema == "0.8.10":
        required.add("revision_observation")
    if set(manifest) != required:
        raise CaptureError("Manifest envelope invalid.")
    if schema == "0.8.10":
        from scripts.search_revision import validate_observation
        _, cases = _query_catalog(catalog)
        validate_observation(
            manifest["revision_observation"],
            {c["kind"] for c in cases}, mode=manifest["mode"])
    if (schema not in (SCHEMA, "0.8.10") or
        manifest["mode"] not in ("scan", "indexed") or
        manifest["catalog_sha256"] != catalog_sha or
        manifest["snapshot_sha256"] != snapshot_sha or
        manifest["client_signed_get_requests"] is not True or
        manifest["independent_server_attestation"] is not False or
        manifest["source_rights_verified"] is not False or
        manifest["independent_human_review_verified"] is not False or
        manifest["release_status"] != "HOLD"):
        raise CaptureError("Manifest trust/version contract invalid.")
    signature = manifest["manifest_hmac"]
    unsigned = {k: v for k, v in manifest.items() if k != "manifest_hmac"}
    if (not isinstance(signature, str) or len(signature) != 64 or
        not hmac.compare_digest(signature, manifest_mac(unsigned, key))):
        raise CaptureError("Manifest HMAC verification failed.")
    actual, count = trace_pages(catalog, snapshot, mode=manifest["mode"])
    if (actual != manifest["trace"] or
        type(manifest["request_count"]) is not int or
        count != manifest["request_count"]):
        raise CaptureError("Page request/response chain mismatch.")
    return count


def save_private_pair(snapshot_path: Path, manifest_path: Path, snapshot: dict,
                      manifest: dict) -> None:
    if (snapshot_path == manifest_path or snapshot_path.exists() or
        manifest_path.exists() or snapshot_path.is_symlink() or
        manifest_path.is_symlink()):
        raise CaptureError("Private output path exists or collides.")
    created = False
    try:
        _write_private(snapshot_path, snapshot)
        created = True
        _write_private(manifest_path, manifest)
    except Exception:
        if created:
            snapshot_path.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    capture = sub.add_parser("capture")
    capture.add_argument("--questions", type=Path, required=True)
    capture.add_argument("--output", type=Path, required=True)
    capture.add_argument("--manifest", type=Path, required=True)
    capture.add_argument("--search", choices=["scan", "indexed"], default="scan")
    capture.add_argument("--url", default="http://127.0.0.1:8000")
    capture.add_argument("--token-file", type=Path)
    capture.add_argument("--key-file", type=Path)
    capture.add_argument("--ack-authorized-metadata-only", action="store_true")
    capture.add_argument("--pin-observed-projection", action="store_true",
                         help="Before/after full bounded visible-metadata and index checks.")
    check = sub.add_parser("verify")
    check.add_argument("--questions", type=Path, required=True)
    check.add_argument("--responses", type=Path, required=True)
    check.add_argument("--manifest", type=Path, required=True)
    check.add_argument("--key-file", type=Path)
    check.add_argument("--require-observed-projection", action="store_true")
    args = parser.parse_args(argv)
    if args.mode == "capture" and not args.ack_authorized_metadata_only:
        print("[BLOCKED] Authorized private metadata capture acknowledgement required.")
        return 2
    try:
        catalog, catalog_sha = read_evidence(args.questions)
        if args.mode == "capture":
            client = SignedLoopbackClient(
                args.url, token_path=args.token_file, key_path=args.key_file)
            revision_probe = None
            if args.pin_observed_projection:
                from scripts.search_revision import observe_projection
                revision_probe = lambda: observe_projection(
                    catalog, client.fetch, mode=args.search)
            snapshot, manifest = collect(
                catalog, client.fetch, mode=args.search,
                catalog_sha=catalog_sha, key=client.key,
                revision_probe=revision_probe)
            save_private_pair(args.output, args.manifest, snapshot, manifest)
            count = manifest["request_count"]
        else:
            snapshot, snapshot_sha = read_evidence(args.responses)
            manifest, _ = read_evidence(args.manifest)
            if args.require_observed_projection and (
                manifest.get("schema_version") != "0.8.10"
            ):
                raise CaptureError("Capture lacks bounded revision observation.")
            key = load_token(args.key_file or signature_key_path())
            count = verify(
                catalog, snapshot, manifest, catalog_sha=catalog_sha,
                snapshot_sha=snapshot_sha, key=key)
        print("[OK] Private signed capture verified; pages=" + str(count)
              + "; research_release=HOLD")
        return 0
    except (OSError, TypeError, KeyError, ValueError, QualityEvidenceError):
        print("[FAIL] Signed private search capture rejected or unavailable.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
