#!/usr/bin/env python3
"""Explicit, local-only, metadata-only normalized search index backfill.

No text bodies/quotations, no guessed aliases, no rights promotion.
Dry-run is the default; apply requires --ack-metadata-only AND isolated CI
or ALLOW_LOCAL_INDEX_BACKFILL=1. Uses the local Neo4j Query API only.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.bootstrap import DEFAULT_SECRET_PATH
from scripts.migrate import LocalQueryClient, applied_checksum, load_migrations
from services.research_api.metadata_search import fold_metadata, safe_id

KINDS = {
    "works": ("Work", "title", "work"),
    "persons": ("Person", "display_name", "person"),
    "passages": ("Passage", "source_ref", "passage"),
    "concepts": ("Concept", "preferred_label", "concept"),
}
WINDOW = 25
MAX_RECORDS_PER_KIND = 50_000
MAX_TITLE = 500

# The label/property are static developer values, never user-controlled
# Cypher identifiers or names. All source values are query parameters.
APPLY = {
    kind: f"""
UNWIND $batch AS row
MATCH (n:{label} {{id: row.id}})
WHERE n.{title_property} = row.source
  AND (n.search_key_v1 IS NULL OR n.search_key_v1 = row.key)
  AND (n.search_source_v1 IS NULL OR n.search_source_v1 = row.source)
SET n.search_key_v1 = row.key, n.search_source_v1 = row.source
RETURN count(n) AS updated
""".strip()
    for kind, (label, title_property, _) in KINDS.items()
}
READ = {
    kind: f"""
MATCH (n:{label})
WHERE ($cursor = '' OR n.id > $cursor)
RETURN n.id AS id, n.{title_property} AS title,
       n.search_key_v1 AS search_key, n.search_source_v1 AS search_source
ORDER BY id
LIMIT $fetch_limit
""".strip()
    for kind, (label, title_property, _) in KINDS.items()
}
COVERAGE = {
    kind: f"""
MATCH (n:{label})
RETURN count(n) AS total,
       count(CASE WHEN n.search_key_v1 IS NOT NULL
         AND n.search_key_v1 <> ''
         AND n.search_source_v1 = n.{title_property} THEN 1 END) AS covered
""".strip()
    for kind, (label, title_property, _) in KINDS.items()
}


def prepare_row(row: object, kind: str) -> dict:
    if not isinstance(row, list) or len(row) != 4:
        raise RuntimeError("Search metadata row shape invalid.")
    identifier, title, existing_key, existing_source = row
    try:
        safe_id(identifier, KINDS[kind][2])
        if not isinstance(title, str) or not 1 <= len(title) <= MAX_TITLE:
            raise ValueError("Source metadata title is missing or too long.")
        key = fold_metadata(title)
        if not key or len(key) > MAX_TITLE:
            raise ValueError("Metadata title cannot be normalized safely.")
        if (existing_key is None) != (existing_source is None):
            raise ValueError("Incomplete existing search key and source pairing.")
        if existing_key is not None and (existing_key != key or existing_source != title):
            raise ValueError("Existing indexed search metadata differs from the source.")
        return {"id": identifier, "source": title, "key": key}
    except (ValueError, TypeError) as exc:
        raise RuntimeError("Index backfill input must be reviewed before any update.") from exc


def collect_plan(client: LocalQueryClient, kind: str) -> list[dict]:
    if kind not in KINDS:
        raise ValueError("Unknown indexed search kind.")
    result = []
    cursor = ""
    while True:
        rows = client.query(READ[kind], {"cursor": cursor, "fetch_limit": WINDOW + 1})
        if not isinstance(rows, list) or len(rows) > WINDOW + 1:
            raise RuntimeError("Index scan exceeded the bounded window.")
        for row in rows[:WINDOW]:
            parsed = prepare_row(row, kind)
            if cursor and parsed["id"] <= cursor:
                raise RuntimeError("Index scan lost canonical ordering.")
            cursor = parsed["id"]
            result.append(parsed)
            if len(result) > MAX_RECORDS_PER_KIND:
                raise RuntimeError("Index backfill exceeds per-kind pilot budget.")
        if len(rows) <= WINDOW:
            return result


def audit(client: LocalQueryClient, kind: str) -> dict:
    rows = client.query(COVERAGE[kind], {})
    if (not isinstance(rows, list) or len(rows) != 1
            or not isinstance(rows[0], list) or len(rows[0]) != 2):
        raise RuntimeError("Index coverage result is malformed.")
    total, covered = rows[0]
    if (type(total) is not int or type(covered) is not int
            or not 0 <= covered <= total <= MAX_RECORDS_PER_KIND):
        raise RuntimeError("Index coverage values are invalid.")
    return {"kind": kind, "total": total, "covered": covered,
            "complete": covered == total}


def verify_migrations(client: LocalQueryClient) -> None:
    for migration in load_migrations():
        if applied_checksum(client, migration.id) != migration.checksum:
            raise RuntimeError("Apply all checked Neo4j migrations before index work.")


def backfill(client: LocalQueryClient, *, kind: str = "all",
             apply: bool = False) -> list[dict]:
    verify_migrations(client)
    names = list(KINDS) if kind == "all" else [kind]
    if any(name not in KINDS for name in names):
        raise ValueError("Unsupported index backfill kind.")
    # Complete preflight of every chosen kind BEFORE the first write.
    planned = {name: collect_plan(client, name) for name in names}
    if apply:
        for name in names:
            for pos in range(0, len(planned[name]), WINDOW):
                batch = planned[name][pos:pos + WINDOW]
                updated = client.query(APPLY[name], {"batch": batch})
                if updated != [[len(batch)]]:
                    raise RuntimeError("Index write raced or hit an incompatible node.")
    results = [audit(client, name) for name in names]
    if apply and any(not r["complete"] for r in results):
        raise RuntimeError("Search index is incomplete; no indexed search release.")
    return [
        {**r, "planned": len(planned[r["kind"]]), "applied": apply}
        for r in results
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["dry-run", "apply", "check"])
    parser.add_argument("--kind", choices=["all", *KINDS], default="all")
    parser.add_argument("--url", default="http://127.0.0.1:7474")
    parser.add_argument("--secret", type=Path, default=DEFAULT_SECRET_PATH)
    parser.add_argument("--ack-metadata-only", action="store_true")
    args = parser.parse_args()
    if args.mode == "apply" and (
        not args.ack_metadata_only or (
            os.getenv("CI") != "true"
            and os.getenv("ALLOW_LOCAL_INDEX_BACKFILL") != "1"
        )
    ):
        print("[BLOCKED] Explicit metadata-only acknowledgement and isolated CI/local override required.")
        return 2
    try:
        client = LocalQueryClient(args.url, args.secret)
        if args.mode == "check":
            verify_migrations(client)
            results = [audit(client, name) for name in
                       (KINDS if args.kind == "all" else [args.kind])]
            if any(not r["complete"] or r["total"] == 0 for r in results):
                print("[INCOMPLETE] Index absent, empty or stale; indexed lookup remains blocked.")
                return 1
        else:
            results = backfill(client, kind=args.kind, apply=args.mode == "apply")
        for row in results:
            print("[INDEX] kind={kind} total={total} covered={covered} "
                  "planned={planned} applied={applied}".format(
                      kind=row["kind"], total=row["total"], covered=row["covered"],
                      planned=row.get("planned", "n/a"), applied=row.get("applied", False)))
        return 0
    except (RuntimeError, ValueError, OSError) as exc:
        print("[FAIL] Metadata index: " + str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
