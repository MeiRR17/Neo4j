# v0.7.1 — Evidence trail for bounded graph neighborhoods

This update extends the **existing private, signed** Neo4j Research API.
It does not download or distribute licensed book text.

Every traversed graph relation now carries a typed provenance projection:
`evidence_id`, `source_record_id`, `source_ref`, `source_uri`,
`link_category`, `rights_tag`, and an **independent**
`evidence_review_status`. These fields are read from the actual Evidence
node referenced by the relationship; they are never inferred from the
graph endpoints. The graph traversal remains undirected and does not
establish citation direction or historical influence.

The Cypher query first bounds candidate paths using the existing
`fetch_limit`, then reads the Evidence records for those paths. Cypher
values remain parameterized, and no full text / arbitrary properties are
returned. Missing evidence records remain excluded by the existing
evidence-match predicate.

The v0.5 `Neighborhood` envelope is unchanged; optional fields
extend `GraphRelation` without adding a new write surface. The DvirOS
Graph Explorer in the paired PR displays source references and allows
only provided, validated HTTPS Sefaria URIs to be opened. Export URLs
and other arbitrary source domains are not automatically converted into
Sefaria passage links.

**Validation:** existing FastAPI contract tests, synthetic real-Neo4j
`scripts/api_smoke.py` with exact source metadata assertions, schema
migration tests, and signed v0.6 integration smoke. These are synthetic
technical tests; the v0.4 human research approval gates remain blocked.

**Release constraint:** Neo4j metadata alone must not be rendered as a
verified academic citation. DvirOS still lacks active user sessions and
its Graph Explorer remains locked from live data.
