"""Sefaria link metadata adapter with exact refs and fail-closed provenance.

The GCS export CSV uses the historic header typo 'Conection Type'. The adapter
recognizes it explicitly, never splits human-readable passage references, and
never claims that a structural link is a directional citation or influence.

Only *metadata* is staged; no book text or edition rights are inferred.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import tempfile
from typing import Iterable, Iterator
import unicodedata
from urllib.parse import urlsplit

from research_graph.ontology import (
    canonical_component, edition_id, evidence_id, passage_id, stable_id, work_id,
)

SCHEMA_VERSION = "0.3.0"
RIGHTS_TAG = "LINK_METADATA_UNREVIEWED"
EDITION_SENTINEL = "UNVERSIONED_LINK_METADATA_ONLY"
FIELDS = ("Citation 1", "Citation 2", "Conection Type", "Text 1", "Text 2", "Category 1", "Category 2")
CSV_URL_RE = re.compile(r"^https://storage\.googleapis\.com/sefaria-export/links/links(?:0|[1-9][0-9]?)\.csv$")
API_URL_RE = re.compile(r"^https://www\.sefaria\.org/api/links/[^?#]+\?with_text=0$")
SAFE_ERROR = {
    "missing_columns", "malformed_row", "missing_identity", "self_link",
    "unsafe_ref", "unresolved_api_mapping", "unsupported_api_record",
}


@dataclass(frozen=True)
class Link:
    left_ref: str
    right_ref: str
    left_work: str
    right_work: str
    link_type: str
    category_left: str = ""
    category_right: str = ""


def normalize_required(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("missing_identity")
    value = canonical_component(value)
    if len(value) > 500 or any(ord(ch) < 32 for ch in value):
        raise ValueError("unsafe_ref")
    return value


def normalize_optional(value: object) -> str:
    if value is None or value == "":
        return ""
    return normalize_required(value)


def csv_links(path: Path) -> Iterator[tuple[int, Link | None, str | None]]:
    """Stream Sefaria's historical 7-column links shard, without loading it."""
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or any(c not in reader.fieldnames for c in FIELDS):
            raise ValueError("missing_columns")
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError("missing_columns")
        for row in reader:
            line = reader.line_num
            try:
                if None in row or any(row.get(k) is None for k in FIELDS):
                    raise ValueError("malformed_row")
                link = Link(
                    normalize_required(row["Citation 1"]),
                    normalize_required(row["Citation 2"]),
                    normalize_required(row["Text 1"]),
                    normalize_required(row["Text 2"]),
                    normalize_optional(row["Conection Type"]) or "unspecified",
                    normalize_optional(row["Category 1"]),
                    normalize_optional(row["Category 2"]),
                )
                if link.left_ref == link.right_ref:
                    raise ValueError("self_link")
                yield line, link, None
            except (TypeError, ValueError) as exc:
                reason = str(exc) if str(exc) in SAFE_ERROR else "missing_identity"
                yield line, None, reason


def api_links(data: object, requested_index: str) -> Iterator[tuple[int, Link | None, str | None]]:
    """Accept only explicitly anchored API link records; never infer book from ref.

    Supported Sefaria /api/links shape: anchorRef, ref, index_title, type.
    Records lacking an explicit opposite work index are quarantined.
    """
    requested_index = normalize_required(requested_index)
    if not isinstance(data, list):
        raise ValueError("API links response must be a list.")
    for i, row in enumerate(data, 1):
        try:
            if not isinstance(row, dict):
                raise ValueError("unsupported_api_record")
            left = normalize_required(row.get("anchorRef"))
            right = normalize_required(row.get("ref"))
            opposite_title = normalize_required(row.get("index_title"))
            category = normalize_optional(row.get("type")) or normalize_optional(row.get("category")) or "unspecified"
            if left == right:
                raise ValueError("self_link")
            yield i, Link(left, right, requested_index, opposite_title, category), None
        except (TypeError, ValueError) as exc:
            reason = str(exc) if str(exc) in SAFE_ERROR else "unresolved_api_mapping"
            yield i, None, reason


def approved_source_url(url: str) -> str:
    """Strictly constrain provenance to public Sefaria metadata endpoints."""
    if not isinstance(url, str) or not (CSV_URL_RE.fullmatch(url) or API_URL_RE.fullmatch(url)):
        raise ValueError("Source must be exact allowlisted Sefaria metadata HTTPS URL.")
    if urlsplit(url).username or urlsplit(url).password:
        raise ValueError("URL may not contain credentials.")
    return url


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def staged_record(link: Link, source_record_id: str, source_uri: str,
                  snapshot_sha256: str) -> dict:
    """Return stable, provenance-linked metadata for a single undirected link."""
    sides = sorted([
        (link.left_work, link.left_ref, link.category_left),
        (link.right_work, link.right_ref, link.category_right),
    ], key=lambda item: (item[0], item[1]))
    work_a, ref_a, cat_a = sides[0]
    work_b, ref_b, cat_b = sides[1]
    w_a, w_b = work_id("sefaria", work_a), work_id("sefaria", work_b)
    e_a, e_b = edition_id(w_a, EDITION_SENTINEL), edition_id(w_b, EDITION_SENTINEL)
    p_a, p_b = passage_id(e_a, ref_a), passage_id(e_b, ref_b)
    evid = evidence_id(source_record_id, ref_a + "\n" + ref_b, link.link_type, p_a, p_b)
    edge = stable_id("edge", "SOURCE_LINK", p_a, p_b, evid)
    return {
        "schema_version": SCHEMA_VERSION, "provider": "sefaria",
        "source_record_id": source_record_id, "source_uri": source_uri,
        "snapshot_sha256": snapshot_sha256, "rights_tag": RIGHTS_TAG,
        "edition_status": "not_provided_by_links_export",
        "orientation": "not_asserted",
        "claim_kind": "OBSERVED_SOURCE_LINK", "review_status": "unreviewed",
        "link_type_raw": link.link_type, "evidence_id": evid, "edge_id": edge,
        "left": {
            "work_ref": work_a, "passage_ref": ref_a, "category": cat_a,
            "work_id": w_a, "edition_id": e_a, "passage_id": p_a,
        },
        "right": {
            "work_ref": work_b, "passage_ref": ref_b, "category": cat_b,
            "work_id": w_b, "edition_id": e_b, "passage_id": p_b,
        },
    }


def process_links(
    links: Iterable[tuple[int, Link | None, str | None]],
    *, source_uri: str, snapshot_sha256: str, allowed_titles: set[str],
    destination: Path, max_quarantine: int = 0, fixture_only: bool = False,
) -> dict:
    """Stream to temporary JSONL and promote only if quality gate is met.

    Every valid edge in the final plan contains a source-record stable ID,
    a source snapshot checksum, full refs, a rights gate and unreviewed kind.
    """
    if not fixture_only:
        approved_source_url(source_uri)
    if not re.fullmatch(r"[a-f0-9]{64}", snapshot_sha256):
        raise ValueError("Source snapshot checksum must be SHA-256 hex.")
    if not allowed_titles or max_quarantine < 0:
        raise ValueError("Select at least one curated title and a valid quarantine budget.")
    allowed = {normalize_required(title) for title in allowed_titles}
    destination = Path(destination)
    if destination.is_symlink():
        raise ValueError("Refusing a symlinked output directory.")
    destination.mkdir(parents=True, exist_ok=True)
    src_id = stable_id("source", "sefaria", source_uri, snapshot_sha256)
    counts = {"seen": 0, "selected": 0, "deduplicated": 0,
              "out_of_scope": 0, "quarantined": 0}
    seen = set()
    quarantine_summary = set()
    # Staging area is discarded when quality gate fails.
    with tempfile.TemporaryDirectory(prefix=".stage-", dir=destination) as tmp:
        tmpdir = Path(tmp)
        plan_path = tmpdir / "links.jsonl"
        rejected_path = tmpdir / "quarantine.jsonl"
        with plan_path.open("w", encoding="utf-8") as output, rejected_path.open("w", encoding="utf-8") as rejected:
            for line, link, failure in links:
                counts["seen"] += 1
                if failure or link is None:
                    counts["quarantined"] += 1
                    reason = failure if failure in SAFE_ERROR else "malformed_row"
                    rejected.write(json.dumps({"line": line, "reason": reason}, sort_keys=True) + "\n")
                    quarantine_summary.add(reason)
                    continue
                if link.left_work not in allowed and link.right_work not in allowed:
                    counts["out_of_scope"] += 1
                    continue
                record = staged_record(link, src_id, source_uri, snapshot_sha256)
                if record["edge_id"] in seen:
                    counts["deduplicated"] += 1
                    continue
                seen.add(record["edge_id"])
                counts["selected"] += 1
                output.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        if counts["quarantined"] > max_quarantine:
            raise ValueError(f"Quarantine gate failed: {counts['quarantined']} > {max_quarantine}; no plan published.")
        report = {
            "schema_version": SCHEMA_VERSION, "source_uri": source_uri,
            "snapshot_sha256": snapshot_sha256, "source_record_id": src_id,
            "rights_tag": RIGHTS_TAG, "text_rights_verified": False,
            "fixture_only": fixture_only,
            "claimed_citation_direction": False, "source_link_is_direct_citation": False,
            "selected_titles": sorted(allowed), "counts": counts,
            "links_sha256": file_sha256(plan_path),
            "quarantine_sha256": file_sha256(rejected_path),
            "quarantine_reasons": sorted(set(quarantine_summary)),
        }
        (tmpdir / "manifest.json").write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        for name in ("links.jsonl", "quarantine.jsonl", "manifest.json"):
            # Never overwrite an existing plan for a different source version.
            target = destination / name
            if target.is_symlink():
                raise ValueError("Refusing a symlinked output plan.")
            if target.exists() and target.read_bytes() != (tmpdir / name).read_bytes():
                raise ValueError("Output exists with different content: choose a fresh directory.")
        for name in ("links.jsonl", "quarantine.jsonl", "manifest.json"):
            target = destination / name
            if not target.exists():
                (tmpdir / name).replace(target)
    return report
