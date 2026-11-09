"""Pure ontology contracts: identity, aliases, evidence and safe relationships."""
import unittest

from research_graph.ontology import (
    EvidenceRecord, GraphEdge, alias_search_key, edge_upsert_query,
    evidence_id, edition_id, passage_id, stable_id, work_id,
)


class IdentityTests(unittest.TestCase):
    def test_multiword_titles_and_passage_refs_never_truncate(self):
        work = work_id("sefaria", "Guide of the Perplexed")
        edition = edition_id(work, "English Edition 1")
        a = passage_id(edition, "Guide of the Perplexed, Part 1:1")
        b = passage_id(edition, "Guide of the Perplexed, Part 1:2")
        self.assertNotEqual(a, b)
        self.assertEqual(a, passage_id(edition, "Guide of the Perplexed, Part 1:1"))
        self.assertNotEqual(a, passage_id(edition, "Guide, Part 1:1"))

    def test_titles_are_not_primary_keys_and_editions_do_not_collide(self):
        a = work_id("sefaria", "work-A")
        b = work_id("sefaria", "work-B")
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, work_id("another-provider", "work-A"))
        self.assertNotEqual(edition_id(a, "edition-a"), edition_id(a, "edition-b"))
        self.assertNotEqual(stable_id("work", "ab", "c"),
                            stable_id("work", "a", "bc"))

    def test_unicode_and_lookup_keys(self):
        self.assertEqual(work_id("provider", "caf\u00e9"), work_id("provider", "cafe\u0301"))
        self.assertEqual(alias_search_key("  מוֹרֶה   נְבוּכִים ", "he"), "מורה נבוכים")
        self.assertEqual(alias_search_key("  GUIDE   Of  the Perplexed ", "en"),
                         "guide of the perplexed")

    def test_bad_keys_are_refused(self):
        for values in [("work", ""), ("work", " \t "), ("work", "bad\x00ref")]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                stable_id(*values)
        with self.assertRaises(ValueError):
            stable_id("unknown", "key")
        with self.assertRaises(TypeError):
            stable_id("work", 123)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.source = stable_id("source", "fixture", "fixture-1")
        self.work = work_id("fixture", "one")
        self.edition = edition_id(self.work, "v1")
        self.passage = passage_id(self.edition, "Synthetic Work 1:1")
        self.passage2 = passage_id(self.edition, "Synthetic Work 1:2")
        self.evidence = evidence_id(self.source, "Synthetic Work 1:1", "Synthetic",
                                    self.passage, self.passage2)

    def record(self, **overrides):
        params = {
            "id": self.evidence, "source_record_id": self.source,
            "source_ref": "Synthetic Work 1:1",
            "source_uri": "https://example.invalid/synthetic",
            "version_id": "test-only", "rights_tag": "TEST_FIXTURE",
            "claim_kind": "OBSERVED_SOURCE_LINK",
        }
        params.update(overrides)
        return EvidenceRecord(**params)

    def test_evidence_has_provenance_and_no_fabricated_review(self):
        props = self.record().properties()
        self.assertEqual(props["source_ref"], "Synthetic Work 1:1")
        self.assertEqual(props["review_status"], "unreviewed")
        self.assertNotIn("reviewer_id", props)
        self.assertNotIn("observed_at", props)

    def test_approval_must_have_reviewer(self):
        with self.assertRaisesRegex(ValueError, "reviewer identity"):
            self.record(review_status="approved")
        with self.assertRaisesRegex(ValueError, "model suggestion"):
            self.record(claim_kind="MODEL_SUGGESTION",
                        review_status="approved", reviewer_id="human-reviewer")

    def test_edge_always_requires_evidence_and_matching_kind(self):
        edge = GraphEdge("SOURCE_LINK", self.passage, self.passage2,
                         self.evidence, "OBSERVED_SOURCE_LINK")
        self.assertEqual(edge.id, GraphEdge("SOURCE_LINK", self.passage,
                                            self.passage2, self.evidence,
                                            "OBSERVED_SOURCE_LINK").id)
        self.assertEqual(edge.parameters()["evidence_id"], self.evidence)
        with self.assertRaisesRegex(ValueError, "requires claim kind"):
            GraphEdge("SOURCE_LINK", self.passage, self.passage2,
                      self.evidence, "MODEL_SUGGESTION")
        with self.assertRaises(ValueError):
            GraphEdge("SOURCE_LINK", self.passage, self.passage2,
                      self.work, "OBSERVED_SOURCE_LINK")

    def test_relationship_cypher_cannot_inject_provider_values(self):
        query = edge_upsert_query("SOURCE_LINK")
        self.assertIn("MATCH (e:Evidence {id: $evidence_id})", query)
        self.assertIn("r.review_status = $status", query)
        self.assertIn("r.claim_kind", query)
        with self.assertRaises(ValueError):
            edge_upsert_query("SOURCE_LINK) DELETE n //")


if __name__ == "__main__":
    unittest.main()
