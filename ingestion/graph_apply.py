"""Explicit metadata-only import into isolated, local Neo4j.

Refuses source text, unreviewed rights promotion, altered plans and missing
migrations. Reruns are idempotent. No DvirOS frontend or public DB access.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterator

from ingestion.sefaria_links import (
    SCHEMA_VERSION, RIGHTS_TAG, EDITION_SENTINEL, Link, approved_source_url,
    file_sha256, staged_record,
)
from research_graph.ontology import GraphEdge
from scripts.migrate import LocalQueryClient, applied_checksum, load_migrations

BATCH_SIZE = 100
UPSERT_CYPHER = """
UNWIND $batch AS row
MERGE (src:SourceRecord {id: row.source_record_id})
  ON CREATE SET src.provider = 'sefaria', src.source_uri = row.source_uri,
    src.checksum_sha256 = row.snapshot_sha256,
    src.version_id = row.snapshot_sha256, src.rights_tag = row.rights_tag
MERGE (wa:Work {id: row.left.work_id})
  ON CREATE SET wa.provider = 'sefaria', wa.provider_ref = row.left.work_ref,
    wa.title = row.left.work_ref
MERGE (wb:Work {id: row.right.work_id})
  ON CREATE SET wb.provider = 'sefaria', wb.provider_ref = row.right.work_ref,
    wb.title = row.right.work_ref
MERGE (ea:Edition {id: row.left.edition_id})
  ON CREATE SET ea.work_id = row.left.work_id,
    ea.version_id = 'UNVERSIONED_LINK_METADATA_ONLY', ea.rights_tag = row.rights_tag
MERGE (eb:Edition {id: row.right.edition_id})
  ON CREATE SET eb.work_id = row.right.work_id,
    eb.version_id = 'UNVERSIONED_LINK_METADATA_ONLY', eb.rights_tag = row.rights_tag
MERGE (pa:Passage {id: row.left.passage_id})
  ON CREATE SET pa.source_ref = row.left.passage_ref,
    pa.work_id = row.left.work_id, pa.edition_id = row.left.edition_id
MERGE (pb:Passage {id: row.right.passage_id})
  ON CREATE SET pb.source_ref = row.right.passage_ref,
    pb.work_id = row.right.work_id, pb.edition_id = row.right.edition_id
MERGE (ev:Evidence {id: row.evidence_id})
  ON CREATE SET ev.source_record_id = row.source_record_id,
    ev.source_ref = row.left.passage_ref,
    ev.source_uri = row.source_uri, ev.version_id = row.snapshot_sha256,
    ev.rights_tag = row.rights_tag, ev.claim_kind = 'OBSERVED_SOURCE_LINK',
    ev.review_status = 'unreviewed', ev.link_category = row.link_type_raw,
    ev.limitation_note = 'Link direction, edition, and scholarly influence not established'
MERGE (src)-[provenance:HAS_EVIDENCE {id: row.source_evidence_edge_id}]->(ev)
  ON CREATE SET provenance.evidence_id = row.evidence_id,
    provenance.claim_kind = 'OBSERVED_SOURCE_LINK',
    provenance.review_status = 'unreviewed'
MERGE (pa)-[rel:SOURCE_LINK {id: row.edge_id}]->(pb)
  ON CREATE SET rel.evidence_id = row.evidence_id,
    rel.claim_kind = 'OBSERVED_SOURCE_LINK', rel.review_status = 'unreviewed',
    rel.orientation = 'not_asserted'
RETURN count(rel) AS count
""".strip()

# Enrich metadata-only stage rows with a deterministic provenance edge ID.
def add_source_evidence_edge(record: dict) -> dict:
    from research_graph.ontology import stable_id
    record = dict(record)
    record["source_evidence_edge_id"] = stable_id(
        "edge", "HAS_EVIDENCE", record["source_record_id"],
        record["evidence_id"], record["evidence_id"]
    )
    return record


def load_verified_plan(directory: Path, *, allow_fixture: bool = False) -> tuple[dict, list[dict]]:
    directory = Path(directory)
    manifest_path = directory / "manifest.json"
    rows_path = directory / "links.jsonl"
    quarantine_path = directory / "quarantine.jsonl"
    if any(p.is_symlink() for p in (directory, manifest_path, rows_path, quarantine_path)):
        raise ValueError("Refusing symlinked staging artifacts.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported ingestion plan version.")
    if manifest.get("fixture_only"):
        if not (allow_fixture and os.getenv("CI") == "true"):
            raise ValueError("Fixture import only permitted in isolated CI.")
    else:
        approved_source_url(manifest.get("source_uri"))
    if manifest.get("rights_tag") != RIGHTS_TAG or manifest.get("text_rights_verified") is not False:
        raise ValueError("Rights review must remain explicitly pending.")
    if manifest.get("source_link_is_direct_citation") is not False or manifest.get("claimed_citation_direction") is not False:
        raise ValueError("Cannot upgrade observational metadata to a citation claim.")
    if manifest.get("counts", {}).get("quarantined") != 0:
        raise ValueError("Metadata apply requires a zero-quarantine plan.")
    if manifest["links_sha256"] != file_sha256(rows_path) or manifest["quarantine_sha256"] != file_sha256(quarantine_path):
        raise ValueError("Staged artifacts differ from their manifest checksums.")
    if quarantine_path.stat().st_size != 0:
        raise ValueError("Quarantine must be empty before metadata apply.")
    planned = []
    seen = set()
    with rows_path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("source_record_id") != manifest["source_record_id"] or row.get("snapshot_sha256") != manifest["snapshot_sha256"]:
                raise ValueError("Source provenance mismatch in staged record.")
            if row.get("source_uri") != manifest["source_uri"] or row.get("rights_tag") != RIGHTS_TAG:
                raise ValueError("Rights/source mismatch in staged record.")
            if row.get("schema_version") != SCHEMA_VERSION or row.get("orientation") != "not_asserted":
                raise ValueError("Unreviewed link contract was changed.")
            if row.get("claim_kind") != "OBSERVED_SOURCE_LINK" or row.get("review_status") != "unreviewed":
                raise ValueError("Only unreviewed observed links may be imported.")
            left, right = row["left"], row["right"]
            link = Link(left["passage_ref"], right["passage_ref"], left["work_ref"],
                        right["work_ref"], row["link_type_raw"],
                        left.get("category", ""), right.get("category", ""))
            reconstructed = staged_record(link, manifest["source_record_id"],
                                          manifest["source_uri"], manifest["snapshot_sha256"])
            if row != reconstructed:
                raise ValueError("Tampered or noncanonical staged record.")
            edge = GraphEdge("SOURCE_LINK", left["passage_id"], right["passage_id"],
                             row["evidence_id"], row["claim_kind"], row["review_status"])
            if edge.id != row["edge_id"] or row["edge_id"] in seen:
                raise ValueError("Invalid or duplicate graph edge.")
            seen.add(edge.id)
            if len(seen) > 50_000:
                raise ValueError("v0.3 metadata pilot limit is 50,000 unique edges per plan.")
            planned.append(add_source_evidence_edge(row))
    if len(planned) != manifest.get("counts", {}).get("selected"):
        raise ValueError("Staged row count differs from manifest.")
    return manifest, planned


def apply_metadata(directory: Path, client: LocalQueryClient, *,
                   allow_fixture: bool = False) -> int:
    manifest, planned = load_verified_plan(directory, allow_fixture=allow_fixture)
    # Fail closed when schema was not applied or its checksum changed.
    for migration in load_migrations():
        if applied_checksum(client, migration.id) != migration.checksum:
            raise RuntimeError("Apply and validate graph schema migrations first.")
    total = 0
    for start in range(0, len(planned), BATCH_SIZE):
        part = planned[start:start + BATCH_SIZE]
        result = client.query(UPSERT_CYPHER, {"batch": part})
        if result != [[len(part)]]:
            raise RuntimeError("Metadata-only Neo4j import did not return all rows.")
        total += len(part)
    print(f"[OK] Imported {total} unreviewed Sefaria link metadata edges; no source texts.")
    return total
