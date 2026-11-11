# v0.9.4 — Deterministic bounded comparison receipt (DRAFT)

## API

GET /v1/analysis/works/compare/receipt?left_work_id=work:CANONICAL&right_work_id=work:CANONICAL&limit=10

This private read-only endpoint reuses the same exact two canonical Work
identifiers and 1–10 per-direction result window as v0.9.3. The existing
bearer authentication and optional signed-call policy remain in effect.
Unknown, duplicated, or over-budget parameters fail before querying.

The response contains:
- **comparison**: the complete v0.9.3 typed comparison with both
  directional SOURCE_LINK evidence trails, source references and review
  status counts, plus sampled author metadata.
- **observation_sha256**: SHA-256 of the comparison mapping encoded with
  json.dumps(..., sort_keys=True, ensure_ascii=False,
  separators=(",", ":"), allow_nan=False).encode("utf-8").
  This is exactly the validated bounded *returned* metadata, not a raw
  corpus snapshot, full index, source-text checksum or signed attestation.
- **fixed_query_templates_sha256**: SHA-256 of the mapping
  {"analysis_work_cross_links": checked_in_cypher,
   "analysis_work_descriptor": checked_in_cypher}, using the same encoding.
  This identifies read template text, not deployment identity or data
  revision. SHA values are lowercase hex.
- **observed_link_count**: the number of included directional link rows,
  not the total number in the database; at most 20.
- **sample_window_truncated**: whether either directional edge window or
  either displayed author window had an extra lookahead row.
- Explicit FALSE flags for graph snapshot, full corpus coverage,
  digital receipt signature, source rights and historical influence,
  with research_release_status=HOLD.

The Work author query now sorts Person IDs before taking the three-row
author lookahead. The SOURCE_LINK windows also order by canonical edge
ID. A digest is repeatable for the *same returned ordered records and
template text*, not a guarantee that four independent read transactions
observe a coherent graph revision. Unicode codepoints are NOT rewritten
or normalized by this receipt layer; byte-identical encoding is required.

## Bounded reproducibility and performance fixture

Synthetic unit tests cover 20 distinct fabricated Work/evidence patterns
and repeat each to verify exact digest equality. They also change
evidence review state, query template text and dictionary key insertion
order and assert the documented digest behavior. Unsafe backend text,
malformed identities or years, over-budget samples and unknown request
parameters continue to fail closed.

The isolated, disposable Neo4j CI smoke uses:
- 2 synthetic Works, 2 synthetic Person author records;
- 1 directed cross-Work SOURCE_LINK with its Evidence node
  (additional same-Work links are fixture setup for earlier API checks);
- 20 sequential authenticated receipt HTTP calls to one unchanged fixture;
- p50 (median) and p95 (nearest-rank) response latency in milliseconds
  logged without text, credentials, endpoint authentication or source bytes.

These measurements are descriptive of an intentionally tiny CI fixture.
They do not establish real-source correctness, query scalability,
representative performance or a service-level objective. An output row
limit does not prove a bound on underlying graph scan work.

## Scholarly, rights and deployment blockers

This version has no independent source licenses, signed receipts, persistent
snapshot identifier, multi-query isolation, real audited 100+ links,
20 human-reviewed analytical examples, independently verified historical
authorship/chronology, 50 real search judgments, DvirOS SSO/RBAC or
production release authorization. All public and scholarly claims remain
on HOLD; hashes do not authenticate research sources or prove influence.
