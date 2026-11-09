#!/usr/bin/env python3
"""CI-only authentic Neo4j Query API + FastAPI HTTP integration, synthetic IDs.

Creates / cleans tiny fabricated metadata nodes. Never touches live source
text or prior graph nodes. Does not open any public port.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from research_graph.ontology import edition_id, evidence_id, passage_id, stable_id, work_id
from scripts.bootstrap import DEFAULT_SECRET_PATH
from scripts.migrate import LocalQueryClient
from services.research_api.app import create_app
from services.research_api.config import TOKEN_PATH, bootstrap_token, load_token


def verify(response, expected):
    if response.status_code != expected:
        raise RuntimeError(
            f"API contract HTTP {response.status_code}, expected {expected}: "
            f"path={response.request.url.path}"
        )


def main() -> int:
    if os.getenv("CI") != "true":
        print("[BLOCKED] API integration fixture must run in isolated CI.")
        return 2
    bootstrap_token()
    admin = LocalQueryClient("http://127.0.0.1:7474", DEFAULT_SECRET_PATH)
    work = work_id("research-api-ci-fixture", "Synthetic Multiword Work")
    edition = edition_id(work, "CI-edition")
    passage1 = passage_id(edition, "Synthetic Multiword Work, Part 1:1")
    passage2 = passage_id(edition, "Synthetic Multiword Work, Part 1:2")
    source = stable_id("source", "research-api-ci-fixture", "snapshot")
    evidence = evidence_id(source, "Synthetic Multiword Work, Part 1:1",
                           "synthetic-link", passage1, passage2)
    edge = stable_id("edge", "SOURCE_LINK", passage1, passage2, evidence)
    ids = [work, edition, passage1, passage2, source, evidence]
    try:
        seed = """
MERGE (w:Work {id:$work})
  ON CREATE SET w.title='CI Synthetic Multiword Work',
    w.provider_ref='ci-work', w.provider='research-api-ci-fixture'
MERGE (ed:Edition {id:$edition})
  ON CREATE SET ed.version_id='CI only',
    ed.rights_tag='TEST_METADATA_ONLY', ed.language='en'
MERGE (w)-[:HAS_EDITION {id:$edition_edge}]->(ed)
MERGE (a:Passage {id:$p1})
  ON CREATE SET a.source_ref='Synthetic Multiword Work, Part 1:1',
    a.work_id=$work, a.edition_id=$edition
MERGE (b:Passage {id:$p2})
  ON CREATE SET b.source_ref='Synthetic Multiword Work, Part 1:2',
    b.work_id=$work, b.edition_id=$edition
MERGE (src:SourceRecord {id:$source})
  ON CREATE SET src.provider='fixture', src.version_id='test-only',
    src.rights_tag='TEST_FIXTURE', src.source_uri='https://example.invalid/test'
MERGE (ev:Evidence {id:$evidence})
  ON CREATE SET ev.claim_kind='OBSERVED_SOURCE_LINK',
    ev.review_status='unreviewed', ev.source_ref='Synthetic Multiword Work, Part 1:1',
    ev.source_uri='https://example.invalid/test', ev.rights_tag='TEST_FIXTURE',
    ev.source_record_id=$source, ev.version_id='test-only',
    ev.link_category='synthetic-link'
MERGE (a)-[r:SOURCE_LINK {id:$edge}]->(b)
  ON CREATE SET r.evidence_id=$evidence,
    r.claim_kind='OBSERVED_SOURCE_LINK', r.review_status='unreviewed'
RETURN w.id AS id
"""
        edition_edge = stable_id("edge", "HAS_EDITION", work, edition, evidence)
        admin.query(seed, {
            "work": work, "edition": edition, "edition_edge": edition_edge,
            "p1": passage1, "p2": passage2, "source": source,
            "evidence": evidence, "edge": edge,
        })
        with TestClient(create_app()) as http:
            no_auth = http.get("/v1/works")
            verify(no_auth, 401)
            headers = {"Authorization": "Bearer " + load_token()}
            verify(http.get("/health/ready"), 200)
            response = http.get("/v1/works", params={
                "query": "CI Synthetic Multiword Work",
            }, headers=headers)
            verify(response, 200)
            if not any(item["id"] == work for item in response.json()["items"]):
                raise RuntimeError("Synthetic work absent from listing.")
            detail = http.get(f"/v1/works/{work}", headers=headers)
            verify(detail, 200)
            if detail.json()["edition_count"] != 1:
                raise RuntimeError("Edition metadata relation not retrieved.")
            p = http.get(f"/v1/passages/{passage1}", headers=headers)
            verify(p, 200)
            if p.json()["excerpt"] is not None or p.json()["source_ref"] != "Synthetic Multiword Work, Part 1:1":
                raise RuntimeError("Passage text or canonical ref contract violated.")
            links = http.get("/v1/links", params={"passage_id": passage1}, headers=headers)
            verify(links, 200)
            if not any(x["id"] == edge and x["evidence_id"] == evidence
                       for x in links.json()["items"]):
                raise RuntimeError("Synthetic evidence link missing.")
            graph = http.get("/v1/graph/neighborhood", params={
                "entity_id": passage1, "edge_types": "SOURCE_LINK", "depth": 1
            }, headers=headers)
            verify(graph, 200)
            if not graph.json()["paths"]:
                raise RuntimeError("Bounded graph query could not locate fixture edge.")
            trails = [
                item for path in graph.json()["paths"]
                for item in path["edges"]
                if item["id"] == edge
            ]
            if not trails or any(
                x["evidence_id"] != evidence
                or x["source_ref"] != "Synthetic Multiword Work, Part 1:1"
                or x["source_uri"] != "https://example.invalid/test"
                or x["rights_tag"] != "TEST_FIXTURE"
                or x["evidence_review_status"] != "unreviewed"
                for x in trails
            ):
                raise RuntimeError("Exact evidence provenance lost from graph path.")
            verify(http.get("/v1/graph/neighborhood", params={
                "entity_id": passage1, "depth": 3
            }, headers=headers), 422)
            status = http.get("/v1/data/status", headers=headers)
            verify(status, 200)
            if status.json()["human_quality_release_approved"] is not False:
                raise RuntimeError("Research corpus was falsely approved.")
        print("[OK] Authenticated FastAPI + real Neo4j: work, edition, "
              "passage, evidence, neighborhood, status and negative access controls.")
    finally:
        admin.query("MATCH (n) WHERE n.id IN $ids DETACH DELETE n", {"ids": ids})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
