"""Canonical IDs, evidence contracts, and safe edge templates.

This module is deliberately pure Python. It never interprets co-citation as
influence or transforms a source link into an asserted citation.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import unicodedata


ENTITY_TYPES = frozenset({
    "work", "passage", "person", "concept", "source",
    "evidence", "import", "alias", "edition", "edge",
})
CLAIM_KINDS = frozenset({
    "OBSERVED_SOURCE_LINK", "HUMAN_INTERPRETATION", "MODEL_SUGGESTION",
})
REVIEW_STATUSES = frozenset({"unreviewed", "approved", "rejected", "disputed"})
CANONICAL_ID_PATTERN = re.compile(r"^(?:work|passage|person|concept|source|evidence|import|alias|edition|edge):[a-f0-9]{64}$")
LANGUAGES = frozenset({"he", "en", "ar", "yi", "other"})

# Curated labels only: database queries NEVER interpolate labels or types
# originating from external provider data or an AI model.
# Each tuple describes (from_label, to_label).
EDGE_ENDPOINTS = {
    "AUTHORED": ("Person", "Work"),
    "HAS_PASSAGE": ("Work", "Passage"),
    "HAS_EDITION": ("Work", "Edition"),
    "IN_EDITION": ("Passage", "Edition"),
    "MENTIONS_CONCEPT": ("Passage", "Concept"),
    "SOURCE_LINK": ("Passage", "Passage"),
    "HUMAN_CLAIM": ("Passage", "Concept"),
    "SUGGESTED_RELATION": ("Passage", "Concept"),
    "HAS_ALIAS": ("Work", "NameAlias"),
    "HAS_EVIDENCE": ("SourceRecord", "Evidence"),
}
EDGE_CLAIM_KIND = {
    "SOURCE_LINK": "OBSERVED_SOURCE_LINK",
    "HUMAN_CLAIM": "HUMAN_INTERPRETATION",
    "SUGGESTED_RELATION": "MODEL_SUGGESTION",
}


def canonical_component(value: str) -> str:
    """Preserve internal whitespace and full chapter/ref syntax; trim edges only."""
    if not isinstance(value, str):
        raise TypeError("Canonical identity component must be a string.")
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized or "\x00" in normalized:
        raise ValueError("Canonical identity component must be nonempty and NUL-free.")
    return normalized


def stable_id(entity_type: str, *identity: str) -> str:
    """Hash a structured identity tuple, NOT a human-readable title or split ref.

    JSON array framing prevents ambiguous concatenation and distinguishable
    source/edition/passage identities. No salts, dates or observed_at timestamps.
    """
    if entity_type not in ENTITY_TYPES:
        raise ValueError("Unsupported canonical entity type.")
    if not identity:
        raise ValueError("Stable ID requires an identity tuple.")
    normalized = [canonical_component(value) for value in identity]
    payload = json.dumps([entity_type, *normalized], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return f"{entity_type}:{hashlib.sha256(payload).hexdigest()}"


def work_id(provider: str, provider_work_id: str) -> str:
    """The immutable provider key is the identity; title changes do not change IDs."""
    return stable_id("work", provider, provider_work_id)


def edition_id(work_canonical_id: str, provider_edition_id: str) -> str:
    require_canonical_id(work_canonical_id)
    return stable_id("edition", work_canonical_id, provider_edition_id)


def passage_id(edition_canonical_id: str, canonical_ref: str) -> str:
    """Preserve full multicomponent refs like 'Guide of the Perplexed, Part 1:1'."""
    require_canonical_id(edition_canonical_id)
    return stable_id("passage", edition_canonical_id, canonical_ref)


def evidence_id(source_record_id: str, source_ref: str, link_category: str,
                subject_id: str, object_id: str) -> str:
    for node_id in (source_record_id, subject_id, object_id):
        require_canonical_id(node_id)
    return stable_id("evidence", source_record_id, source_ref,
                     link_category, subject_id, object_id)


def require_canonical_id(value: str) -> str:
    if not isinstance(value, str) or not CANONICAL_ID_PATTERN.fullmatch(value):
        raise ValueError("Expected a stable canonical entity ID.")
    return value


def alias_search_key(display: str, language: str) -> str:
    """Secondary lookup key only; NEVER a canonical identifier or dedup key."""
    if language not in LANGUAGES:
        raise ValueError("Unsupported language tag.")
    visible = canonical_component(display)
    # Remove combining marks for finding alternate spellings; retain original
    # display as a separate property. This intentionally does not unify titles.
    return " ".join("".join(
        char for char in unicodedata.normalize("NFKD", visible)
        if not unicodedata.combining(char)
    ).casefold().split())


@dataclass(frozen=True)
class EvidenceRecord:
    id: str
    source_record_id: str
    source_ref: str
    source_uri: str
    version_id: str
    rights_tag: str
    claim_kind: str
    review_status: str = "unreviewed"
    reviewer_id: str | None = None
    limitation_note: str = ""
    observed_at: str = ""  # supplied UTC source timestamp in ingestion
    link_category: str = ""  # original provider category, not "direct citation"

    def __post_init__(self) -> None:
        require_canonical_id(self.id)
        require_canonical_id(self.source_record_id)
        for field in ("source_ref", "source_uri", "version_id", "rights_tag"):
            canonical_component(getattr(self, field))
        if self.claim_kind not in CLAIM_KINDS:
            raise ValueError("Unknown claim kind.")
        if self.review_status not in REVIEW_STATUSES:
            raise ValueError("Unknown review status.")
        if self.claim_kind == "MODEL_SUGGESTION" and self.review_status == "approved":
            raise ValueError("A model suggestion cannot promote itself to approved evidence.")
        if self.review_status == "approved" and not self.reviewer_id:
            raise ValueError("Approved evidence requires a reviewer identity.")

    def properties(self) -> dict:
        """Non-null Cypher properties; do not invent reviewer or observation dates."""
        result = {
            "id": self.id, "source_record_id": self.source_record_id,
            "source_ref": self.source_ref, "source_uri": self.source_uri,
            "version_id": self.version_id, "rights_tag": self.rights_tag,
            "claim_kind": self.claim_kind, "review_status": self.review_status,
        }
        for key in ("reviewer_id", "limitation_note", "observed_at", "link_category"):
            value = getattr(self, key)
            if value:
                result[key] = value
        return result


@dataclass(frozen=True)
class GraphEdge:
    edge_type: str
    source_id: str
    target_id: str
    evidence_id: str
    claim_kind: str
    status: str = "unreviewed"

    def __post_init__(self) -> None:
        if self.edge_type not in EDGE_ENDPOINTS:
            raise ValueError("Unsupported graph relationship type.")
        for value in (self.source_id, self.target_id, self.evidence_id):
            require_canonical_id(value)
        if self.evidence_id.split(":", 1)[0] != "evidence":
            raise ValueError("Relationship evidence ID must identify an Evidence node.")
        if self.claim_kind not in CLAIM_KINDS or self.status not in REVIEW_STATUSES:
            raise ValueError("Invalid claim kind or review status.")
        required_kind = EDGE_CLAIM_KIND.get(self.edge_type)
        if required_kind and self.claim_kind != required_kind:
            raise ValueError(f"{self.edge_type} requires claim kind {required_kind}.")
        if self.claim_kind == "MODEL_SUGGESTION" and self.status == "approved":
            raise ValueError("Automated suggestions cannot be auto-approved.")

    @property
    def id(self) -> str:
        return stable_id("edge", self.edge_type, self.source_id,
                         self.target_id, self.evidence_id)

    def parameters(self) -> dict:
        return {
            "edge_id": self.id, "source_id": self.source_id,
            "target_id": self.target_id, "evidence_id": self.evidence_id,
            "claim_kind": self.claim_kind, "status": self.status,
        }


def edge_upsert_query(edge_type: str) -> str:
    """Fixed, parameterized Cypher. All new relationships require Evidence.

    The query returns no rows if either endpoint or Evidence does not exist.
    The caller must check the return value and treat absence as an error.
    """
    if edge_type not in EDGE_ENDPOINTS:
        raise ValueError("Unrecognized relationship type: refusing query.")
    source_label, target_label = EDGE_ENDPOINTS[edge_type]
    return (
        f"MATCH (s:{source_label} {{id: $source_id}}) "
        f"MATCH (t:{target_label} {{id: $target_id}}) "
        "MATCH (e:Evidence {id: $evidence_id}) "
        "WHERE e.claim_kind = $claim_kind "
        f"MERGE (s)-[r:{edge_type} {{id: $edge_id}}]->(t) "
        "ON CREATE SET r.evidence_id = $evidence_id, "
        "r.claim_kind = $claim_kind, r.review_status = $status "
        "RETURN r.id AS id"
    )
