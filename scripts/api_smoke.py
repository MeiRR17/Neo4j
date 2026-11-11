#!/usr/bin/env python3
"""CI-only authentic Neo4j Query API + FastAPI HTTP integration, synthetic IDs.

Creates / cleans tiny fabricated metadata nodes. Never touches live source
text or prior graph nodes. Does not open any public port.
"""
from __future__ import annotations

import os
import statistics
import time
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
    passage3 = passage_id(edition, "Synthetic Multiword Work, Part 1:3")
    source = stable_id("source", "research-api-ci-fixture", "snapshot")
    author = stable_id("person", "research-api-ci-fixture", "synthetic-author")
    other_work = work_id("research-api-ci-fixture", "Synthetic Comparison Work")
    other_edition = edition_id(other_work, "CI-comparison-edition")
    other_passage = passage_id(other_edition, "Synthetic Comparison Work 1:1")
    other_author = stable_id("person", "research-api-ci-fixture", "other-author")
    evidence = evidence_id(source, "Synthetic Multiword Work, Part 1:1",
                           "synthetic-link", passage1, passage2)
    edge = stable_id("edge", "SOURCE_LINK", passage1, passage2, evidence)
    evidence2 = evidence_id(source, "Synthetic Multiword Work, Part 1:2",
                            "synthetic-link", passage2, passage3)
    edge2 = stable_id("edge", "SOURCE_LINK", passage2, passage3, evidence2)
    cross_evidence = evidence_id(source, "Synthetic Multiword Work, Part 1:3",
                                 "synthetic-cross-work", passage3, other_passage)
    cross_edge = stable_id("edge", "SOURCE_LINK", passage3, other_passage, cross_evidence)
    ids = [work, edition, passage1, passage2, passage3, source, evidence,
           evidence2, author, other_work, other_edition, other_passage,
           other_author, cross_evidence]
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
MERGE (c:Passage {id:$p3})
  ON CREATE SET c.source_ref='Synthetic Multiword Work, Part 1:3',
    c.work_id=$work, c.edition_id=$edition
MERGE (other_work:Work {id:$other_work})
  ON CREATE SET other_work.title='CI Synthetic Comparison Work',
    other_work.provider_ref='ci-other-work', other_work.provider='research-api-ci-fixture'
MERGE (other_edition:Edition {id:$other_edition})
  ON CREATE SET other_edition.version_id='CI comparison only',
    other_edition.rights_tag='TEST_METADATA_ONLY', other_edition.language='en'
MERGE (other_work)-[:HAS_EDITION {id:$other_edition_edge}]->(other_edition)
MERGE (other_passage:Passage {id:$other_passage})
  ON CREATE SET other_passage.source_ref='Synthetic Comparison Work 1:1',
    other_passage.work_id=$other_work, other_passage.edition_id=$other_edition
MERGE (other_author:Person {id:$other_author})
  ON CREATE SET other_author.display_name='Synthetic Second Author',
    other_author.date_from_year=1210, other_author.date_to_year=1260
MERGE (other_author)-[:AUTHORED {id:$other_author_edge}]->(other_work)
MERGE (author:Person {id:$author})
  ON CREATE SET author.display_name='Synthetic Fixture Author',
    author.date_from_year=1100, author.date_to_year=1160
MERGE (author)-[:AUTHORED {id:$author_edge}]->(w)
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
MERGE (ev2:Evidence {id:$evidence2})
  ON CREATE SET ev2.claim_kind='OBSERVED_SOURCE_LINK',
    ev2.review_status='unreviewed', ev2.source_ref='Synthetic Multiword Work, Part 1:2',
    ev2.source_uri='https://example.invalid/test', ev2.rights_tag='TEST_FIXTURE',
    ev2.source_record_id=$source, ev2.version_id='test-only',
    ev2.link_category='synthetic-link'
MERGE (b)-[r2:SOURCE_LINK {id:$edge2}]->(c)
  ON CREATE SET r2.evidence_id=$evidence2,
    r2.claim_kind='OBSERVED_SOURCE_LINK', r2.review_status='unreviewed'
MERGE (cross_ev:Evidence {id:$cross_evidence})
  ON CREATE SET cross_ev.claim_kind='OBSERVED_SOURCE_LINK',
    cross_ev.review_status='unreviewed',
    cross_ev.source_ref='Synthetic Multiword Work, Part 1:3',
    cross_ev.source_uri='https://example.invalid/comparison',
    cross_ev.rights_tag='TEST_FIXTURE',
    cross_ev.source_record_id=$source, cross_ev.version_id='test-only',
    cross_ev.link_category='synthetic-cross-work'
MERGE (c)-[cross:SOURCE_LINK {id:$cross_edge}]->(other_passage)
  ON CREATE SET cross.evidence_id=$cross_evidence,
    cross.claim_kind='OBSERVED_SOURCE_LINK', cross.review_status='unreviewed'
RETURN w.id AS id
"""
        edition_edge = stable_id("edge", "HAS_EDITION", work, edition, evidence)
        author_edge = stable_id("edge", "AUTHORED", author, work, evidence)
        other_edition_edge = stable_id(
            "edge", "HAS_EDITION", other_work, other_edition, cross_evidence)
        other_author_edge = stable_id(
            "edge", "AUTHORED", other_author, other_work, cross_evidence)
        admin.query(seed, {
            "work": work, "edition": edition, "edition_edge": edition_edge,
            "p1": passage1, "p2": passage2, "p3": passage3,
            "source": source, "evidence": evidence, "edge": edge,
            "evidence2": evidence2, "edge2": edge2,
            "author": author, "author_edge": author_edge,
            "other_work": other_work, "other_edition": other_edition,
            "other_passage": other_passage, "other_author": other_author,
            "other_edition_edge": other_edition_edge,
            "other_author_edge": other_author_edge,
            "cross_evidence": cross_evidence, "cross_edge": cross_edge,
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
            # v0.9.1: exercise both fixed path Cypher operations in real,
            # disposable CI Neo4j, not only mocked graph rows.
            direct = http.get("/v1/graph/evidence-path", params={
                "source_id": passage1, "target_id": passage2,
            }, headers=headers)
            verify(direct, 200)
            if (direct.json()["observed_shortest_hops"] != 1 or
                direct.json()["paths"][0]["edges"][0]["evidence_id"] != evidence):
                raise RuntimeError("Direct observed path lost exact evidence.")
            two_hop = http.get("/v1/graph/evidence-path", params={
                "source_id": passage1, "target_id": passage3,
            }, headers=headers)
            verify(two_hop, 200)
            if (two_hop.json()["observed_shortest_hops"] != 2 or
                [item["evidence_id"] for item in two_hop.json()["paths"][0]["edges"]]
                    != [evidence, evidence2]):
                raise RuntimeError("Two-hop path lost independent evidence chain.")
            reverse = http.get("/v1/graph/evidence-path", params={
                "source_id": passage3, "target_id": passage1,
            }, headers=headers)
            verify(reverse, 200)
            if reverse.json()["paths"] or reverse.json()["observed_shortest_hops"] is not None:
                raise RuntimeError("Directed path incorrectly traversed backwards.")
            # v0.9.2: fixed bounded frequency and recorded-author metadata
            # checks against the same isolated synthetic Neo4j fixtures.
            frequency = http.get("/v1/analysis/metrics/link-frequency", params={
                "passage_id": passage2,
            }, headers=headers)
            verify(frequency, 200)
            counts = frequency.json()
            if (counts["observed_link_denominator"] != 2 or
                    counts["incoming_observed_links"] != 1 or
                    counts["outgoing_observed_links"] != 1 or
                    counts["pending_status_links"] != 2 or
                    counts["joint_approved_status_fraction"] != 0.0 or
                    counts["whole_graph_centrality_verified"] is not False):
                raise RuntimeError("Synthetic link-frequency denominator mismatch.")
            years = http.get(
                "/v1/analysis/chronology/author-lifetimes", params={
                    "source_id": passage1, "target_id": passage2,
                }, headers=headers)
            verify(years, 200)
            chronology = years.json()
            if (chronology["metadata_status"] != "same_work" or
                    chronology["author_lifetime_relation"] != "unknown" or
                    [a["id"] for a in chronology["source_authors"]] != [author] or
                    chronology["historical_influence_proven"] is not False):
                raise RuntimeError("Synthetic author chronology metadata invalid.")
            # v0.9.3: real Neo4j read-only Work and author comparison.
            comparison = http.get("/v1/analysis/works/compare", params={
                "left_work_id": work, "right_work_id": other_work, "limit": 2,
            }, headers=headers)
            verify(comparison, 200)
            report = comparison.json()
            forward_links = report["left_to_right"]["links"]
            if (report["left_work"]["author_sample"][0]["id"] != author or
                    report["right_work"]["author_sample"][0]["id"] != other_author or
                    report["author_id_overlap_status"] != "different_author_ids_observed" or
                    report["left_to_right"]["observed_window_denominator"] != 1 or
                    report["right_to_left"]["observed_window_denominator"] != 0 or
                    len(forward_links) != 1 or
                    forward_links[0]["edge_id"] != cross_edge or
                    forward_links[0]["evidence_id"] != cross_evidence or
                    forward_links[0]["source_passage_id"] != passage3 or
                    forward_links[0]["target_passage_id"] != other_passage or
                    report["historical_influence_proven"] is not False or
                    report["research_release_status"] != "HOLD"):
                raise RuntimeError("Bounded Work comparison lost source evidence or direction.")
            backwards = http.get("/v1/analysis/works/compare", params={
                "left_work_id": other_work, "right_work_id": work,
            }, headers=headers)
            verify(backwards, 200)
            if (backwards.json()["left_to_right"]["observed_window_denominator"] != 0 or
                    backwards.json()["right_to_left"]["observed_window_denominator"] != 1):
                raise RuntimeError("Work comparison reversed source direction.")
            # v0.9.9: authenticated directed and cursor-filtered link audit
            # against the disposable live Neo4j fixture. No population claim.
            audit_url = "/v1/analysis/works/links/audit"
            params = {
                "source_work_id": work,
                "target_work_id": other_work,
                "limit": 1,
            }
            first_page = http.get(audit_url, params=params, headers=headers)
            verify(first_page, 200)
            page = first_page.json()
            if (page["schema_version"] != "0.9.9" or
                    page["observed_window_denominator"] != 1 or
                    page["links"][0]["edge_id"] != cross_edge or
                    page["links"][0]["evidence_id"] != cross_evidence or
                    page["has_more"] is not False or
                    page["next_cursor"] is not None or
                    page["snapshot_consistency_verified"] is not False or
                    page["research_release_status"] != "HOLD"):
                raise RuntimeError("Live Work-link audit lost Evidence or bounds.")
            past_cursor = http.get(
                audit_url, params={**params, "cursor": cross_edge},
                headers=headers)
            verify(past_cursor, 200)
            if (past_cursor.json()["links"] or
                    past_cursor.json()["observed_window_denominator"] != 0):
                raise RuntimeError("Audit cursor did not exclude previous edge.")
            opposite = http.get(
                audit_url, params={
                    "source_work_id": other_work,
                    "target_work_id": work, "limit": 1,
                }, headers=headers)
            verify(opposite, 200)
            if opposite.json()["links"]:
                raise RuntimeError("Work-link audit silently reversed direction.")
            for invalid in (
                {**params, "cursor": other_work},
                {**params, "rights": "approved"},
            ):
                verify(http.get(audit_url, params=invalid, headers=headers), 422)
            # v0.9.4: repeat a fixed metadata-only comparison 20 times on
            # the disposable two-Work fixture; this measures only this
            # synthetic runner and does not certify real-corpus performance.
            sample_ms = []
            comparison_digest = None
            template_digest = None
            for _ in range(20):
                started = time.perf_counter_ns()
                receipt = http.get(
                    "/v1/analysis/works/compare/receipt",
                    params={"left_work_id": work, "right_work_id": other_work,
                            "limit": 2},
                    headers=headers,
                )
                sample_ms.append((time.perf_counter_ns() - started) / 1_000_000)
                verify(receipt, 200)
                observed = receipt.json()
                if (observed["schema_version"] != "0.9.4" or
                        observed["observed_link_count"] != 1 or
                        observed["receipt_digitally_signed"] is not False or
                        observed["comparison_snapshot_verified"] is not False or
                        observed["research_release_status"] != "HOLD"):
                    raise RuntimeError("Synthetic comparison receipt scope invalid.")
                current_digest = observed["observation_sha256"]
                current_template = observed["fixed_query_templates_sha256"]
                if comparison_digest is not None and (
                        comparison_digest != current_digest or
                        template_digest != current_template):
                    raise RuntimeError("Identical synthetic Work sample changed digest.")
                comparison_digest, template_digest = current_digest, current_template
            p50_ms = statistics.median(sample_ms)
            p95_ms = sorted(sample_ms)[18]  # nearest-rank p95 at n=20
            print("[OBSERVED synthetic fixture only] 2 Works, 2 authors, "
                  "1 direct cross-Work link, 20 repeated receipts, "
                  f"HTTP p50={p50_ms:.1f}ms, p95={p95_ms:.1f}ms. "
                  "No production performance or snapshot claim.")
            status = http.get("/v1/data/status", headers=headers)
            verify(status, 200)
            if status.json()["human_quality_release_approved"] is not False:
                raise RuntimeError("Research corpus was falsely approved.")
        print("[OK] Authenticated FastAPI + real Neo4j: work, edition, "
              "passage, evidence, neighborhood, 1/2-hop paths, frequency/chronology, Work comparisons, keyset link audit, receipt replay, status and negative access controls.")
    finally:
        admin.query("MATCH (n) WHERE n.id IN $ids DETACH DELETE n", {"ids": ids})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
