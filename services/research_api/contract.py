"""Versioned DvirOS integration contract: no user data or secrets."""
from __future__ import annotations

CONTRACT_VERSION = "1.0"
SERVICE_ID = "dviros.neo4j.philosophy"
API_VERSION = "0.6.0"
MIN_DVIROS_BRIDGE = "dvir-os/0.6.0"

RESEARCH_CONTRACT = {
    "contract_version": CONTRACT_VERSION,
    "service_id": SERVICE_ID,
    "api_version": API_VERSION,
    "schema_version": "0.5.0",
    "minimum_client": MIN_DVIROS_BRIDGE,
    "capabilities": [
        "works", "persons", "passages", "concepts", "links",
        "graph/neighborhood", "data/status", "sources"
    ],
    "source_trail_required": True,
    "research_corpus_status": "human_review_pending",
    "human_approval_required": True,
    "full_text_available": False,
    "writes_allowed": False,
}
