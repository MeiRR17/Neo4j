"""v0.9.8 deterministic 4-Work SOURCE_LINK distractor-isolation fixtures.

Fixed 128 observed links between two selected Works; 0/128/512
unrelated links between a separate pair of Works. Every Passage and
Evidence ID is unique. No data is scraped, loaded, or sourced externally.
This module never connects to a database.
"""
from __future__ import annotations

from hashlib import sha256
import json

from research_graph.ontology import stable_id

VERSION = "synthetic-v0.9.8-1"
NAMESPACE = "isolated-v098-work-distractors"
PRIMARY_EDGES = 128
DISTRACTOR_SIZES = (0, 128, 512)
CASES = ("control-0", "distractor-128", "distractor-512")
MAX_IDS = 2000


def _edge(case_name: str, index: int, *, distraction: bool,
          left: str, right: str) -> dict:
    role = "distractor" if distraction else "selected"
    source_work, target_work = (left, right) if index % 2 == 0 else (right, left)
    ref = f"SYNTHETIC-{role}-{case_name}-{index:04d}"
    return {
        "source_work_id": source_work,
        "target_work_id": target_work,
        "source_passage_id": stable_id(
            "passage", NAMESPACE, case_name, role, str(index), "source"),
        "target_passage_id": stable_id(
            "passage", NAMESPACE, case_name, role, str(index), "target"),
        "evidence_id": stable_id(
            "evidence", NAMESPACE, case_name, role, str(index)),
        "edge_id": stable_id(
            "edge", NAMESPACE, case_name, role, str(index), "link"),
        "source_ref": ref + "/source",
        "target_ref": ref + "/target",
    }


def fixture_ids(case: dict) -> list[str]:
    ids = set(case["work_ids"] + case["author_ids"])
    seen_edges, seen_evidence = set(), set()
    for row in case["edges"]:
        seen_edges.add(row["edge_id"])
        seen_evidence.add(row["evidence_id"])
        ids.update((
            row["source_passage_id"], row["target_passage_id"],
            row["evidence_id"],
        ))
    if (len(seen_edges) != len(case["edges"]) or
            len(seen_evidence) != len(case["edges"]) or
            len(ids) != 8 + 3 * len(case["edges"]) or
            len(ids) > MAX_IDS):
        raise ValueError("Nonunique or excessive synthetic fixture identity.")
    return sorted(ids)


def distractor_case(name: str) -> dict:
    if type(name) is not str or name not in CASES:
        raise ValueError("Only three declared distractor fixtures are supported.")
    extra = int(name.split("-")[-1])
    work_ids = [
        stable_id("work", NAMESPACE, name, label)
        for label in ("selected-left", "selected-right",
                      "distractor-left", "distractor-right")
    ]
    authors = [
        stable_id("person", NAMESPACE, name, f"author-{i}")
        for i in range(4)
    ]
    authored_edges = [
        stable_id("edge", NAMESPACE, name, f"authored-{i}")
        for i in range(4)
    ]
    primary = [
        _edge(name, i, distraction=False, left=work_ids[0], right=work_ids[1])
        for i in range(PRIMARY_EDGES)
    ]
    distractions = [
        _edge(name, i, distraction=True, left=work_ids[2], right=work_ids[3])
        for i in range(extra)
    ]
    case = {
        "schema_version": VERSION,
        "name": name,
        "selected_edge_count": PRIMARY_EDGES,
        "distractor_edge_count": extra,
        "total_link_count": PRIMARY_EDGES + extra,
        "work_ids": work_ids,
        "author_ids": authors,
        "authored_edge_ids": authored_edges,
        "left_work_id": work_ids[0],
        "right_work_id": work_ids[1],
        # profile_params() must always use a selected Passage.
        "edges": primary + distractions,
    }
    ids = fixture_ids(case)
    case["synthetic_node_count"] = len(ids)
    data = json.dumps(
        case, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    case["fixture_sha256"] = sha256(data).hexdigest()
    return case
