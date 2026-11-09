"""Immutable, parameterized, read-only Cypher registry.

No client may submit query text, label, relationship pattern or arbitrary
Cypher fragment. The only pattern variation is a server-selected depth 1/2.
Data is projected to an explicit safelist (no text bodies).
"""
from __future__ import annotations

from research_graph.ontology import EDGE_ENDPOINTS

READ_OPERATIONS: dict[str, str] = {
    "ready": """
MATCH (m:SchemaMigration)
RETURN m.id AS id, m.checksum AS checksum
ORDER BY id
""",
    "works": """
MATCH (w:Work)
WHERE ($query = '' OR toLower(coalesce(w.title, '')) CONTAINS toLower($query))
  AND ($language = '' OR EXISTS {
    MATCH (w)-[:HAS_EDITION]->(ed:Edition)
    WHERE ed.language = $language
  })
  AND ($cursor = '' OR w.id > $cursor)
RETURN w.id AS id, w.title AS title, w.provider_ref AS provider_ref,
       w.provider AS provider
ORDER BY id
LIMIT $fetch_limit
""",
    "persons": """
MATCH (p:Person)
WHERE ($query = '' OR toLower(coalesce(p.display_name, '')) CONTAINS toLower($query))
  AND ($cursor = '' OR p.id > $cursor)
RETURN p.id AS id, p.display_name AS display_name,
       p.date_from_year AS date_from_year, p.date_to_year AS date_to_year
ORDER BY id
LIMIT $fetch_limit
""",
    "passages": """
MATCH (p:Passage)
WHERE ($query = '' OR toLower(coalesce(p.source_ref, '')) CONTAINS toLower($query))
  AND ($cursor = '' OR p.id > $cursor)
RETURN p.id AS id, p.source_ref AS source_ref,
       p.work_id AS work_id, p.edition_id AS edition_id
ORDER BY id
LIMIT $fetch_limit
""",
    "concepts": """
MATCH (c:Concept)
WHERE ($query = '' OR toLower(coalesce(c.preferred_label, '')) CONTAINS toLower($query))
  AND ($cursor = '' OR c.id > $cursor)
RETURN c.id AS id, c.preferred_label AS preferred_label, c.language AS language
ORDER BY id
LIMIT $fetch_limit
""",
    "links": """
MATCH (a:Passage)-[r:SOURCE_LINK]->(b:Passage)
MATCH (e:Evidence {id:r.evidence_id})
WHERE ($passage_id = '' OR a.id = $passage_id OR b.id = $passage_id)
  AND ($claim_kind = '' OR r.claim_kind = $claim_kind)
  AND ($review_status = '' OR r.review_status = $review_status)
  AND r.claim_kind = e.claim_kind AND r.id IS NOT NULL
  AND ($cursor = '' OR r.id > $cursor)
RETURN r.id AS id, a.id AS source_passage_id, b.id AS target_passage_id,
       e.id AS evidence_id, r.claim_kind AS claim_kind,
       r.review_status AS review_status, e.link_category AS link_category,
       e.source_ref AS source_ref, e.source_uri AS source_uri,
       e.rights_tag AS rights_tag
ORDER BY id
LIMIT $fetch_limit
""",
    "work": """
MATCH (w:Work {id:$id})
OPTIONAL MATCH (w)-[:HAS_EDITION]->(e:Edition)
RETURN w.id AS id, w.title AS title, w.provider_ref AS provider_ref,
       w.provider AS provider, count(DISTINCT e) AS edition_count
""",
    "person": """
MATCH (p:Person {id:$id})
RETURN p.id AS id, p.display_name AS display_name,
       p.date_from_year AS date_from_year, p.date_to_year AS date_to_year
""",
    "passage": """
MATCH (p:Passage {id:$id})
OPTIONAL MATCH (e:Edition {id: p.edition_id})
RETURN p.id AS id, p.source_ref AS source_ref,
       p.work_id AS work_id, p.edition_id AS edition_id,
       e.version_id AS version_id, e.rights_tag AS rights_tag
""",
    "concept": """
MATCH (c:Concept {id:$id})
RETURN c.id AS id, c.preferred_label AS preferred_label, c.language AS language
""",
    "source": """
MATCH (s:SourceRecord {id:$id})
RETURN s.id AS id, s.provider AS provider, s.source_uri AS source_uri,
       s.version_id AS version_id, s.rights_tag AS rights_tag,
       s.checksum_sha256 AS checksum_sha256
""",
    "data_status": """
OPTIONAL MATCH (w:Work)
WITH count(w) AS works
OPTIONAL MATCH (p:Passage)
WITH works, count(p) AS passages
OPTIONAL MATCH (e:Evidence)
WITH works, passages, count(e) AS evidence_records
OPTIONAL MATCH (ed:Edition)
RETURN works AS works, passages AS passages,
       evidence_records AS evidence_records,
       count(ed) AS editions
""",
}

NEIGHBORHOOD_DEPTH_1 = """
MATCH (s)
WHERE s.id = $id AND (s:Work OR s:Person OR s:Passage OR s:Concept)
MATCH path = (s)-[*1]-(t)
WHERE ALL(r IN relationships(path) WHERE
  type(r) IN $edge_types AND r.evidence_id IS NOT NULL
  AND r.review_status IN ['unreviewed', 'approved', 'disputed', 'rejected']
  AND EXISTS {
    MATCH (e:Evidence {id:r.evidence_id})
    WHERE e.claim_kind = r.claim_kind
  })
WITH path
LIMIT $fetch_limit
WITH path, [rel IN relationships(path) | rel.evidence_id] AS evidence_ids
MATCH (ev:Evidence) WHERE ev.id IN evidence_ids
WITH path, collect(ev) AS evidence
RETURN [n IN nodes(path) | {id:n.id, label:head(labels(n)),
  title:coalesce(n.title,n.source_ref,n.display_name,n.preferred_label,'')}] AS nodes,
       [r IN relationships(path) | {id:r.id, type:type(r),
       evidence_id:r.evidence_id, claim_kind:r.claim_kind,
       review_status:r.review_status,
       source_ref:head([ev IN evidence WHERE ev.id = r.evidence_id | ev.source_ref]),
       source_uri:head([ev IN evidence WHERE ev.id = r.evidence_id | ev.source_uri]),
       rights_tag:head([ev IN evidence WHERE ev.id = r.evidence_id | ev.rights_tag]),
       link_category:head([ev IN evidence WHERE ev.id = r.evidence_id | ev.link_category]),
       source_record_id:head([ev IN evidence WHERE ev.id = r.evidence_id | ev.source_record_id]),
       evidence_review_status:head([ev IN evidence WHERE ev.id = r.evidence_id | ev.review_status])}] AS edges
""".strip()

NEIGHBORHOOD_DEPTH_2 = NEIGHBORHOOD_DEPTH_1.replace("[*1]", "[*1..2]")

# Only declared operations may run. No write clauses or arbitrary patterns.
READ_OPERATIONS["neighborhood_1"] = NEIGHBORHOOD_DEPTH_1
READ_OPERATIONS["neighborhood_2"] = NEIGHBORHOOD_DEPTH_2

VALID_EDGE_TYPES = frozenset(EDGE_ENDPOINTS)
LIST_KINDS = {
    "works": ("work", "works"),
    "persons": ("person", "persons"),
    "passages": ("passage", "passages"),
    "concepts": ("concept", "concepts"),
    "links": ("edge", "links"),
}
DETAIL_KINDS = {
    "work": "work", "person": "person", "passage": "passage",
    "concept": "concept", "source": "source",
}
