# v0.9.1 — Evidence-bounded directed shortest observed path (DRAFT)

## What is implemented

GET /v1/graph/evidence-path?source_id=passage:CANONICAL&target_id=passage:CANONICAL&limit=5

The existing private bearer and optional DvirOS signed-call check apply.
Only two distinct canonical passage IDs are accepted, with optional limit
1..10. Unknown/duplicated query parameters are rejected. The client
cannot choose Cypher, edges, direction, hops, or source licensing status.

The server checks a direct directed SOURCE_LINK relationship first. Only
if none is returned does it check two directed hops. The implementation
uses **two fixed read-only Cypher operations**; each relationship must
reference an actual Evidence node with matching OBSERVED_SOURCE_LINK
claim-kind and an unreviewed/approved edge and Evidence review state.
Rejected and disputed records never silently become support. The
2-hop query excludes same-node cycles and reused edge/evidence IDs.

Responses include ordered canonical passage IDs, separate edge IDs,
Evidence IDs, source references, reported version and rights tags,
and both edge and Evidence review states. The result is bounded to
ten paths plus one lookahead. Empty results are reported as unobserved,
not fabricated as a negative scholarly finding.

## Boundaries and interpretation

- Direct paths take priority over 2-hop alternatives; this is the
  shortest *eligible directed path in the 1–2 hop subset at observation
  time*, not a global graph shortest-path proof.
- A 5-second database timeout and row/response budgets remain in effect.
  Output caps do NOT guarantee cheap underlying graph scans.
- Multiple requests are not transactionally isolated as a snapshot.
- Reported evidence status does NOT establish a rights license,
  verified source-provider identity, reliable historical chronology,
  causation, intellectual influence, a direct citation, or consensus.
- The linked records are currently metadata-only. No unlicensed source
  text is downloaded or returned.
- Every response explicitly sets whole_graph_shortest_path_proven,
  graph_snapshot_isolation_verified, historical_influence_proven,
  source_rights_verified to false; research_release_status is HOLD.

Synthetic unit/API tests cover missing auth, unsafe filters, tampered
paths, unapproved statuses, duplicate evidence and two-hop path selection.
The isolated, disposable Neo4j CI smoke inserts three synthetic passages
and two synthetic source-linked Evidence nodes, verifies 1-hop and 2-hop
paths and reverse-direction denial, then cleans all generated nodes.

## Remaining v0.9 research gate

Still unimplemented: provenance-aware longer paths under a measured
performance budget, defined frequency/centrality metrics with denominators,
chronological constraints and author/work comparisons. Existing quality
gates still require 100+ human-checked links, 20 reviewed analytical
examples, 50 genuinely reviewed search questions, source/edition rights
approval, DvirOS SSO/RBAC and independent release authorization.
