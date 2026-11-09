"""Source-grounded Jewish philosophy graph domain for DvirOS.

No database connection or external source acquisition happens on import.
"""
from .ontology import (
    CLAIM_KINDS, EDGE_ENDPOINTS, REVIEW_STATUSES, EvidenceRecord,
    GraphEdge, alias_search_key, edge_upsert_query, evidence_id,
    edition_id, passage_id, stable_id, work_id,
)
__all__ = [
    "CLAIM_KINDS", "EDGE_ENDPOINTS", "REVIEW_STATUSES", "EvidenceRecord",
    "GraphEdge", "alias_search_key", "edge_upsert_query", "evidence_id",
    "edition_id", "passage_id", "stable_id", "work_id",
]
