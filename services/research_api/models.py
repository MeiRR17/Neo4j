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
    graph_schema_version: str = "0.2.0"
    api_version: str = "0.5.0"
    research_corpus_status: Literal["human_review_pending"] = "human_review_pending"


class ErrorDetail(StrictModel):
    code: str
    message: str
    request_id: str


class ErrorResponse(StrictModel):
    error: ErrorDetail
