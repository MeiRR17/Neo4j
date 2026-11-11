#!/usr/bin/env python3
"""v0.8.8 offline dual-review preparation and explicit disagreement resolution.

No graph/network access, AI-generated labels, automatic human approval, writes
to the source corpus or stdout exposure of research titles/source anchors.
Private output files are created exclusively at mode 0600, never overwritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_graph.ontology import require_canonical_id
from scripts.search_quality_eval import (
    ALLOWED_KINDS, MAX_QUERIES, QID, QualityEvidenceError, SCHEMA as EVAL_SCHEMA,
    _string, evaluate_pages, read_evidence, validate_judgments,
)
from services.research_api.metadata_search import fold_metadata

SCHEMA = "0.8.8"
DATASET_KINDS = {"synthetic", "candidate_human"}
MAX_FORM_ROWS = MAX_QUERIES * 5


class ReviewWorkflowError(QualityEvidenceError):
    """Constant, non-source error codes only."""


def _keys(value: object, keys: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == keys


def _sha(value: object) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ReviewWorkflowError("Invalid input fingerprint.")
    try:
        int(value, 16)
    except ValueError:
        raise ReviewWorkflowError("Invalid input fingerprint.") from None
    if value != value.lower():
        raise ReviewWorkflowError("Invalid fingerprint case.")
    return value


def _query_catalog(data: dict) -> tuple[str, list[dict]]:
    if not _keys(data, {"schema_version", "dataset_kind", "questions"}):
        raise ReviewWorkflowError("Question catalog envelope invalid.")
    if data["schema_version"] != SCHEMA or data["dataset_kind"] not in DATASET_KINDS:
        raise ReviewWorkflowError("Question catalog version/provenance invalid.")
    questions = data["questions"]
    if not isinstance(questions, list) or not 1 <= len(questions) <= MAX_QUERIES:
        raise ReviewWorkflowError("Question count outside bound.")
    seen = set()
    for case in questions:
        if not _keys(case, {"id", "kind", "query", "language"}):
            raise ReviewWorkflowError("Question form invalid.")
        qid, kind, language = case["id"], case["kind"], case["language"]
        if not isinstance(qid, str) or not QID.fullmatch(qid) or qid in seen:
            raise ReviewWorkflowError("Question ID invalid/duplicate.")
        seen.add(qid)
        if kind not in ALLOWED_KINDS or language not in ("", "he", "en", "ar", "yi"):
            raise ReviewWorkflowError("Question kind/language invalid.")
        if language and kind != "works":
            raise ReviewWorkflowError("Language filter unsupported for entity type.")
        try:
            if not fold_metadata(_string(case["query"], max_length=100)):
                raise ValueError("Empty normalized query.")
        except (ValueError, TypeError):
            raise ReviewWorkflowError("Question query invalid.") from None
    return data["dataset_kind"], questions


def prepare_packet(catalog: dict, captures: dict, *, catalog_hash: str,
                   captures_hash: str) -> dict:
    """Use only completed, metadata-only captures; never fabricate judgments."""
    category, cases = _query_catalog(catalog)
    if not _keys(captures, {"schema_version", "responses"}) or (
        captures["schema_version"] != EVAL_SCHEMA
    ):
        raise ReviewWorkflowError("Captured search envelope invalid.")
    responses = captures["responses"]
    if not isinstance(responses, list) or len(responses) != len(cases):
        raise ReviewWorkflowError("Captured responses must match every question.")
    index = {}
    for record in responses:
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            raise ReviewWorkflowError("Captured query ID invalid.")
        qid = record["id"]
        if qid in index:
            raise ReviewWorkflowError("Captured query repeated.")
        index[qid] = record
    if set(index) != {case["id"] for case in cases}:
        raise ReviewWorkflowError("Captured question set differs from catalog.")
    result = []
    for case in cases:
        record = index[case["id"]]
        try:
            summary = evaluate_pages(record, {"kind": case["kind"], "labels": {}})
        except QualityEvidenceError:
            # Convert the upstream safety-contract failure to our public
            # workflow error without repeating source properties or text.
            raise ReviewWorkflowError("Captured search metadata invalid.") from None
        if not summary["search_complete"] or summary["missing_anchors"]:
            raise ReviewWorkflowError("Incomplete search or missing source anchor.")
        all_hits = [hit for page in record["pages"] for hit in page["items"]]
        if len(all_hits) < 5:
            # The existing evaluator's frozen judgments require five IDs.
            raise ReviewWorkflowError("Five results required for review packet.")
        chosen = []
        for rank, hit in enumerate(all_hits[:5], 1):
            if not _keys(hit, {"id", "kind", "title", "source_anchor",
                              "match_basis", "review_status",
                              "source_verification", "rights_status",
                              "text_available"}):
                raise ReviewWorkflowError("Unsafe metadata result projection.")
            title = _string(hit["title"], max_length=300)
            anchor = hit["source_anchor"]
            if anchor is not None:
                _string(anchor, max_length=500)
            if hit["match_basis"] not in ("canonical_id", "title", "alias"):
                raise ReviewWorkflowError("Unknown match semantics.")
            chosen.append({
                "id": hit["id"], "rank": rank, "title": title,
                "source_anchor": anchor, "match_basis": hit["match_basis"],
            })
        result.append({
            **case, "search_schema": summary["schema"],
            "ranking_semantics": summary["ranking_semantics"],
            "hits": chosen,
        })
    return {
        "schema_version": SCHEMA, "dataset_kind": category,
        "catalog_sha256": _sha(catalog_hash),
        "captures_sha256": _sha(captures_hash),
        "review_status": "UNREVIEWED",
        "questions": result,
    }


def _packet_questions(packet: dict) -> list[dict]:
    if not _keys(packet, {"schema_version", "dataset_kind", "catalog_sha256",
                          "captures_sha256", "review_status", "questions"}):
        raise ReviewWorkflowError("Review packet envelope invalid.")
    if packet["schema_version"] != SCHEMA or (
        packet["dataset_kind"] not in DATASET_KINDS
    ) or packet["review_status"] != "UNREVIEWED":
        raise ReviewWorkflowError("Review packet version/status invalid.")
    _sha(packet["catalog_sha256"])
    _sha(packet["captures_sha256"])
    _, catalog = _query_catalog({
        "schema_version": SCHEMA, "dataset_kind": packet["dataset_kind"],
        "questions": [{k: c[k] for k in ("id", "kind", "query", "language")}
                      for c in packet["questions"]],
    })
    for case in packet["questions"]:
        if not _keys(case, {"id", "kind", "query", "language",
                            "search_schema", "ranking_semantics", "hits"}):
            raise ReviewWorkflowError("Review packet question keys invalid.")
        if case["search_schema"] not in ("0.8.2", "0.8.3"):
            raise ReviewWorkflowError("Review packet search version invalid.")
        if not isinstance(case["hits"], list) or len(case["hits"]) != 5:
            raise ReviewWorkflowError("Review packet must contain five results.")
        seen = set()
        for n, hit in enumerate(case["hits"], 1):
            if not _keys(hit, {"id", "rank", "title", "source_anchor", "match_basis"}):
                raise ReviewWorkflowError("Review result fields invalid.")
            if type(hit["rank"]) is not int or hit["rank"] != n:
                raise ReviewWorkflowError("Review result rank invalid.")
            try:
                rid = require_canonical_id(hit["id"])
            except (ValueError, TypeError):
                raise ReviewWorkflowError("Review result canonical ID invalid.") from None
            if rid in seen or rid.split(":")[0] != ALLOWED_KINDS[case["kind"]][0]:
                raise ReviewWorkflowError("Review result duplicated/type mismatch.")
            seen.add(rid)
            _string(hit["title"], max_length=300)
            if hit["source_anchor"] is not None:
                _string(hit["source_anchor"], max_length=500)
            if hit["match_basis"] not in ("canonical_id", "title", "alias"):
                raise ReviewWorkflowError("Review match basis invalid.")
    return catalog


def reviewer_template(packet: dict, *, packet_hash: str, reviewer_id: str) -> dict:
    _packet_questions(packet)
    _string(reviewer_id, max_length=30)
    rows = [
        {"query_id": q["id"], "id": hit["id"], "relevance": None,
         "evidence_ref": None}
        for q in packet["questions"] for hit in q["hits"]
    ]
    return {"schema_version": SCHEMA, "packet_sha256": _sha(packet_hash),
            "reviewer_id": reviewer_id, "labels": rows}


def _labels(form: dict, *, packet: dict, packet_hash: str,
            needed: set[tuple[str, str]] | None = None) -> tuple[str, dict]:
    if not _keys(form, {"schema_version", "packet_sha256", "reviewer_id", "labels"}):
        raise ReviewWorkflowError("Assessment envelope invalid.")
    if form["schema_version"] != SCHEMA or form["packet_sha256"] != packet_hash:
        raise ReviewWorkflowError("Assessment is not bound to this packet.")
    reviewer = _string(form["reviewer_id"], max_length=30)
    expected = (needed if needed is not None else {
        (q["id"], h["id"]) for q in packet["questions"] for h in q["hits"]
    })
    rows = form["labels"]
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise ReviewWorkflowError("Assessment row count invalid.")
    judged = {}
    for row in rows:
        if not _keys(row, {"query_id", "id", "relevance", "evidence_ref"}):
            raise ReviewWorkflowError("Assessment row shape invalid.")
        key = (row["query_id"], row["id"])
        if key not in expected or key in judged:
            raise ReviewWorkflowError("Unexpected/repeated assessment ID.")
        if type(row["relevance"]) is not int or row["relevance"] not in (0, 1):
            raise ReviewWorkflowError("Unreviewed or nonbinary relevance.")
        _string(row["evidence_ref"], max_length=180)
        judged[key] = (row["relevance"], row["evidence_ref"])
    return reviewer, judged


def freeze_reviews(packet: dict, *, packet_hash: str, first: dict, second: dict,
                   third: dict | None = None,
                   review_hashes: tuple[str, ...] = ()) -> tuple[dict, dict]:
    """Both reviewers must label all top-five hits; disputes require third."""
    _packet_questions(packet)
    reviewer_a, a = _labels(first, packet=packet, packet_hash=packet_hash)
    reviewer_b, b = _labels(second, packet=packet, packet_hash=packet_hash)
    if reviewer_a == reviewer_b:
        raise ReviewWorkflowError("Two distinct reviewer IDs are required.")
    conflicts = {key for key in a if a[key][0] != b[key][0]}
    adjudicator = None
    adjudicated = {}
    if conflicts and third is None:
        raise ReviewWorkflowError("Disagreement requires independent adjudication.")
    if third is not None:
        adjudicator, adjudicated = _labels(
            third, packet=packet, packet_hash=packet_hash, needed=conflicts)
        if adjudicator in (reviewer_a, reviewer_b):
            raise ReviewWorkflowError("Adjudicator must be distinct.")
    judgments = []
    for q in packet["questions"]:
        rows = []
        for hit in q["hits"]:
            key = (q["id"], hit["id"])
            if key in conflicts:
                chosen = adjudicated[key]
                person = adjudicator
            else:
                chosen = a[key]
                person = reviewer_a + "+" + reviewer_b
            rows.append({
                "id": hit["id"], "relevance": chosen[0],
                "reviewer_id": person, "evidence_ref": chosen[1],
            })
        judgments.append({
            "id": q["id"], "kind": q["kind"],
            "query": q["query"], "language": q["language"],
            "judgments": rows,
        })
    final = {
        "schema_version": EVAL_SCHEMA,
        # A claim, not independently verified scholar identity or permissions.
        "dataset_kind": ("synthetic" if packet["dataset_kind"] == "synthetic"
                         else "human_reviewed"),
        "queries": judgments,
    }
    validate_judgments(final)
    audit = {
        "schema_version": SCHEMA, "packet_sha256": _sha(packet_hash),
        "review_file_sha256": [_sha(h) for h in review_hashes],
        "questions": len(judgments),
        "judgments": sum(len(q["judgments"]) for q in judgments),
        "disagreements_adjudicated": len(conflicts),
        "independent_reviewer_identity_verified": False,
        "scholarly_source_rights_verified": False,
        "production_release_status": "HOLD",
    }
    return final, audit


def _write_private(path: Path, payload: dict) -> None:
    # No overwrites (even symlinks), world-readable files, or repo mutations.
    content = (json.dumps(payload, ensure_ascii=False, indent=2,
                          sort_keys=True) + "\n").encode("utf-8")
    if len(content) > 512_000:
        raise ReviewWorkflowError("Private output exceeds file budget.")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as f:
            f.write(content)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    operations = parser.add_subparsers(dest="action", required=True)
    prepare = operations.add_parser("prepare")
    prepare.add_argument("--questions", type=Path, required=True)
    prepare.add_argument("--responses", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    template = operations.add_parser("template")
    template.add_argument("--packet", type=Path, required=True)
    template.add_argument("--reviewer-id", required=True)
    template.add_argument("--output", type=Path, required=True)
    freeze = operations.add_parser("freeze")
    freeze.add_argument("--packet", type=Path, required=True)
    freeze.add_argument("--review-a", type=Path, required=True)
    freeze.add_argument("--review-b", type=Path, required=True)
    freeze.add_argument("--adjudicator", type=Path)
    freeze.add_argument("--output", type=Path, required=True)
    freeze.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "prepare":
            catalog, c_hash = read_evidence(args.questions)
            captures, r_hash = read_evidence(args.responses)
            result = prepare_packet(catalog, captures,
                                    catalog_hash=c_hash, captures_hash=r_hash)
            _write_private(args.output, result)
            count = len(result["questions"])
        elif args.action == "template":
            packet, p_hash = read_evidence(args.packet)
            result = reviewer_template(packet, packet_hash=p_hash,
                                       reviewer_id=args.reviewer_id)
            _write_private(args.output, result)
            count = len(result["labels"])
        else:
            packet, p_hash = read_evidence(args.packet)
            first, a_hash = read_evidence(args.review_a)
            second, b_hash = read_evidence(args.review_b)
            third, t_hash = read_evidence(args.adjudicator) if args.adjudicator else (None, "")
            result, audit = freeze_reviews(
                packet, packet_hash=p_hash, first=first, second=second,
                third=third, review_hashes=tuple(
                    h for h in (a_hash, b_hash, t_hash) if h))
            # Both output paths must be new. Never replace any review evidence.
            if args.output == args.audit or args.output.exists() or args.audit.exists():
                raise ReviewWorkflowError("Output paths already exist or collide.")
            _write_private(args.output, result)
            _write_private(args.audit, audit)
            count = audit["judgments"]
        print("[OK] Private review workflow output created; records=" + str(count)
              + "; release=HOLD")
        return 0
    except (OSError, ValueError, TypeError, KeyError, QualityEvidenceError):
        print("[FAIL] Private review workflow rejected invalid or incomplete input.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
