"""Typed public DTOs contain no arbitrary graph properties or source text."""
from __future__ import annotations

from typing import Generic, Literal, TypeVar
from pydantic import BaseModel, Field, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Work(StrictModel):
    id: str
    title: str
    provider_ref: str | None = None
    provider: str | None = None
    edition_count: int | None = None


class Person(StrictModel):
    id: str
    display_name: str | None = None
    date_from_year: int | None = None
    date_to_year: int | None = None


class Passage(StrictModel):
    id: str
    source_ref: str
    work_id: str | None = None
    edition_id: str | None = None
    version_id: str | None = None
    rights_tag: str | None = None
    excerpt: None = None   # No licensed text is stored or exposed in v0.5.


class Concept(StrictModel):
    id: str
    preferred_label: str | None = None
    language: str | None = None


class SourceRecord(StrictModel):
    id: str
    provider: str | None = None
    source_uri: str | None = None
    version_id: str | None = None
    rights_tag: str | None = None
    checksum_sha256: str | None = None


class EvidenceLink(StrictModel):
    id: str
    source_passage_id: str
    target_passage_id: str
    evidence_id: str
    claim_kind: Literal["OBSERVED_SOURCE_LINK", "HUMAN_INTERPRETATION", "MODEL_SUGGESTION"]
    review_status: Literal["unreviewed", "approved", "rejected", "disputed"]
    link_category: str | None = None
    source_ref: str | None = None
    source_uri: str | None = None
    rights_tag: str | None = None


T = TypeVar("T")


class Page(StrictModel, Generic[T]):
    schema_version: Literal["0.5.0"] = "0.5.0"
    items: list[T]
    next_cursor: str | None = None
    corpus_status: Literal["unreviewed_metadata_only"] = "unreviewed_metadata_only"


class GraphNode(StrictModel):
    id: str
    label: str
    title: str


class GraphRelation(StrictModel):
    id: str
    type: str
    evidence_id: str
    claim_kind: Literal["OBSERVED_SOURCE_LINK", "HUMAN_INTERPRETATION", "MODEL_SUGGESTION"]
    review_status: Literal["unreviewed", "approved", "rejected", "disputed"]
    source_ref: str | None = None
    source_uri: str | None = None
    rights_tag: str | None = None
    link_category: str | None = None
    source_record_id: str | None = None
    evidence_review_status: Literal["unreviewed", "approved", "rejected", "disputed"] | None = None


class GraphPath(StrictModel):
    nodes: list[GraphNode]
    edges: list[GraphRelation]


class Neighborhood(StrictModel):
    schema_version: Literal["0.5.0"] = "0.5.0"
    entity_id: str
    depth: int
    paths: list[GraphPath]
    has_more: bool = False
    note: str = "Graph connectivity is not evidence of influence or agreement."


class Readiness(StrictModel):
    status: Literal["ready"] = "ready"
    graph_schema_version: str = "0.2.1"
    api_version: str = "0.5.0"
    research_corpus_status: Literal["human_review_pending"] = "human_review_pending"


class ErrorDetail(StrictModel):
    code: str
    message: str
    request_id: str


class ErrorResponse(StrictModel):
    error: ErrorDetail


class MetadataHit(StrictModel):
    id: str
    kind: Literal["work", "person", "passage", "concept"]
    title: str
    source_anchor: str | None
    match_basis: Literal["canonical_id", "title", "alias"]
    review_status: Literal["unreviewed"] = "unreviewed"
    source_verification: Literal["NOT_VERIFIED"] = "NOT_VERIFIED"
    rights_status: Literal["NOT_ASSESSED"] = "NOT_ASSESSED"
    text_available: Literal[False] = False


class MetadataSearchPage(StrictModel):
    schema_version: Literal["0.8.2"] = "0.8.2"
    kind: Literal["works", "persons", "passages", "concepts"]
    items: list[MetadataHit]
    next_cursor: str | None = None
    has_more: bool
    search_complete: bool
    scanned_candidates: int
    candidate_window_limit: Literal[50] = 50
    corpus_status: Literal["unreviewed_metadata_only"] = "unreviewed_metadata_only"
    match_order: Literal["canonical_id_scan_not_relevance_ranked"] = "canonical_id_scan_not_relevance_ranked"
    normalization: Literal["unicode_nfkd_casefold_marks_punctuation"] = "unicode_nfkd_casefold_marks_punctuation"
    text_available: Literal[False] = False
    source_trail_verified: Literal[False] = False
    full_text_indexed: Literal[False] = False


class IndexedMetadataSearchPage(StrictModel):
    schema_version: Literal["0.8.3"] = "0.8.3"
    kind: Literal["works", "persons", "passages", "concepts"]
    items: list[MetadataHit]
    next_cursor: str | None = None
    has_more: bool
    search_complete: bool
    match_order: Literal["indexed_title_prefix_canonical_id"]
    index_version: Literal["search_key_v1"]
    index_coverage: dict
    alias_matching_available: Literal[False] = False
    full_text_indexed: Literal[False] = False
    source_trail_verified: Literal[False] = False
    text_available: Literal[False] = False
    corpus_status: Literal["unreviewed_metadata_only"] = "unreviewed_metadata_only"
