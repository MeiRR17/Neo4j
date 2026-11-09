#!/usr/bin/env python3
"""CI-only integration for synthetic edition metadata, never real source text."""
from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingestion.seed_catalog import build_inventory, load_catalog, checksum, versions_url  # noqa: E402
from ingestion.seed_apply import apply_approved_editions, approved_rows  # noqa: E402
from scripts.migrate import LocalQueryClient  # noqa: E402
from scripts.bootstrap import DEFAULT_SECRET_PATH  # noqa: E402


def main() -> int:
    if os.getenv("CI") != "true":
        print("[BLOCKED] Synthetic edition smoke is CI-only.")
        return 2
    catalog = load_catalog()
    title = catalog[-1]["index_title"]
    inventory = build_inventory(catalog, {
        title: [{
            "title": title, "versionTitle": "SYNTHETIC TEST VERSION - NOT ACTUAL SEFARIA",
            "language": "en", "license": "CC0",
            "versionSource": "https://example.invalid/fixture",
        }]
    })
    inventory["fixture_only"] = True
    ed = inventory["editions"][0]
    rights = [{
        "edition_id": ed["edition_id"], "inventory_sha256": checksum(inventory),
        "decision": "approve_metadata", "license_confirmed": "CC0",
        "intended_use": "research_metadata_only",
        "reviewer_id": "synthetic-ci-reviewer-not-a-real-person",
        "reviewed_at": "2026-11-09T12:00:00+00:00",
        "rationale": "CI-only fixture approval validates technical metadata import, not actual rights.",
        "rights_evidence_uri": versions_url(title),
        "attribution": "Synthetic test version; no source text or real license clearance",
        "use_context": "noncommercial",
    }]
    records = approved_rows(inventory, rights)
    client = LocalQueryClient("http://127.0.0.1:7474", DEFAULT_SECRET_PATH)
    ids = [
        records[0][key] for key in (
            "source_record_id", "work_id", "edition_id", "evidence_id"
        )
    ]
    try:
        for _ in range(2):
            if apply_approved_editions(inventory, rights, client, fixture=True) != 1:
                raise RuntimeError("Fixture metadata import did not upsert one version.")
        rows = client.query(
            "MATCH (w:Work {id: $wid})-[r:HAS_EDITION]->"
            "(e:Edition {id: $eid}) RETURN e.license_raw AS license, "
            "e.allowed_text_redistribution AS text_allowed, "
            "r.evidence_id AS evidence",
            {"wid": records[0]["work_id"], "eid": records[0]["edition_id"]},
        )
        if rows != [["CC0", False, records[0]["evidence_id"]]]:
            raise RuntimeError("Metadata-only relation/provenance check failed.")
        print("[OK] Synthetic edition metadata upsert twice, with evidence and no text.")
        return 0
    finally:
        client.query("MATCH (n) WHERE n.id IN $ids DETACH DELETE n", {"ids": ids})


if __name__ == "__main__":
    raise SystemExit(main())
