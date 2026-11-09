"""Offline tests for Sefaria CSV/API metadata and plan safety (no network)."""
from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ingestion.acquire import (
    api_url, fetch_gcs_shard, parse_content_range,
)
from ingestion.graph_apply import add_source_evidence_edge, load_verified_plan
from ingestion.sefaria_links import (
    Link, api_links, csv_links, file_sha256, process_links,
    approved_source_url, staged_record,
)

SOURCE = "https://storage.googleapis.com/sefaria-export/links/links0.csv"
HEADER = ["Citation 1", "Citation 2", "Conection Type", "Text 1", "Text 2", "Category 1", "Category 2"]
TITLE = "Guide for the Perplexed"
OTHER = "Duties of the Heart"


def write_sample(path):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(HEADER)
        writer.writerow([TITLE + ", Part 1:1", OTHER + ", Gate 1:2",
                         "quotation", TITLE, OTHER, "Philosophy", "Ethics"])
        writer.writerow([OTHER + ", Gate 1:2", TITLE + ", Part 1:1",
                         "quotation", OTHER, TITLE, "Ethics", "Philosophy"])
        writer.writerow(["Exodus 3:4", "Genesis 1:1",
                         "reference", "Exodus", "Genesis", "Tanakh", "Tanakh"])
        writer.writerow([TITLE + ", Part 1:2", OTHER + ", Gate 1:2",
                         "related", TITLE, OTHER, "Philosophy", "Ethics"])


class SefariaPlanTests(unittest.TestCase):
    def test_curated_offline_plan_is_idempotent_and_preserves_ref(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, out = root / "links.csv", root / "out"
            write_sample(source)
            def run():
                return process_links(
                    csv_links(source), source_uri=SOURCE,
                    snapshot_sha256=file_sha256(source),
                    allowed_titles={TITLE}, destination=out,
                )
            a = run()
            self.assertEqual(a["counts"], {
                "seen": 4, "selected": 2, "deduplicated": 1,
                "out_of_scope": 1, "quarantined": 0,
            })
            self.assertEqual(a, run())
            manifest, records = load_verified_plan(out)
            self.assertEqual(len(records), 2)
            self.assertEqual(manifest["links_sha256"], file_sha256(out / "links.jsonl"))
            self.assertFalse(manifest["text_rights_verified"])
            first = records[0]
            self.assertTrue(first["left"]["passage_ref"].startswith(OTHER) or
                            first["right"]["passage_ref"].startswith(OTHER))
            self.assertTrue(any(x["passage_ref"].endswith("Part 1:1")
                                for x in (first["left"], first["right"])))
            self.assertNotEqual(records[0]["edge_id"], records[1]["edge_id"])
            self.assertEqual(first["orientation"], "not_asserted")
            self.assertEqual(first["review_status"], "unreviewed")
            self.assertIn("source_evidence_edge_id", first)

    def test_quarantine_gate_blocks_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, out = root / "bad.csv", root / "plan"
            with source.open("w", encoding="utf-8", newline="") as s:
                writer = csv.writer(s)
                writer.writerow(HEADER)
                writer.writerow(["A 1:1", "", "reference", TITLE, OTHER, "", ""])
            with self.assertRaisesRegex(ValueError, "Quarantine gate"):
                process_links(csv_links(source), source_uri=SOURCE,
                              snapshot_sha256=file_sha256(source),
                              allowed_titles={TITLE}, destination=out)
            self.assertFalse((out / "manifest.json").exists())

    def test_missing_header_and_full_ref_collision(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.csv"
            path.write_text("Citation 1,Citation 2\nFoo,Bar\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing_columns"):
                list(csv_links(path))
        one = Link("Guide for the Perplexed, Part 1:1", "Other 1:2",
                   TITLE, "Other", "related")
        two = Link("Guide for the Perplexed, Part 1:2", "Other 1:2",
                   TITLE, "Other", "related")
        source_record_id = "source:" + "0" * 64
        a = staged_record(one, source_record_id, SOURCE, "f" * 64)
        b = staged_record(two, source_record_id, SOURCE, "f" * 64)
        self.assertNotEqual(a["edge_id"], b["edge_id"])

    def test_tampered_plan_rejected_before_database_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, out = root / "links.csv", root / "out"
            write_sample(source)
            process_links(csv_links(source), source_uri=SOURCE,
                          snapshot_sha256=file_sha256(source),
                          allowed_titles={TITLE}, destination=out)
            data = (out / "links.jsonl").read_text(encoding="utf-8")
            (out / "links.jsonl").write_text(data.replace("unreviewed", "approved"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "checksums"):
                load_verified_plan(out)

    def test_api_fallback_quarantines_unmapped_fields(self):
        url = api_url(TITLE)
        self.assertIn("with_text=0", url)
        links = list(api_links([
            {"anchorRef": TITLE + " 1:1", "ref": OTHER + " 2:3",
             "index_title": OTHER, "type": "related"},
            {"anchorRef": TITLE + " 1:2", "ref": OTHER + " 3:4"},  # no opposite index
        ], TITLE))
        self.assertIsNotNone(links[0][1])
        self.assertEqual(links[1][2], "missing_identity")
        self.assertIn("api/links", approved_source_url(url))
        with self.assertRaises(ValueError):
            approved_source_url("http://evil.test/links0.csv")


class AcquisitionTests(unittest.TestCase):
    def test_range_parse_and_allowlist(self):
        self.assertEqual(parse_content_range("bytes 6-10/11"), (6, 10, 11))
        for value in ["bytes 10-5/11", "bytes */11", "bytes 0-11/11"]:
            with self.assertRaises(ValueError):
                parse_content_range(value)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                fetch_gcs_shard("../secret.csv", Path(directory) / "x.csv")

    def test_graph_provenance_edge_is_stable(self):
        dummy = {"source_record_id": "source:" + "1"*64,
                 "evidence_id": "evidence:" + "2"*64}
        a = add_source_evidence_edge(dummy)
        b = add_source_evidence_edge(dummy)
        self.assertEqual(a, b)
        self.assertTrue(a["source_evidence_edge_id"].startswith("edge:"))


if __name__ == "__main__":
    unittest.main()
