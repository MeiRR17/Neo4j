#!/usr/bin/env python3
"""Offline, deterministic, evidence-conservative research-search evaluation.

Consumes frozen assessor judgments and explicitly captured service search
pages. It never contacts Neo4j, calls an LLM, infers relevance, marks human
approvals, or prints document IDs, queries, titles or source text.
A self-declared reviewer is not an independently verified reviewer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_graph.ontology import require_canonical_id
from services.research_api.metadata_search import ALLOWED_KINDS, fold_metadata

SCHEMA = "0.8.7"
MAX_BYTES = 512_000
MAX_QUERIES = 100
MAX_PAGES = 100
MAX_RESULTS = 500
TOP_K = 5
MIN_REVIEWED = 50
TARGET_PRECISION = 0.80
QID = re.compile(r"^q-[a-z0-9][a-z0-9_-]{2,39}$")
KINDS = frozenset(ALLOWED_KINDS)


class QualityEvidenceError(ValueError):
    """Failure text must not contain file data, titles or document IDs."""


def _unique_keys(pairs: list[tuple[str, object]]) -> dict:
    out = {}
    for key, value in pairs:
        if key in out:
            raise QualityEvidenceError("Duplicate JSON object key.")
        out[key] = value
    return out


def read_evidence(path: Path) -> tuple[dict, str]:
    if path.is_symlink() or not path.is_file():
        raise QualityEvidenceError("Input must be a regular non-symlink file.")
    with path.open("rb") as handle:
        data = handle.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise QualityEvidenceError("Input exceeds file budget.")
    try:
        document = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_keys)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise QualityEvidenceError("Input is not canonical UTF-8 JSON.") from None
    if not isinstance(document, dict):
        raise QualityEvidenceError("Input must be a JSON object.")
    return document, hashlib.sha256(data).hexdigest()


def _string(value: object, *, max_length: int = 120) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= max_length:
        raise QualityEvidenceError("Invalid bounded text field.")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise QualityEvidenceError("Control character in input.")
    return value


def _canonical_id(raw: object, kind: str) -> str:
    try:
        validated = require_canonical_id(raw)
    except (ValueError, TypeError):
        raise QualityEvidenceError("Invalid canonical result identifier.") from None
    if validated.split(":", 1)[0] != ALLOWED_KINDS[kind][0]:
        raise QualityEvidenceError("Result identifier type mismatch.")
    return validated


def validate_judgments(data: dict) -> tuple[str, dict]:
    if set(data) != {"schema_version", "dataset_kind", "queries"} or data["schema_version"] != SCHEMA:
        raise QualityEvidenceError("Judgment envelope/schema invalid.")
    dataset_kind = data["dataset_kind"]
    if dataset_kind not in ("synthetic", "human_reviewed"):
        raise QualityEvidenceError("Dataset provenance category invalid.")
    cases = data["queries"]
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_QUERIES:
        raise QualityEvidenceError("Dataset query count outside bound.")
    parsed = {}
    for case in cases:
        if not isinstance(case, dict) or set(case) != {"id", "kind", "query", "language", "judgments"}:
            raise QualityEvidenceError("Judgment case structure invalid.")
        qid = case["id"]
        if not isinstance(qid, str) or not QID.fullmatch(qid) or qid in parsed:
            raise QualityEvidenceError("Judgment query IDs invalid or duplicated.")
        kind = case["kind"]
        if kind not in KINDS:
            raise QualityEvidenceError("Unknown entity type.")
        language = case["language"]
        if language not in ("", "he", "en", "ar", "yi") or (language and kind != "works"):
            raise QualityEvidenceError("Language constraint invalid.")
        query = _string(case["query"], max_length=100)
        try:
            if not fold_metadata(query):
                raise ValueError("Empty folded search.")
        except (ValueError, TypeError):
            raise QualityEvidenceError("Search term cannot be normalized.") from None
        judgments = case["judgments"]
        if not isinstance(judgments, list) or not 5 <= len(judgments) <= MAX_RESULTS:
            raise QualityEvidenceError("At least five bounded judgments are required.")
        labels = {}
        for row in judgments:
            if not isinstance(row, dict) or set(row) != {
                "id", "relevance", "reviewer_id", "evidence_ref"
            }:
                raise QualityEvidenceError("Relevance judgment structure invalid.")
            rid = _canonical_id(row["id"], kind)
            if rid in labels or type(row["relevance"]) is not int or row["relevance"] not in (0, 1):
                raise QualityEvidenceError("Conflicting, missing or duplicate relevance labels.")
            _string(row["reviewer_id"], max_length=80)
            _string(row["evidence_ref"], max_length=180)
            labels[rid] = row["relevance"]
        parsed[qid] = {"kind": kind, "language": language, "labels": labels}
    return dataset_kind, parsed


def evaluate_pages(record: dict, case: dict) -> dict:
    if not isinstance(record, dict) or set(record) != {"id", "pages"}:
        raise QualityEvidenceError("Captured response envelope invalid.")
    pages = record["pages"]
    if not isinstance(pages, list) or not 1 <= len(pages) <= MAX_PAGES:
        raise QualityEvidenceError("Captured page count invalid.")
    schema = None
    all_ids: list[str] = []
    missing_anchors = 0
    seen_ids = set()
    seen_cursors = set()
    complete = False
    for number, page in enumerate(pages):
        if not isinstance(page, dict) or not {
            "schema_version", "kind", "items", "search_complete",
            "has_more", "next_cursor",
        }.issubset(page):
            raise QualityEvidenceError("Captured page structure invalid.")
        current_schema = page["schema_version"]
        if current_schema not in ("0.8.2", "0.8.3") or (
            schema is not None and current_schema != schema
        ):
            raise QualityEvidenceError("Search result schema changed between pages.")
        schema = current_schema
        if page["kind"] != case["kind"]:
            raise QualityEvidenceError("Captured page entity type mismatch.")
        if type(page["has_more"]) is not bool or type(page["search_complete"]) is not bool:
            raise QualityEvidenceError("Pagination flags must be boolean.")
        if page["search_complete"] == page["has_more"]:
            raise QualityEvidenceError("Pagination completion flags conflict.")
        cursor = page["next_cursor"]
        if page["has_more"]:
            if not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
                raise QualityEvidenceError("Pagination cursor invalid or repeated.")
            _canonical_id(cursor, case["kind"])
            seen_cursors.add(cursor)
        elif cursor is not None:
            raise QualityEvidenceError("Completed search must have no cursor.")
        if number < len(pages) - 1 and page["search_complete"]:
            raise QualityEvidenceError("Pagination continued after completion.")
        if not isinstance(page["items"], list) or len(page["items"]) > 20:
            raise QualityEvidenceError("Search page exceeds result limit.")
        for hit in page["items"]:
            if not isinstance(hit, dict) or not {
                "id", "kind", "source_anchor", "review_status",
                "source_verification", "rights_status", "text_available",
            }.issubset(hit):
                raise QualityEvidenceError("Search hit projection invalid.")
            rid = _canonical_id(hit["id"], case["kind"])
            if rid in seen_ids:
                raise QualityEvidenceError("Repeated result across captured pages.")
            seen_ids.add(rid)
            if len(all_ids) >= MAX_RESULTS:
                raise QualityEvidenceError("Captured results exceed budget.")
            if hit["kind"] != ALLOWED_KINDS[case["kind"]][0] or (
                hit["review_status"] != "unreviewed" or
                hit["source_verification"] != "NOT_VERIFIED" or
                hit["rights_status"] != "NOT_ASSESSED" or
                hit["text_available"] is not False
            ):
                raise QualityEvidenceError("Unapproved result status or kind.")
            if "excerpt" in hit or "text" in hit or "text_body" in hit:
                raise QualityEvidenceError("Source text in metadata-only results.")
            anchor = hit["source_anchor"]
            if anchor is not None:
                _string(anchor, max_length=500)
            if case["kind"] in ("works", "passages") and anchor is None:
                missing_anchors += 1
            all_ids.append(rid)
        complete = page["search_complete"]
    top = all_ids[:TOP_K]
    unjudged = sum(rid not in case["labels"] for rid in top)
    eligible = complete and unjudged == 0 and missing_anchors == 0
    precision = (
        round(sum(case["labels"][rid] for rid in top) / TOP_K, 4)
        if eligible else None
    )
    return {
        "schema": schema,
        "eligible": eligible,
        "precision_at_5": precision,
        "retrieved_top5": len(top),
        "unjudged_top5": unjudged,
        "missing_anchors": missing_anchors,
        "search_complete": complete,
        "returned_count": len(all_ids),
        "ranking_semantics": (
            "canonical_id_scan_not_relevance_ranked"
            if schema == "0.8.2" else "indexed_title_prefix_canonical_id"
        ),
    }


def evaluate(judgments: dict, captured: dict, *, hashes: tuple[str, str] = ("", "")) -> dict:
    kind, cases = validate_judgments(judgments)
    if set(captured) != {"schema_version", "responses"} or captured["schema_version"] != SCHEMA:
        raise QualityEvidenceError("Captured search snapshot envelope invalid.")
    records = captured["responses"]
    if not isinstance(records, list) or len(records) != len(cases):
        raise QualityEvidenceError("Every frozen question needs one captured response.")
    results = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            raise QualityEvidenceError("Captured query identity malformed.")
        qid = record["id"]
        if qid not in cases or qid in results:
            raise QualityEvidenceError("Missing, unexpected or repeated query capture.")
        results[qid] = evaluate_pages(record, cases[qid])
    rows = [{"id": qid, "kind": cases[qid]["kind"], **results[qid]} for qid in sorted(cases)]
    eligible = [item for item in rows if item["eligible"]]
    all_eligible = len(eligible) == len(rows)
    observed = round(sum(item["precision_at_5"] for item in eligible) / len(eligible), 4) if eligible else None
    # A declared human_reviewed dataset is an *assertion supplied by the
    # file*, not verified governance. Release approval always remains HOLD.
    target_observed = (kind == "human_reviewed" and len(rows) >= MIN_REVIEWED
                       and all_eligible and observed is not None
                       and observed >= TARGET_PRECISION)
    return {
        "schema_version": SCHEMA,
        "dataset_kind_claimed": kind,
        "judgments_sha256": hashes[0],
        "captures_sha256": hashes[1],
        "questions_total": len(rows),
        "eligible_questions": len(eligible),
        "mean_precision_at_5_eligible_only": observed,
        "target_precision_at_5": TARGET_PRECISION,
        "minimum_human_questions": MIN_REVIEWED,
        "quality_target_observed": target_observed,
        "external_human_review_verified": False,
        "production_release_status": "HOLD",
        "unjudged_hits_top5": sum(item["unjudged_top5"] for item in rows),
        "incomplete_queries": sum(not item["search_complete"] for item in rows),
        "missing_source_anchors": sum(item["missing_anchors"] for item in rows),
        "unscorable_queries": len(rows) - len(eligible),
        "cases": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--judgments", type=Path, required=True)
    parser.add_argument("--responses", type=Path, required=True)
    parser.add_argument("--require-quality-target", action="store_true",
                        help="Require observed threshold, never release approval.")
    args = parser.parse_args(argv)
    try:
        judgments, a = read_evidence(args.judgments)
        captures, b = read_evidence(args.responses)
        report = evaluate(judgments, captures, hashes=(a, b))
        print(json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        return 1 if args.require_quality_target and not report["quality_target_observed"] else 0
    except (OSError, QualityEvidenceError, ValueError):
        print("[FAIL] Frozen search quality inputs invalid; no quality claim made.")
        return 2


if __name__ == "__main__":
    sys.exit(main())
