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


# v0.9.0: evidence-linked, metadata-only exploratory analytics.
# Caller can only supply a canonical passage ID and a bounded row limit.
READ_OPERATIONS["analysis_source_links"] = """
MATCH (a:Passage)-[r:SOURCE_LINK]->(b:Passage)
MATCH (ev:Evidence {id:r.evidence_id})
WHERE (a.id = $id OR b.id = $id)
  AND r.id IS NOT NULL
  AND r.claim_kind = 'OBSERVED_SOURCE_LINK'
  AND ev.claim_kind = 'OBSERVED_SOURCE_LINK'
  AND r.review_status IN ['unreviewed','approved','rejected','disputed']
  AND ev.review_status IN ['unreviewed','approved','rejected','disputed']
RETURN r.id AS id, a.id AS source_passage_id,
       b.id AS target_passage_id, ev.id AS evidence_id,
       r.claim_kind AS claim_kind, r.review_status AS review_status,
       ev.review_status AS evidence_review_status,
       ev.source_ref AS source_ref, ev.version_id AS version_id,
       ev.rights_tag AS rights_tag
ORDER BY id
LIMIT $fetch_limit
""".strip()

READ_OPERATIONS["analysis_shared_targets"] = """
MATCH (focus:Passage {id:$id})-[fr:SOURCE_LINK]->(target:Passage)
MATCH (candidate:Passage)-[cr:SOURCE_LINK]->(target)
MATCH (fe:Evidence {id:fr.evidence_id})
MATCH (ce:Evidence {id:cr.evidence_id})
WHERE candidate.id <> $id
  AND fr.id IS NOT NULL AND cr.id IS NOT NULL
  AND fr.claim_kind = 'OBSERVED_SOURCE_LINK'
  AND cr.claim_kind = 'OBSERVED_SOURCE_LINK'
  AND fe.claim_kind = 'OBSERVED_SOURCE_LINK'
  AND ce.claim_kind = 'OBSERVED_SOURCE_LINK'
  AND fr.review_status IN ['unreviewed','approved','rejected','disputed']
  AND cr.review_status IN ['unreviewed','approved','rejected','disputed']
  AND fe.review_status IN ['unreviewed','approved','rejected','disputed']
  AND ce.review_status IN ['unreviewed','approved','rejected','disputed']
RETURN candidate.id AS candidate_passage_id,
       target.id AS shared_target_passage_id,
       fe.id AS focus_evidence_id, ce.id AS candidate_evidence_id,
       fr.review_status AS focus_review_status,
       cr.review_status AS candidate_review_status,
       fe.review_status AS focus_evidence_review_status,
       ce.review_status AS candidate_evidence_review_status,
       fe.source_ref AS focus_source_ref,
       ce.source_ref AS candidate_source_ref
ORDER BY candidate_passage_id, shared_target_passage_id,
         focus_evidence_id, candidate_evidence_id
LIMIT $fetch_limit
""".strip()


# v0.9.1: fixed directed SOURCE_LINK path queries (1 or 2 hops only).
# No arbitrary Cypher or client-controlled relationship type / path length.
# Only unreviewed or approved edges AND matching Evidence can participate.
READ_OPERATIONS["analysis_path_direct"] = """
MATCH (s:Passage {id:$source_id})-[r:SOURCE_LINK]->(t:Passage {id:$target_id})
MATCH (ev:Evidence {id:r.evidence_id})
WHERE r.id IS NOT NULL
  AND r.claim_kind = 'OBSERVED_SOURCE_LINK'
  AND ev.claim_kind = 'OBSERVED_SOURCE_LINK'
  AND r.review_status IN ['unreviewed', 'approved']
  AND ev.review_status IN ['unreviewed', 'approved']
WITH s,t,r,ev ORDER BY r.id
RETURN [s.id, t.id] AS passage_ids,
       [{edge_id:r.id, from_passage_id:s.id, to_passage_id:t.id,
         evidence_id:ev.id, claim_kind:r.claim_kind,
         edge_review_status:r.review_status,
         evidence_review_status:ev.review_status,
         source_ref:ev.source_ref, version_id:ev.version_id,
         rights_tag:ev.rights_tag}] AS edges, 1 AS hop_count
LIMIT $fetch_limit
""".strip()

READ_OPERATIONS["analysis_path_two_hop"] = """
MATCH (s:Passage {id:$source_id})-[a:SOURCE_LINK]->(m:Passage)
      -[b:SOURCE_LINK]->(t:Passage {id:$target_id})
MATCH (ea:Evidence {id:a.evidence_id})
MATCH (eb:Evidence {id:b.evidence_id})
WHERE m.id <> s.id AND m.id <> t.id
  AND a.id IS NOT NULL AND b.id IS NOT NULL AND a.id <> b.id
  AND ea.id <> eb.id
  AND a.claim_kind = 'OBSERVED_SOURCE_LINK'
  AND b.claim_kind = 'OBSERVED_SOURCE_LINK'
  AND ea.claim_kind = 'OBSERVED_SOURCE_LINK'
  AND eb.claim_kind = 'OBSERVED_SOURCE_LINK'
  AND a.review_status IN ['unreviewed', 'approved']
  AND b.review_status IN ['unreviewed', 'approved']
  AND ea.review_status IN ['unreviewed', 'approved']
  AND eb.review_status IN ['unreviewed', 'approved']
WITH s,m,t,a,b,ea,eb ORDER BY m.id,a.id,b.id
RETURN [s.id, m.id, t.id] AS passage_ids,
       [{edge_id:a.id, from_passage_id:s.id, to_passage_id:m.id,
         evidence_id:ea.id, claim_kind:a.claim_kind,
         edge_review_status:a.review_status,
         evidence_review_status:ea.review_status,
         source_ref:ea.source_ref, version_id:ea.version_id,
         rights_tag:ea.rights_tag},
        {edge_id:b.id, from_passage_id:m.id, to_passage_id:t.id,
         evidence_id:eb.id, claim_kind:b.claim_kind,
         edge_review_status:b.review_status,
         evidence_review_status:eb.review_status,
         source_ref:eb.source_ref, version_id:eb.version_id,
         rights_tag:eb.rights_tag}] AS edges, 2 AS hop_count
LIMIT $fetch_limit
""".strip()


# v0.9.2: a fixed 50+1 incident source-link metadata sample, ordered by
# canonical edge ID. This is NOT whole-graph centrality or an inferred citation.
READ_OPERATIONS["analysis_frequency_window"] = """
MATCH (p:Passage {id:$passage_id})-[r:SOURCE_LINK]-(q:Passage)
MATCH (ev:Evidence {id:r.evidence_id})
WHERE r.id IS NOT NULL
  AND r.claim_kind = 'OBSERVED_SOURCE_LINK'
  AND ev.claim_kind = 'OBSERVED_SOURCE_LINK'
  AND r.review_status IN ['unreviewed','approved','rejected','disputed']
  AND ev.review_status IN ['unreviewed','approved','rejected','disputed']
RETURN r.id AS edge_id, startNode(r).id AS source_passage_id,
       endNode(r).id AS target_passage_id,
       ev.id AS evidence_id, r.review_status AS edge_review_status,
       ev.review_status AS evidence_review_status
ORDER BY edge_id
LIMIT $fetch_limit
""".strip()

# v0.9.2: only a direct evidenced SOURCE_LINK (never arbitrary pairings) can
# carry a tentative author-lifetime comparison. Author lists are capped at 2
# to detect missing/ambiguous authorships without fabricating a date.
READ_OPERATIONS["analysis_author_lifetimes"] = """
MATCH (s:Passage {id:$source_id})-[r:SOURCE_LINK]->(t:Passage {id:$target_id})
MATCH (ev:Evidence {id:r.evidence_id})
WHERE r.id IS NOT NULL
  AND r.claim_kind = 'OBSERVED_SOURCE_LINK'
  AND ev.claim_kind = 'OBSERVED_SOURCE_LINK'
  AND r.review_status IN ['unreviewed','approved']
  AND ev.review_status IN ['unreviewed','approved']
WITH s,t,r,ev ORDER BY r.id LIMIT 1
MATCH (sw:Work {id:s.work_id})
MATCH (tw:Work {id:t.work_id})
RETURN r.id AS edge_id, ev.id AS evidence_id,
       s.id AS source_passage_id, t.id AS target_passage_id,
       sw.id AS source_work_id, tw.id AS target_work_id,
       [(sw)<-[:AUTHORED]-(sa:Person) |
         {id:sa.id, date_from_year:sa.date_from_year,
          date_to_year:sa.date_to_year}][..2] AS source_authors,
       [(tw)<-[:AUTHORED]-(ta:Person) |
         {id:ta.id, date_from_year:ta.date_from_year,
          date_to_year:ta.date_to_year}][..2] AS target_authors
LIMIT 1
""".strip()


# v0.9.3: a bounded Work descriptor with a third author reference as
# lookahead to expose ambiguity. No source text or identity assertion.
READ_OPERATIONS["analysis_work_descriptor"] = """
MATCH (w:Work {id:$work_id})
OPTIONAL MATCH (w)<-[:AUTHORED]-(p:Person)
WITH w, p ORDER BY p.id
WITH w, collect(p)[..3] AS author_window
RETURN w.id AS id, w.title AS title, w.provider_ref AS provider_ref,
       [person IN author_window |
         {id:person.id, date_from_year:person.date_from_year,
          date_to_year:person.date_to_year}] AS author_sample
LIMIT 2
""".strip()

# v0.9.6 refinement: target coalesce() preserves nonempty canonical ID
# equality without a separate target-side indexed join predicate.
# v0.9.6: start at :Passage(work_id) via migration 002's existing
# passage_work_lookup index, then expand only directed SOURCE_LINKs and
# filter target Work. Do not independently seed both sides of a large
# potential cross join; preserve exact Evidence membership and ordering.
# v0.9.3: separate fixed, directed, bounded source-link windows between
# two canonical Work IDs, with per-link Evidence verification. Query twice
# with reversed parameters to avoid silently collapsing direction.
READ_OPERATIONS["analysis_work_cross_links"] = """
MATCH (a:Passage {work_id:$source_work_id})
USING INDEX a:Passage(work_id)
WITH a
MATCH (a)-[r:SOURCE_LINK]->(b:Passage)
WHERE coalesce(b.work_id, '') = $target_work_id
MATCH (ev:Evidence {id:r.evidence_id})
WHERE r.id IS NOT NULL
  AND r.claim_kind = 'OBSERVED_SOURCE_LINK'
  AND ev.claim_kind = 'OBSERVED_SOURCE_LINK'
  AND r.review_status IN ['unreviewed','approved','rejected','disputed']
  AND ev.review_status IN ['unreviewed','approved','rejected','disputed']
RETURN r.id AS edge_id, a.work_id AS source_work_id,
       b.work_id AS target_work_id, a.id AS source_passage_id,
       b.id AS target_passage_id, ev.id AS evidence_id,
       r.review_status AS edge_review_status,
       ev.review_status AS evidence_review_status,
       a.source_ref AS source_ref, b.source_ref AS target_ref,
       ev.source_ref AS evidence_source_ref,
       ev.version_id AS version_id, ev.rights_tag AS rights_tag
ORDER BY edge_id
LIMIT $fetch_limit
""".strip()


# v0.9.9: keyset page of directed source links, only after a canonical edge
# ID. Exactly one Work-side index anchor, then directional expansion and
# Evidence-node verification. Stable edge ordering is not a graph snapshot.
READ_OPERATIONS["analysis_work_cross_link_page"] = """
MATCH (a:Passage {work_id:$source_work_id})
USING INDEX a:Passage(work_id)
WITH a
MATCH (a)-[r:SOURCE_LINK]->(b:Passage)
WHERE coalesce(b.work_id, '') = $target_work_id
  AND r.id > $after_edge_id
MATCH (ev:Evidence {id:r.evidence_id})
WHERE r.claim_kind = 'OBSERVED_SOURCE_LINK'
  AND ev.claim_kind = 'OBSERVED_SOURCE_LINK'
  AND r.review_status IN ['unreviewed','approved','rejected','disputed']
  AND ev.review_status IN ['unreviewed','approved','rejected','disputed']
RETURN r.id AS edge_id, a.work_id AS source_work_id,
       b.work_id AS target_work_id, a.id AS source_passage_id,
       b.id AS target_passage_id, ev.id AS evidence_id,
       r.review_status AS edge_review_status,
       ev.review_status AS evidence_review_status,
       a.source_ref AS source_ref, b.source_ref AS target_ref,
       ev.source_ref AS evidence_source_ref,
       ev.version_id AS version_id, ev.rights_tag AS rights_tag
ORDER BY edge_id
LIMIT $fetch_limit
""".strip()
