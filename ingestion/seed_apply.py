"""Upsert human rights-reviewed *metadata* for curated editions into Neo4j.

No full texts, quotations, research claims or source excerpts are written.
This uses the v0.2 evidence ontology without promoting proposed graph links
to scholarly facts or general text redistribution permission.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from ingestion.seed_catalog import checksum
from ingestion.seed_quality import validate_rights_decisions, verify_inventory
from research_graph.ontology import stable_id
from scripts.migrate import LocalQueryClient, applied_checksum, load_migrations

BATCH_SIZE = 25
METADATA_CYPHER = """
UNWIND $batch AS row
MERGE (s:SourceRecord {id: row.source_record_id})
  ON CREATE SET s.provider = 'sefaria',
    s.source_uri = row.metadata_source, s.version_id = row.source_sha256,
    s.checksum_sha256 = row.source_sha256,
    s.rights_tag = 'EDITION_METADATA_ONLY'
MERGE (w:Work {id: row.work_id})
  ON CREATE SET w.provider = 'sefaria',
    w.provider_ref = row.index_title, w.title = row.index_title
MERGE (ed:Edition {id: row.edition_id})
  ON CREATE SET ed.work_id = row.work_id,
    ed.version_id = row.version_title, ed.language = row.language,
    ed.license_raw = row.license_raw, ed.rights_tag = row.license_raw,
    ed.version_source = row.version_source,
    ed.rights_review_status = 'METADATA_ONLY_REVIEWED',
    ed.rights_reviewer_id = row.reviewer_id,
    ed.rights_reviewed_at = row.reviewed_at,
    ed.attribution = row.attribution,
    ed.allowed_text_redistribution = false
MERGE (ev:Evidence {id: row.evidence_id})
  ON CREATE SET ev.source_record_id = row.source_record_id,
    ev.source_ref = row.index_title, ev.source_uri = row.metadata_source,
    ev.version_id = row.source_sha256,
    ev.rights_tag = 'EDITION_METADATA_ONLY', ev.claim_kind = 'OBSERVED_SOURCE_LINK',
    ev.review_status = 'unreviewed',
    ev.limitation_note = 'Edition listing and license metadata; no full-text permission inferred'
MERGE (s)-[e:HAS_EVIDENCE {id: row.provenance_edge_id}]->(ev)
  ON CREATE SET e.evidence_id = row.evidence_id,
    e.claim_kind = 'OBSERVED_SOURCE_LINK', e.review_status = 'unreviewed'
MERGE (w)-[rel:HAS_EDITION {id: row.edition_edge_id}]->(ed)
  ON CREATE SET rel.evidence_id = row.evidence_id,
    rel.claim_kind = 'OBSERVED_SOURCE_LINK', rel.review_status = 'unreviewed'
RETURN count(rel) AS count
""".strip()


def approved_rows(inventory: dict, decisions: list[dict]) -> list[dict]:
    indexed = verify_inventory(inventory)
    reviewed = validate_rights_decisions(inventory, decisions)
    snapshots = {record["index_title"]: record for record in inventory["source_snapshots"]}
    result = []
    for eid, decision in sorted(reviewed.items()):
        if decision["decision"] != "approve_metadata":
            continue
        version = indexed[eid]
        src = snapshots[version["index_title"]]
        source_id = src["source_record_id"]
        evidence = stable_id("evidence", source_id, version["work_id"],
                             eid, "VERSION_LISTING")
        result.append({
            **version,
            "source_record_id": source_id, "source_sha256": src["response_sha256"],
            "evidence_id": evidence,
            "provenance_edge_id": stable_id(
                "edge", "HAS_EVIDENCE", source_id, evidence, evidence),
            "edition_edge_id": stable_id(
                "edge", "HAS_EDITION", version["work_id"], eid, evidence),
            "reviewer_id": decision["reviewer_id"],
            "reviewed_at": decision["reviewed_at"],
            "attribution": decision["attribution"],
            "rights_evidence_uri": decision["rights_evidence_uri"],
        })
    return result


def apply_approved_editions(inventory: dict, decisions: list[dict],
                            client: LocalQueryClient, *, fixture: bool = False) -> int:
    if fixture and os.getenv("CI") != "true":
        raise ValueError("Synthetic approval test runs only inside isolated CI.")
    if inventory.get("fixture_only") and not fixture:
        raise ValueError("Synthetic inventory must not be imported as real data.")
    if not fixture and inventory.get("fixture_only"):
        raise ValueError("Refusing synthetic inventory.")
    rows = approved_rows(inventory, decisions)
    if not rows:
        raise ValueError("No human-reviewed, metadata-approved editions supplied.")
    for migration in load_migrations():
        if applied_checksum(client, migration.id) != migration.checksum:
            raise RuntimeError("Graph migrations are missing or have drifted.")
    # Protect prior persisted rights statements against silent license changes.
    for record in rows:
        existing = client.query(
            "MATCH (ed:Edition {id: $id}) "
            "RETURN ed.license_raw AS license, ed.rights_review_status AS status",
            {"id": record["edition_id"]},
        )
        if existing and existing != [[record["license_raw"], "METADATA_ONLY_REVIEWED"]]:
            raise RuntimeError("Conflicting existing edition metadata; manual reconciliation required.")
    total = 0
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start:start + BATCH_SIZE]
        result = client.query(METADATA_CYPHER, {"batch": batch})
        if result != [[len(batch)]]:
            raise RuntimeError("Edition metadata import failed to process whole batch.")
        total += len(batch)
    return total
