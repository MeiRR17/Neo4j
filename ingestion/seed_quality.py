"""Human rights review, reproducible evidence samples, and quality gates.

Neither Sefaria metadata discovery nor an AI answer can approve source rights
or scholarly assertions. Decisions are separate, human-authored records bound
to immutable inventory/review queue hashes.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from ingestion.seed_catalog import (
    RIGHTS_LICENSES, SCHEMA_VERSION, checksum, compact_json, parse_versions,
    safe_title, versions_url,
)
from research_graph.ontology import require_canonical_id

MIN_WORKS = 12
MIN_REVIEWED_EDGES = 100
DECISIONS = frozenset({"approve_metadata", "reject"})
OBSERVATIONS = frozenset({"confirmed_observed_link", "not_supported", "uncertain"})


def read_jsonl(path: Path, *, max_lines: int = 100_000) -> list[dict]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Review file must be a regular non-symlink JSONL file.")
    result = []
    with path.open(encoding="utf-8") as src:
        for line in src:
            if line.strip():
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise ValueError("JSONL record must be a JSON object.")
                result.append(item)
                if len(result) > max_lines:
                    raise ValueError("Review file exceeds the line limit.")
    return result


def review_time(value: str) -> str:
    if not isinstance(value, str) or len(value) > 50:
        raise ValueError("Review requires an explicit ISO 8601 timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Review timestamp is not ISO 8601.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Review timestamp needs a timezone.")
    return value


def reviewer(value: object) -> str:
    if not isinstance(value, str) or not 3 <= len(value.strip()) <= 120:
        raise ValueError("A nonempty reviewer identity is required.")
    return value.strip()


def human_rationale(value: object) -> str:
    if not isinstance(value, str) or len(value.strip()) < 24 or len(value) > 3000:
        raise ValueError("Human review requires a substantial rationale (24..3000 chars).")
    return value.strip()


def evidence_uri(uri: object) -> str:
    if not isinstance(uri, str) or len(uri) > 1500:
        raise ValueError("Rights evidence URI is missing or oversized.")
    parsed = urlsplit(uri)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Rights evidence must have a credential-free HTTPS reference.")
    return uri


def verify_inventory(inventory: dict) -> dict[str, dict]:
    if not isinstance(inventory, dict) or inventory.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported version inventory.")
    if inventory.get("status") != "PENDING_HUMAN_RIGHTS_REVIEW" or inventory.get("no_text_downloaded") is not True:
        raise ValueError("Inventory cannot claim pre-reviewed rights or downloaded texts.")
    if inventory.get("verified_edition_count") != 0 or inventory.get("rights_decisions_generated") is not False:
        raise ValueError("Discovery cannot pre-authorize editions.")
    candidates = inventory.get("candidates")
    if not isinstance(candidates, list) or not 12 <= len(candidates) <= 20:
        raise ValueError("Seed catalog must contain 12..20 candidates.")
    if len({x["index_title"] for x in candidates}) != len(candidates):
        raise ValueError("Duplicate candidate work.")
    if checksum(candidates) != inventory.get("catalog_sha256"):
        raise ValueError("Candidate catalog changed after discovery.")
    snapshots = inventory.get("source_snapshots")
    if not isinstance(snapshots, list):
        raise ValueError("Inventory source snapshot list missing.")
    source_by_title = {s["index_title"]: s for s in snapshots}
    if len(source_by_title) != len(snapshots):
        raise ValueError("Duplicate source snapshot.")
    editions = inventory.get("editions")
    if not isinstance(editions, list) or len(editions) > 20_000:
        raise ValueError("Invalid inventory edition list.")
    seen = {}
    for edition in editions:
        title = safe_title(edition["index_title"])
        if title not in {c["index_title"] for c in candidates} or title not in source_by_title:
            raise ValueError("Edition outside enumerated discovery snapshots.")
        from research_graph.ontology import work_id, edition_id
        wid = work_id("sefaria", title)
        expected = edition_id(wid, edition["language"] + "|" + edition["version_title"])
        if edition.get("work_id") != wid or edition.get("edition_id") != expected:
            raise ValueError("Edition canonical identity mismatch.")
        if edition.get("metadata_source") != versions_url(title):
            raise ValueError("Edition source URI mismatch.")
        if edition.get("rights_status") != "pending_human_review" or edition.get("allowed_text_redistribution") is not False:
            raise ValueError("Inventory illegally pre-approves source rights.")
        source = source_by_title[title]
        if source.get("url") != versions_url(title):
            raise ValueError("Snapshot source URL mismatch.")
        if expected in seen:
            raise ValueError("Duplicate edition identity.")
        seen[expected] = edition
    return seen


def validate_rights_decisions(inventory: dict, decisions: list[dict]) -> dict[str, dict]:
    by_edition = verify_inventory(inventory)
    digest = checksum(inventory)
    reviewed = {}
    for item in decisions:
        ident = item.get("edition_id")
        if ident not in by_edition or ident in reviewed:
            raise ValueError("Unknown or duplicate rights-review edition ID.")
        if item.get("inventory_sha256") != digest:
            raise ValueError("Rights review is bound to a different inventory snapshot.")
        choice = item.get("decision")
        if choice not in DECISIONS:
            raise ValueError("Rights decision must explicitly approve metadata or reject.")
        reviewer(item.get("reviewer_id"))
        review_time(item.get("reviewed_at"))
        human_rationale(item.get("rationale"))
        ed = by_edition[ident]
        if choice == "approve_metadata":
            if item.get("license_confirmed") != ed["license_raw"]:
                raise ValueError("Approved license must match exact edition metadata.")
            if ed["license_raw"] not in RIGHTS_LICENSES:
                raise ValueError("Unrecognized or missing license cannot be approved.")
            if item.get("intended_use") != "research_metadata_only":
                raise ValueError("Only metadata use is in scope in v0.4.")
            if ed["license_raw"] == "CC-BY-NC" and item.get("use_context") != "noncommercial":
                raise ValueError("Noncommercial license requires explicit noncommercial context.")
            if not isinstance(item.get("attribution"), str) or len(item["attribution"].strip()) < 8:
                raise ValueError("Reviewed edition needs documented attribution.")
            evidence_uri(item.get("rights_evidence_uri"))
        reviewed[ident] = item
    return reviewed


def make_review_queue(staged: list[dict], *, sample_size: int = 120,
                      fixture: bool = False) -> dict:
    if not 100 <= sample_size <= 500:
        raise ValueError("Review sample must target 100..500 edges.")
    unique = {}
    for item in staged:
        eid = require_canonical_id(item["evidence_id"])
        if eid.split(":", 1)[0] != "evidence":
            raise ValueError("Not a canonical evidence ID.")
        if item.get("claim_kind") != "OBSERVED_SOURCE_LINK" or item.get("orientation") != "not_asserted":
            raise ValueError("Research queue cannot assert citation or causal direction.")
        if eid in unique and item != unique[eid]:
            raise ValueError("Evidence ID collision with conflicting source metadata.")
        unique[eid] = item
    # Deterministic hash-order sample, not biased by CSV row ordering.
    order = sorted(unique, key=lambda s: hashlib.sha256(s.encode("utf-8")).hexdigest())
    selected = []
    for eid in order[:sample_size]:
        record = unique[eid]
        selected.append({
            "evidence_id": eid, "source_record_id": record["source_record_id"],
            "source_uri": record["source_uri"],
            "source_ref_left": record["left"]["passage_ref"],
            "source_ref_right": record["right"]["passage_ref"],
            "raw_link_type": record["link_type_raw"],
            "claim_kind": "OBSERVED_SOURCE_LINK",
            "orientation": "not_asserted",
            "review_status": "pending_human_inspection",
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "fixture_only": fixture, "target_count": sample_size,
        "available_evidence_count": len(unique),
        "selected_count": len(selected),
        "reviewer_decisions_generated": False,
        "items": selected,
    }


def validate_evidence_reviews(queue: dict, decisions: list[dict]) -> dict[str, dict]:
    if queue.get("schema_version") != SCHEMA_VERSION or queue.get("reviewer_decisions_generated") is not False:
        raise ValueError("Invalid or pre-reviewed evidence queue.")
    ids = {item["evidence_id"] for item in queue["items"]}
    if len(ids) != len(queue["items"]):
        raise ValueError("Duplicate queue evidence IDs.")
    digest = checksum(queue)
    observed = {}
    for item in decisions:
        eid = item.get("evidence_id")
        if eid not in ids or eid in observed:
            raise ValueError("Unknown or duplicate evidence review.")
        if item.get("queue_sha256") != digest:
            raise ValueError("Evidence review references a different frozen queue.")
        if item.get("decision") not in OBSERVATIONS:
            raise ValueError("Not a permitted observation review outcome.")
        reviewer(item.get("reviewer_id"))
        review_time(item.get("reviewed_at"))
        human_rationale(item.get("rationale"))
        if item.get("asserted_influence") is not False or item.get("asserted_citation_direction") is not False:
            raise ValueError("Observed-link review cannot assert causal influence or citation direction.")
        observed[eid] = item
    return observed


def quality_report(inventory: dict, rights_decisions: list[dict],
                   queue: dict | None, evidence_decisions: list[dict],
                   staged: list[dict] | None = None) -> dict:
    verified = verify_inventory(inventory)
    approved = validate_rights_decisions(inventory, rights_decisions)
    evidence = validate_evidence_reviews(queue, evidence_decisions) if queue else {}
    inspected_works = {verified[k]["work_id"] for k, d in approved.items()
                       if d["decision"] == "approve_metadata"}
    source_collision = 0
    missing_anchor = 0
    missing_evidence = 0
    seen_passages = {}
    for row in staged or []:
        if not row.get("evidence_id") or not row.get("source_record_id"):
            missing_evidence += 1
        for key in ("left", "right"):
            side = row.get(key, {})
            passage = side.get("passage_id")
            pair = (side.get("edition_id"), side.get("passage_ref"))
            if not passage or not pair[0] or not pair[1]:
                missing_anchor += 1
            elif passage in seen_passages and seen_passages[passage] != pair:
                source_collision += 1
            else:
                seen_passages[passage] = pair
    blocked = []
    if not (12 <= len(inspected_works) <= 20):
        blocked.append("Need 12..20 distinct rights-reviewed approved work editions.")
    if len(evidence) < MIN_REVIEWED_EDGES:
        blocked.append("Need at least 100 distinct manually adjudicated observed-link examples.")
    if inventory["quarantine"] or inventory["unavailable"]:
        blocked.append("Candidate availability and version metadata quarantine need resolution.")
    if (queue is None or queue.get("fixture_only") or
            queue.get("selected_count", 0) < MIN_REVIEWED_EDGES):
        blocked.append("Need a real (nonfixture) evidence review queue of at least 100.")
    if source_collision or missing_anchor or missing_evidence:
        blocked.append("Data-quality integrity defects must be resolved.")
    if staged is None or not staged:
        blocked.append("Need an actual staged, integrity-verified source link snapshot.")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "AWAITING_HUMAN_RELEASE_SIGNOFF" if not blocked else "BLOCKED",
        "production_ga": False,
        "approved_edition_count": sum(d["decision"] == "approve_metadata"
                                      for d in approved.values()),
        "approved_distinct_works": len(inspected_works),
        "pending_edition_count": len(verified) - len(approved),
        "adjudicated_evidence_count": len(evidence),
        "queue_available_count": queue.get("selected_count", 0) if queue else 0,
        "source_link_count": len(staged) if staged else 0,
        "canonical_id_collisions": source_collision,
        "missing_passage_anchors": missing_anchor,
        "missing_evidence_ids": missing_evidence,
        "unresolved_version_rows": len(inventory["quarantine"]),
        "unavailable_candidates": len(inventory["unavailable"]),
        "manual_release_signoff_required": True,
        "human_identity_verified_cryptographically": False,
        "blocking_issues": blocked,
    }
