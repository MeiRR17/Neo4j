"""Pure, offline tests for edition rights, research reviews and seed quality."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from ingestion.seed_catalog import (
    build_inventory, checksum, load_catalog, parse_versions,
    versions_url, write_immutable_json,
)
from ingestion.seed_quality import (
    make_review_queue, quality_report, validate_evidence_reviews,
    validate_rights_decisions, verify_inventory,
)
from ingestion.seed_apply import approved_rows, METADATA_CYPHER
from ingestion.sefaria_links import Link, staged_record
from research_graph.ontology import evidence_id, stable_id, work_id, edition_id, passage_id

TITLE = "Guide for the Perplexed"
REVIEWED = "2026-11-09T12:00:00+00:00"
NOTE = "A reviewer checked exact upstream license data and usage restrictions."


def specimen(license_value="CC-BY"):
    catalog = load_catalog()
    sample = [{
        "title": TITLE, "versionTitle": "Fixture version A", "language": "he",
        "license": license_value, "versionSource": "https://example.invalid/source",
    }]
    return build_inventory(catalog, {TITLE: sample})


def decision(inventory, *, license_value="CC-BY", **changes):
    ed = inventory["editions"][0]
    result = {
        "edition_id": ed["edition_id"], "inventory_sha256": checksum(inventory),
        "decision": "approve_metadata", "license_confirmed": license_value,
        "intended_use": "research_metadata_only", "reviewer_id": "human-reviewer-fixture",
        "reviewed_at": REVIEWED, "rationale": NOTE,
        "rights_evidence_uri": versions_url(TITLE),
        "attribution": "Synthetic fixture edition, fake source attribution",
        "use_context": "noncommercial",
    }
    result.update(changes)
    return result


def links(count=120):
    wid = work_id("sefaria", TITLE)
    oid = work_id("sefaria", "Synthetic Other Work")
    ed1 = edition_id(wid, "UNVERSIONED_LINK_METADATA_ONLY")
    ed2 = edition_id(oid, "UNVERSIONED_LINK_METADATA_ONLY")
    source = stable_id("source", "sefaria", "synthetic-test-source")
    result = []
    for n in range(count):
        left = f"{TITLE}, Part 1:{n+1}"
        right = f"Synthetic Other Work, Part 2:{n+1}"
        record = staged_record(
            Link(left, right, TITLE, "Synthetic Other Work", "unspecified"),
            source, "https://example.invalid/synthetic", "a"*64,
        )
        result.append(record)
    return result


def observation(queue, idx=0, **changes):
    item = queue["items"][idx]
    review = {
        "evidence_id": item["evidence_id"],
        "queue_sha256": checksum(queue),
        "decision": "uncertain", "reviewer_id": "human-reviewer-fixture",
        "reviewed_at": REVIEWED,
        "rationale": "The observed link is ambiguous and requires independent assessment.",
        "asserted_influence": False, "asserted_citation_direction": False,
    }
    review.update(changes)
    return review


class CatalogTests(unittest.TestCase):
    def test_candidate_catalog_does_not_claim_any_rights(self):
        entries = load_catalog()
        self.assertEqual(len(entries), 18)
        self.assertEqual(len({x["index_title"] for x in entries}), 18)
        inventory = build_inventory(entries, {})
        self.assertEqual(len(inventory["editions"]), 0)
        self.assertEqual(len(inventory["unavailable"]), 18)
        self.assertFalse(inventory["rights_decisions_generated"])

    def test_version_metadata_is_pending_regardless_of_license(self):
        inventory = specimen("Public Domain")
        edition = next(iter(verify_inventory(inventory).values()))
        self.assertEqual(edition["rights_status"], "pending_human_review")
        self.assertFalse(edition["allowed_text_redistribution"])
        self.assertEqual(edition["license_raw"], "Public Domain")

    def test_version_titles_cannot_implicitly_change_index(self):
        good, quarantine = parse_versions(TITLE, [
            {"title": "Another Work", "versionTitle": "Version", "language": "he"},
            {"title": TITLE, "versionTitle": "A", "language": "xx"},
            {"title": TITLE, "versionTitle": "A", "language": "en", "license": ""},
        ])
        self.assertEqual(len(good), 1)
        self.assertEqual(len(quarantine), 2)
        self.assertFalse(good[0]["license_supported_for_review"])

    def test_immutable_inventory_rejects_changes(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "inventory.json"
            document = specimen()
            write_immutable_json(path, document)
            write_immutable_json(path, document)
            with self.assertRaisesRegex(ValueError, "different content"):
                write_immutable_json(path, specimen("CC0"))


class RightsTests(unittest.TestCase):
    def test_review_is_explicit_and_digest_bound(self):
        inventory = specimen()
        self.assertEqual(len(validate_rights_decisions(inventory, [])), 0)
        approved = validate_rights_decisions(inventory, [decision(inventory)])
        self.assertEqual(len(approved), 1)
        self.assertEqual(len(approved_rows(inventory, [decision(inventory)])), 1)
        self.assertIn("allowed_text_redistribution = false", METADATA_CYPHER)

    def test_rights_cannot_be_automatically_inferred_or_tampered(self):
        inventory = specimen()
        for changed in [
            {"license_confirmed": "Public Domain"},
            {"inventory_sha256": "b"*64},
            {"intended_use": "publish_full_text"},
            {"reviewer_id": ""},
            {"reviewed_at": "2026-11-09"},
            {"rationale": "ok"},
            {"rights_evidence_uri": "http://evil.test/rights"},
        ]:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                validate_rights_decisions(inventory, [decision(inventory, **changed)])

    def test_noncommercial_license_needs_noncommercial_use(self):
        inventory = specimen("CC-BY-NC")
        with self.assertRaisesRegex(ValueError, "noncommercial"):
            validate_rights_decisions(inventory, [
                decision(inventory, license_value="CC-BY-NC", use_context="commercial"),
            ])
        self.assertEqual(len(validate_rights_decisions(inventory, [
            decision(inventory, license_value="CC-BY-NC", use_context="noncommercial"),
        ])), 1)

    def test_unknown_license_never_approved(self):
        inventory = specimen("Unclear")
        with self.assertRaisesRegex(ValueError, "Unrecognized"):
            validate_rights_decisions(inventory, [
                decision(inventory, license_value="Unclear"),
            ])

    def test_duplicate_decisions_are_rejected(self):
        inventory = specimen()
        d = decision(inventory)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_rights_decisions(inventory, [d, d])


class QualityTests(unittest.TestCase):
    def test_sample_is_deterministic_and_contains_no_review_decisions(self):
        data = links(130)
        a = make_review_queue(data)
        b = make_review_queue(list(reversed(data)))
        self.assertEqual(a, b)
        self.assertEqual(a["selected_count"], 120)
        self.assertFalse(a["reviewer_decisions_generated"])
        self.assertTrue(all(x["review_status"] == "pending_human_inspection"
                            for x in a["items"]))
        self.assertEqual(len({x["evidence_id"] for x in a["items"]}), 120)

    def test_fake_influence_or_wrong_hash_is_rejected(self):
        queue = make_review_queue(links())
        with self.assertRaisesRegex(ValueError, "causal"):
            validate_evidence_reviews(queue, [
                observation(queue, asserted_influence=True)
            ])
        with self.assertRaisesRegex(ValueError, "different frozen queue"):
            validate_evidence_reviews(queue, [
                observation(queue, queue_sha256="0"*64)
            ])

    def test_readiness_fails_without_real_reviews_and_licenses(self):
        inventory = specimen()
        queue = make_review_queue(links(130), fixture=True)
        report = quality_report(inventory, [], queue, [], links(130))
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["approved_edition_count"], 0)
        self.assertEqual(report["adjudicated_evidence_count"], 0)
        self.assertTrue(report["manual_release_signoff_required"])
        self.assertFalse(report["production_ga"])

    def test_reviewed_count_measured_but_synthetic_stays_blocked(self):
        inventory = specimen()
        queue = make_review_queue(links(130), fixture=True)
        adjudications = [observation(queue, n) for n in range(120)]
        report = quality_report(inventory, [decision(inventory)],
                                queue, adjudications, links(130))
        self.assertEqual(report["adjudicated_evidence_count"], 120)
        self.assertEqual(report["approved_distinct_works"], 1)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertGreater(len(report["blocking_issues"]), 0)

    def test_collision_detection(self):
        inventory = specimen()
        staged = links(2)
        staged[1] = deepcopy(staged[1])
        staged[1]["left"]["passage_id"] = staged[0]["left"]["passage_id"]
        queue = make_review_queue(links(130), fixture=True)
        report = quality_report(inventory, [], queue, [], staged)
        self.assertEqual(report["canonical_id_collisions"], 1)

    def test_missing_evidence_detected(self):
        inventory = specimen()
        staged = links(1)
        staged[0] = deepcopy(staged[0])
        staged[0]["source_record_id"] = ""
        queue = make_review_queue(links(130), fixture=True)
        report = quality_report(inventory, [], queue, [], staged)
        self.assertEqual(report["missing_evidence_ids"], 1)


if __name__ == "__main__":
    unittest.main()
