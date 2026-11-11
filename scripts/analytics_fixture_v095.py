"""v0.9.5 synthetic-only, immutable-in-scope analytical benchmark cases.

Build stable, deterministic identities. All payloads are fabricated labels,
not historical works or citations. This file never contacts a database.
"""
from __future__ import annotations

from hashlib import sha256
import json

from research_graph.ontology import stable_id

SIZES = (32, 128)
NAMESPACE = "isolated-ci-analytics-cost-v095"
SEED_VERSION = "synthetic-v0.9.5-1"


def fixture_case(size: int) -> dict:
    if type(size) is not int or size not in SIZES:
        raise ValueError("Only documented synthetic benchmark sizes are accepted.")
    left = stable_id("work", NAMESPACE, str(size), "left")
    right = stable_id("work", NAMESPACE, str(size), "right")
    authors = [
        stable_id("person", NAMESPACE, str(size), "author-left"),
        stable_id("person", NAMESPACE, str(size), "author-right"),
    ]
    relationships = [
        stable_id("edge", NAMESPACE, str(size), "authored-left"),
        stable_id("edge", NAMESPACE, str(size), "authored-right"),
    ]
    edges = []
    for i in range(size):
        forward = i % 2 == 0
        source_work, target_work = (left, right) if forward else (right, left)
        source_passage = stable_id("passage", NAMESPACE, str(size), str(i), "source")
        target_passage = stable_id("passage", NAMESPACE, str(size), str(i), "target")
        evidence = stable_id("evidence", NAMESPACE, str(size), str(i))
        link = stable_id("edge", NAMESPACE, str(size), str(i), "link")
        edges.append({
            "source_work_id": source_work,
            "target_work_id": target_work,
            "source_passage_id": source_passage,
            "target_passage_id": target_passage,
            "evidence_id": evidence,
            "edge_id": link,
            "source_ref": f"SYNTHETIC-{size}-{i:04d}/source",
            "target_ref": f"SYNTHETIC-{size}-{i:04d}/target",
        })
    case = {
        "seed_version": SEED_VERSION,
        "size": size,
        "left_work_id": left,
        "right_work_id": right,
        "author_ids": authors,
        "authored_edge_ids": relationships,
        "edges": edges,
    }
    serialized = json.dumps(
        case, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    case["fixture_sha256"] = sha256(serialized).hexdigest()
    return case


def exact_fixture_ids(case: dict) -> list[str]:
    ids = [
        case["left_work_id"], case["right_work_id"],
        *case["author_ids"],
    ]
    for edge in case["edges"]:
        ids.extend((edge["source_passage_id"], edge["target_passage_id"],
                    edge["evidence_id"]))
    if len(ids) != len(set(ids)):
        raise ValueError("Fixture generated colliding node IDs.")
    return ids
