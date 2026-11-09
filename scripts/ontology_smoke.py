#!/usr/bin/env python3
"""Insert/recheck/delete purely SYNTHETIC fixtures in a disposable local DB.

Never treats fixtures as authentic Sefaria data. Requires explicit opt-in and
refuses non-CI execution without a local developer override.
"""

from __future__ import annotations

import argparse
import os

from migrate import LocalQueryClient
from bootstrap import DEFAULT_SECRET_PATH
from research_path import install_research_path
install_research_path()

from research_graph.ontology import (  # noqa: E402
    EvidenceRecord, GraphEdge, edge_upsert_query, edition_id, evidence_id,
    passage_id, stable_id, work_id,
)


def ensure(client: LocalQueryClient, query: str, params: dict, expected: list) -> None:
    actual = client.query(query, params)
    if actual != expected:
        raise RuntimeError(f"Unexpected synthetic fixture query result (rows={len(actual)}).")


def run(client: LocalQueryClient) -> None:
    # Completely synthetic entities, never real authors or Sefaria source records.
    a = work_id("fixture-provider", "work-1")
    b = work_id("fixture-provider", "work-2")
    ed1, ed2 = edition_id(a, "edition-one"), edition_id(b, "edition-one")
    ref1 = "Fixture Multiword Work, Chapter 1:1"
    ref2 = "Fixture Multiword Work, Chapter 2:1"
    p1, p2 = passage_id(ed1, ref1), passage_id(ed2, ref2)
    s = stable_id("source", "fixture-provider", "fixture-record-1")
    ev = evidence_id(s, ref1, "SyntheticLink", p1, p2)
    record = EvidenceRecord(ev, s, ref1, "https://example.invalid/fixture",
                            "fixture-version", "TEST_FIXTURE", "OBSERVED_SOURCE_LINK",
                            link_category="SyntheticLink")
    edge = GraphEdge("SOURCE_LINK", p1, p2, ev, "OBSERVED_SOURCE_LINK")
    ids = [a, b, ed1, ed2, p1, p2, s, ev]
    try:
        for id_value, label, props in (
            (a, "Work", {"title": "Fixture Multiword Work", "provider_ref": "work-1"}),
            (b, "Work", {"title": "Fixture Multiword Work", "provider_ref": "work-2"}),
            (ed1, "Edition", {"version_id": "edition-one"}),
            (ed2, "Edition", {"version_id": "edition-one"}),
            (p1, "Passage", {"source_ref": ref1, "edition_id": ed1, "work_id": a}),
            (p2, "Passage", {"source_ref": ref2, "edition_id": ed2, "work_id": b}),
            (s, "SourceRecord", {"provider": "fixture-provider"}),
            (ev, "Evidence", record.properties()),
        ):
            ensure(
                client,
                f"MERGE (n:{label} {{id: $id}}) ON CREATE SET n += $properties "
                "RETURN n.id AS id",
                {"id": id_value, "properties": props},
                [[id_value]],
            )
        for _ in range(2):
            ensure(client, edge_upsert_query("SOURCE_LINK"), edge.parameters(), [[edge.id]])
        ensure(
            client,
            "MATCH (a:Work) WHERE a.id IN $ids RETURN count(a) AS count",
            {"ids": [a, b]}, [[2]],
        )
        ensure(
            client,
            "MATCH (p:Passage)-[r:SOURCE_LINK]->(q:Passage) "
            "WHERE r.id = $id RETURN r.claim_kind AS kind, "
            "r.evidence_id AS evidence, r.review_status AS review",
            {"id": edge.id}, [["OBSERVED_SOURCE_LINK", ev, "unreviewed"]],
        )
    finally:
        # Exact ID set was locally generated for this synthetic run.
        client.query("MATCH (n) WHERE n.id IN $ids DETACH DELETE n", {"ids": ids})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-synthetic", action="store_true")
    args = parser.parse_args()
    if not args.allow_synthetic:
        print("[FAIL] Explicit --allow-synthetic is required.")
        return 1
    if os.getenv("CI") != "true" and os.getenv("ALLOW_LOCAL_SYNTHETIC_FIXTURE") != "1":
        print("[FAIL] Use only isolated CI or set ALLOW_LOCAL_SYNTHETIC_FIXTURE=1 deliberately.")
        return 1
    try:
        run(LocalQueryClient("http://127.0.0.1:7474", DEFAULT_SECRET_PATH))
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"[FAIL] Ontology smoke: {exc}")
        return 1
    print("[OK] Canonical fixture refs, two distinct works, evidence-linked edge, "
          "idempotent upsert and cleanup.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
