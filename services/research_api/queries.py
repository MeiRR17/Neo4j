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


# v0.8.2: deterministic, read-only candidate scans over metadata fields.
# The API folds Hebrew niqqud/Latin accents after reading a strict 50-record
# window, with explicit scan-incomplete flags and a cursor.
READ_OPERATIONS["metadata_works"] = """
MATCH (n:Work)
WHERE ($cursor = '' OR n.id > $cursor)
  AND ($language = '' OR EXISTS {
    MATCH (n)-[:HAS_EDITION]->(ed:Edition)
    WHERE ed.language = $language
  })
RETURN n.id AS id, n.title AS title, n.provider_ref AS source_anchor,
       [(n)-[:HAS_ALIAS]->(a:NameAlias) | coalesce(a.label, a.value, a.name)][..8] AS aliases
ORDER BY id
LIMIT $fetch_limit
""".strip()

READ_OPERATIONS["metadata_persons"] = """
MATCH (n:Person)
WHERE ($cursor = '' OR n.id > $cursor)
RETURN n.id AS id, n.display_name AS title, null AS source_anchor,
       [] AS aliases
ORDER BY id
LIMIT $fetch_limit
""".strip()

READ_OPERATIONS["metadata_passages"] = """
MATCH (n:Passage)
WHERE ($cursor = '' OR n.id > $cursor)
RETURN n.id AS id, n.source_ref AS title, n.source_ref AS source_anchor,
       [] AS aliases
ORDER BY id
LIMIT $fetch_limit
""".strip()

READ_OPERATIONS["metadata_concepts"] = """
MATCH (n:Concept)
WHERE ($cursor = '' OR n.id > $cursor)
RETURN n.id AS id, n.preferred_label AS title, null AS source_anchor,
       [] AS aliases
ORDER BY id
LIMIT $fetch_limit
""".strip()


# v0.8.3 — fixed, developer-owned normalized title prefix index operations.
# The 004 migration creates secondary range indexes; canonical IDs remain
# unchanged. Never mix indexed title-prefix results with v0.8.2 alias/substring
# scans without telling the client the matching semantics changed.
_INDEX_FIELDS = {
    "works": ("Work", "title", "n.provider_ref"),
    "persons": ("Person", "display_name", "null"),
    "passages": ("Passage", "source_ref", "n.source_ref"),
    "concepts": ("Concept", "preferred_label", "null"),
}
for _kind, (_label, _field, _anchor) in _INDEX_FIELDS.items():
    _language = """AND ($language = '' OR EXISTS {
    MATCH (n)-[:HAS_EDITION]->(ed:Edition) WHERE ed.language = $language
  })""" if _kind == "works" else ""
    READ_OPERATIONS[f"index_candidates_{_kind}"] = f"""
MATCH (n:{_label})
WHERE ($cursor = '' OR n.id > $cursor)
RETURN n.id AS id, n.{_field} AS title,
       n.search_key_v1 AS search_key, n.search_source_v1 AS search_source
ORDER BY id
LIMIT $fetch_limit
""".strip()
    READ_OPERATIONS[f"index_coverage_{_kind}"] = f"""
MATCH (n:{_label})
RETURN count(n) AS total,
       count(CASE WHEN n.search_key_v1 IS NOT NULL
         AND n.search_key_v1 <> ''
         AND n.search_source_v1 = n.{_field} THEN 1 END) AS covered
""".strip()
    READ_OPERATIONS[f"indexed_{_kind}"] = f"""
MATCH (n:{_label})
WHERE n.search_key_v1 STARTS WITH $prefix
  AND n.search_source_v1 = n.{_field}
  AND ($cursor = '' OR n.id > $cursor)
  {_language}
RETURN n.id AS id, n.{_field} AS title, {_anchor} AS source_anchor,
       [] AS aliases
ORDER BY id
LIMIT $fetch_limit
""".strip()


# v0.8.4: validate the actual Neo4j physical range index before declaring
# indexed search available. A populated search_key property is not an index.
# This is a fixed read-only operation; the caller provides only an exact
# server-owned index name (never a Cypher fragment or dynamic label).
READ_OPERATIONS["index_state"] = """
SHOW INDEXES YIELD name, type, entityType, labelsOrTypes, properties, state
WHERE name = $index_name
RETURN name, type, entityType, labelsOrTypes, properties, state
""".strip()


# v0.8.11 fixed, bounded, metadata-only provenance reads. These are NOT
# checksums of the full corpus or certificates of text/edition usage rights.
READ_OPERATIONS["provenance_sources"] = """
MATCH (s:SourceRecord)
WHERE ($cursor = '' OR s.id > $cursor)
RETURN s.id AS id, s.provider AS provider, s.source_uri AS source_uri,
       s.version_id AS version_id, s.rights_tag AS rights_tag,
       s.checksum_sha256 AS checksum_sha256
ORDER BY id
LIMIT $fetch_limit
""".strip()

READ_OPERATIONS["provenance_editions"] = """
MATCH (ed:Edition)
WHERE ($cursor = '' OR ed.id > $cursor)
RETURN ed.id AS id, ed.work_id AS work_id,
       ed.version_id AS version_id, ed.language AS language,
       ed.rights_tag AS rights_tag,
       ed.rights_review_status AS rights_review_status,
       ed.allowed_text_redistribution AS allowed_text_redistribution
ORDER BY id
LIMIT $fetch_limit
""".strip()

READ_OPERATIONS["provenance_evidence"] = """
MATCH (ev:Evidence)
WHERE ($cursor = '' OR ev.id > $cursor)
RETURN ev.id AS id, ev.source_record_id AS source_record_id,
       ev.version_id AS version_id, ev.rights_tag AS rights_tag,
       ev.claim_kind AS claim_kind, ev.review_status AS review_status
ORDER BY id
LIMIT $fetch_limit
""".strip()
