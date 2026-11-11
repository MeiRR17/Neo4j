# v0.9.3 — Two-Work comparison with source-evidence trails (DRAFT)

This is a metadata-only **exploratory** query. It is not an academic finding,
a license clearance mechanism, a ranking, or proof of historical influence.

## Endpoint

GET /v1/analysis/works/compare?left_work_id=work:CANONICAL&right_work_id=work:CANONICAL&limit=10

Requests use the existing private bearer authentication and optional
DvirOS signed-call restriction. Both IDs must be distinct canonical Works.
Unknown/duplicated filters and limits outside 1–10 are rejected. Missing
Works return 404, never a synthetic comparison.

The endpoint runs two fixed read-only Work descriptor queries and two
fixed, directional SOURCE_LINK queries with reversed Work parameters.
Every link must match an actual Evidence node, and both records must
declare OBSERVED_SOURCE_LINK. Each direction returns up to 10 rows,
ordered by canonical edge ID; one lookahead row sets has_more. Links
include source and target Work IDs, exact passage IDs, Evidence ID and
edge ID, two review states, passage source references, optional Evidence
source reference, version ID and rights tag.

Per direction, observed_window_denominator counts **only displayed**
links; joint_approved_status_links counts edges where both internal
reviews say approved, contested counts either rejected/disputed layer,
and pending counts all other states. Neither a count nor an internal
approval is a scholarly, legal or rights determination.

Work descriptors include title, provider reference, and up to 2 Person
author IDs and recorded lifetime ranges. A third record indicates a
truncated sample. Author-ID overlap is reported only when both sampled
author lists are nonempty and not truncated; otherwise the relation is
insufficient_author_metadata. An observed shared Person ID is catalog
metadata, not independently certified common authorship. Year metadata
does not establish work composition, publication, chronology or influence.

## Failure behavior

Unexpected source-text fields, invalid canonical or Work-membership IDs,
malformed author years, repeated author identities, mismatched directed
work links, duplicate evidence/edges, unsafe review states and oversized
windows are denied with a sanitized database-unavailable response.
No public network endpoint, full-text graph read or write is exposed.

## Explicit limitations

- A has_more=false result only indicates exhaustion of this read's
  bounded query; it is NOT a transactionally frozen or complete corpus.
- Two directions are observed separately; a multi-query snapshot is
  not verified, and a source-side may change between reads.
- The present Neo4j model does not contain independently validated
  editions, author attribution, dated composition or legal licenses.
- Database 5-second query timeout and 2 MB response guard remain
  active. A bounded output does not prove bounded graph scan cost.
- All generated samples and isolated CI tests use fabricated identities.
- Research approval and production release remain HOLD pending verified
  source/edition rights, 100+ manually reviewed links, 20 actual
  analytical cases, 50 reviewed search questions, benchmarks,
  DvirOS SSO/RBAC and release signoff.
