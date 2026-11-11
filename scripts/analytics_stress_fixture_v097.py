"""v0.9.7 controlled 256/512-edge disjoint and high-fanout graph fixtures.

All entities are synthetic, stable and namespaced by size and topology.
Each hub case shares one source Passage across half its outgoing SOURCE_LINKs;
the other passages and all Evidence nodes remain distinct. No source texts.
This builder performs no network or database operations.
"""
from __future__ import annotations

from hashlib import sha256
import json

from research_graph.ontology import stable_id

TOPOLOGIES = ("disjoint", "hub")
SIZES = (256, 512)
CASES = tuple(f"{kind}-{size}" for size in SIZES for kind in TOPOLOGIES)
NAMESPACE = "isolated-v097-graph-cost"
VERSION = "synthetic-v0.9.7-1"
MAX_NODE_IDS = 1600


def stress_case(name: str) -> dict:
    if not isinstance(name, str) or name not in CASES:
        raise ValueError("Only fixed v0.9.7 synthetic cases are allowed.")
    kind, numeric_size = name.split("-")
    size = int(numeric_size)
    left = stable_id("work", NAMESPACE, name, "left")
    right = stable_id("work", NAMESPACE, name, "right")
    authors = [
        stable_id("person", NAMESPACE, name, "left"),
        stable_id("person", NAMESPACE, name, "right"),
    ]
    authored = [
        stable_id("edge", NAMESPACE, name, "authored-left"),
        stable_id("edge", NAMESPACE, name, "authored-right"),
    ]
    hub = stable_id("passage", NAMESPACE, name, "hub-left") if kind == "hub" else None
    edges = []
    for index in range(size):
        forward = index % 2 == 0
        source_work, target_work = (left, right) if forward else (right, left)
        source_passage = (
            hub if hub is not None and forward else
            stable_id("passage", NAMESPACE, name, str(index), "source")
        )
        target_passage = stable_id("passage", NAMESPACE, name, str(index), "target")
        reference = (
            f"SYNTHETIC-{name}-SHARED-SOURCE"
            if hub is not None and forward else
            f"SYNTHETIC-{name}-{index:04d}-SOURCE"
        )
        edges.append({
            "source_work_id": source_work,
            "target_work_id": target_work,
            "source_passage_id": source_passage,
            "target_passage_id": target_passage,
            "evidence_id": stable_id("evidence", NAMESPACE, name, str(index)),
            "edge_id": stable_id("edge", NAMESPACE, name, str(index), "link"),
            "source_ref": reference,
            "target_ref": f"SYNTHETIC-{name}-{index:04d}-TARGET",
        })
    case = {
        "name": name,
        "version": VERSION,
        "size": size,
        "topology": kind,
        "left_work_id": left,
        "right_work_id": right,
        "author_ids": authors,
        "authored_edge_ids": authored,
        "hub_passage_id": hub,
        "max_source_out_degree": size // 2 if hub is not None else 1,
        "incident_rows_expected": 51 if hub is not None else 1,
        "edges": edges,
    }
    ids = fixture_ids(case)
    case["synthetic_passage_count"] = sum(value.startswith("passage:") for value in ids)
    canonical = json.dumps(
        case, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    case["fixture_sha256"] = sha256(canonical).hexdigest()
    return case


def fixture_ids(case: dict) -> list[str]:
    ids = {case["left_work_id"], case["right_work_id"], *case["author_ids"]}
    edges = case["edges"]
    if len(edges) != case["size"] or len(edges) > max(SIZES):
        raise ValueError("Unexpected synthetic relationship population.")
    edge_ids, evidence_ids = set(), set()
    for row in edges:
        edge_ids.add(row["edge_id"])
        evidence_ids.add(row["evidence_id"])
        ids.update((row["source_passage_id"], row["target_passage_id"],
                    row["evidence_id"]))
    if len(edge_ids) != len(edges) or len(evidence_ids) != len(edges):
        raise ValueError("Repeated synthetic edge or Evidence identity.")
    if len(ids) > MAX_NODE_IDS:
        raise ValueError("Synthetic node population exceeded safety limit.")
    return sorted(ids)
