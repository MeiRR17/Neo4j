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


class IndexedCapabilityCoverage(StrictModel):
    total: int = Field(ge=0, le=1_000_000)
    covered: int = Field(ge=0, le=1_000_000)
    complete: bool


class IndexedSearchCapability(StrictModel):
    """Service-only index readiness, not proof of corpus rights or completeness."""
    schema_version: Literal["0.8.5"] = "0.8.5"
    kind: Literal["works", "persons", "passages", "concepts"]
    index_version: Literal["search_key_v1"] = "search_key_v1"
    index_status: Literal["ready", "missing", "not_online", "empty", "incomplete"]
    indexed_prefix_ready: bool
    index_coverage: IndexedCapabilityCoverage | None
    bounded_scan_supported: Literal[True] = True
    scan_candidate_window_limit: Literal[50] = 50
    scan_requires_cursor_completion: Literal[True] = True
    alias_matching_on_index: Literal[False] = False
    full_text_indexed: Literal[False] = False
    source_trail_verified: Literal[False] = False
    text_available: Literal[False] = False
    corpus_status: Literal["unreviewed_metadata_only"] = "unreviewed_metadata_only"


class ProvenanceSourceItem(StrictModel):
    id: str
    provider: str | None = None
    source_uri: str | None = None
    version_id: str | None = None
    rights_tag: str | None = None
    checksum_sha256: str | None = None


class ProvenanceEditionItem(StrictModel):
    id: str
    work_id: str
    version_id: str | None = None
    language: str | None = None
    rights_tag: str | None = None
    rights_review_status: str | None = None
    allowed_text_redistribution: bool | None = None


class ProvenanceEvidenceItem(StrictModel):
    id: str
    source_record_id: str
    version_id: str | None = None
    rights_tag: str | None = None
    claim_kind: str
    review_status: str


class ProvenanceMetadataPage(StrictModel):
    schema_version: Literal["0.8.11"] = "0.8.11"
    kind: Literal["sources", "editions", "evidence"]
    items: list[ProvenanceSourceItem | ProvenanceEditionItem | ProvenanceEvidenceItem]
    has_more: bool
    search_complete: bool
    next_cursor: str | None = None
    rights_independently_verified: Literal[False] = False
    source_bytes_verified: Literal[False] = False
    source_text_available: Literal[False] = False
    corpus_snapshot_isolation: Literal[False] = False


# v0.9.0: exploratory evidence-linked metadata only; no inference.
class AnalysisSourceLink(StrictModel):
    id: str
    source_passage_id: str
    target_passage_id: str
    evidence_id: str
    claim_kind: Literal["OBSERVED_SOURCE_LINK"]
    review_status: Literal["unreviewed", "approved", "rejected", "disputed"]
    evidence_review_status: Literal["unreviewed", "approved", "rejected", "disputed"]
    source_ref: str | None
    version_id: str | None
    rights_tag: str | None


class AnalysisSharedTarget(StrictModel):
    candidate_passage_id: str
    shared_target_passage_id: str
    focus_evidence_id: str
    candidate_evidence_id: str
    focus_review_status: Literal["unreviewed", "approved", "rejected", "disputed"]
    candidate_review_status: Literal["unreviewed", "approved", "rejected", "disputed"]
    focus_evidence_review_status: Literal["unreviewed", "approved", "rejected", "disputed"]
    candidate_evidence_review_status: Literal["unreviewed", "approved", "rejected", "disputed"]
    focus_source_ref: str | None
    candidate_source_ref: str | None


class AnalysisPage(StrictModel):
    schema_version: Literal["0.9.0"] = "0.9.0"
    analysis_kind: Literal["source-links", "shared-targets"]
    focus_passage_id: str
    items: list[AnalysisSourceLink | AnalysisSharedTarget]
    has_more: bool
    result_window_limit: Literal[20] = 20
    corpus_completeness_verified: Literal[False] = False
    source_rights_verified: Literal[False] = False
    historical_influence_proven: Literal[False] = False
    research_release_status: Literal["HOLD"] = "HOLD"
    note: str


# v0.9.1 bounded directed path evidence; not a scholarly influence claim.
class EvidencePathEdge(StrictModel):
    edge_id: str
    from_passage_id: str
    to_passage_id: str
    evidence_id: str
    claim_kind: Literal["OBSERVED_SOURCE_LINK"]
    edge_review_status: Literal["unreviewed", "approved"]
    evidence_review_status: Literal["unreviewed", "approved"]
    source_ref: str | None
    version_id: str | None
    rights_tag: str | None


class EvidencePathRecord(StrictModel):
    passage_ids: list[str]
    edges: list[EvidencePathEdge]
    hop_count: Literal[1, 2]


class EvidencePathPage(StrictModel):
    schema_version: Literal["0.9.1"] = "0.9.1"
    source_passage_id: str
    target_passage_id: str
    paths: list[EvidencePathRecord]
    observed_shortest_hops: Literal[1, 2] | None
    has_more: bool
    max_hops: Literal[2] = 2
    eligible_review_statuses: list[Literal["unreviewed", "approved"]]
    whole_graph_shortest_path_proven: Literal[False] = False
    graph_snapshot_isolation_verified: Literal[False] = False
    historical_influence_proven: Literal[False] = False
    source_rights_verified: Literal[False] = False
    research_release_status: Literal["HOLD"] = "HOLD"
    note: str


# v0.9.2: sample-frequency metrics and conditional author-year indicators.
class SourceLinkFrequency(StrictModel):
    schema_version: Literal["0.9.2"] = "0.9.2"
    passage_id: str
    sample_order: Literal["ascending_canonical_source_link_edge_id"]
    sample_limit: Literal[50] = 50
    observed_link_denominator: int = Field(ge=0, le=50)
    outgoing_observed_links: int = Field(ge=0, le=50)
    incoming_observed_links: int = Field(ge=0, le=50)
    joint_approved_status_links: int = Field(ge=0, le=50)
    contested_status_links: int = Field(ge=0, le=50)
    pending_status_links: int = Field(ge=0, le=50)
    joint_approved_status_fraction: float | None = Field(default=None, ge=0, le=1)
    window_truncated: bool
    whole_graph_centrality_verified: Literal[False] = False
    graph_snapshot_isolation_verified: Literal[False] = False
    source_rights_verified: Literal[False] = False
    scholarly_quality_approved: Literal[False] = False
    historical_influence_proven: Literal[False] = False
    research_release_status: Literal["HOLD"] = "HOLD"
    note: str


class AuthorLifetimeRange(StrictModel):
    id: str
    date_from_year: int | None
    date_to_year: int | None


class SourceLinkAuthorChronology(StrictModel):
    schema_version: Literal["0.9.2"] = "0.9.2"
    source_passage_id: str
    target_passage_id: str
    sample_link_edge_id: str | None
    sample_link_evidence_id: str | None
    source_work_id: str | None
    target_work_id: str | None
    source_authors: list[AuthorLifetimeRange]
    target_authors: list[AuthorLifetimeRange]
    metadata_status: Literal[
        "no_eligible_observed_link_or_work", "same_work",
        "missing_author_metadata", "ambiguous_author_metadata",
        "incomplete_year_metadata", "author_lifetime_intervals_compared",
    ]
    author_lifetime_relation: Literal[
        "unknown", "source_author_lifetime_later",
        "target_author_lifetime_later", "lifetimes_overlap",
    ]
    source_years_independently_verified: Literal[False] = False
    composition_or_publication_order_verified: Literal[False] = False
    historical_influence_proven: Literal[False] = False
    source_rights_verified: Literal[False] = False
    graph_snapshot_isolation_verified: Literal[False] = False
    research_release_status: Literal["HOLD"] = "HOLD"
    note: str


# v0.9.3: metadata-only two-Work comparison, no verified attribution.
class WorkComparisonAuthor(StrictModel):
    id: str
    date_from_year: int | None
    date_to_year: int | None


class WorkComparisonDescriptor(StrictModel):
    id: str
    title: str | None
    provider_ref: str | None
    author_sample: list[WorkComparisonAuthor]
    author_sample_truncated: bool
    author_metadata_status: Literal["missing", "single", "multiple", "truncated"]


class WorkCrossLink(StrictModel):
    edge_id: str
    source_work_id: str
    target_work_id: str
    source_passage_id: str
    target_passage_id: str
    evidence_id: str
    edge_review_status: Literal["unreviewed", "approved", "rejected", "disputed"]
    evidence_review_status: Literal["unreviewed", "approved", "rejected", "disputed"]
    source_ref: str
    target_ref: str
    evidence_source_ref: str | None
    version_id: str | None
    rights_tag: str | None


class WorkCrossLinkWindow(StrictModel):
    source_work_id: str
    target_work_id: str
    links: list[WorkCrossLink]
    observed_window_denominator: int = Field(ge=0, le=10)
    joint_approved_status_links: int = Field(ge=0, le=10)
    contested_status_links: int = Field(ge=0, le=10)
    pending_status_links: int = Field(ge=0, le=10)
    has_more: bool


class WorkComparison(StrictModel):
    schema_version: Literal["0.9.3"] = "0.9.3"
    left_work: WorkComparisonDescriptor
    right_work: WorkComparisonDescriptor
    left_to_right: WorkCrossLinkWindow
    right_to_left: WorkCrossLinkWindow
    author_id_overlap_status: Literal[
        "insufficient_author_metadata",
        "shared_author_id_observed",
        "different_author_ids_observed",
    ]
    shared_author_ids: list[str]
    directional_window_limit: int = Field(ge=1, le=10)
    all_cross_work_links_examined: Literal[False] = False
    author_attribution_independently_verified: Literal[False] = False
    historical_influence_proven: Literal[False] = False
    source_rights_verified: Literal[False] = False
    graph_snapshot_isolation_verified: Literal[False] = False
    research_release_status: Literal["HOLD"] = "HOLD"
    note: str
