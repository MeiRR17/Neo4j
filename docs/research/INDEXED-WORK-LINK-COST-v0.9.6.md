# v0.9.6 — Indexed Work-link query and pinned cost comparisons (DRAFT)

## Actual prior observations

The v0.9.5 GitHub Actions run 43099681819 at commit
ae10aad62fb7b5fb1be2278b0b52536711a14bee produced the sanitized
synthetic benchmark artifact 13891625668. Its measured median dbHits:

| Fixed operation | 32 synthetic links | 128 synthetic links |
| --- | ---: | ---: |
| Work descriptor | 12 | 12 |
| SOURCE_LINK left-to-right | 4,366 | 66,382 |
| SOURCE_LINK right-to-left | 4,366 | 66,382 |
| Incident frequency | 15 | 15 |

The directional query had 15.204x hit-count growth for a fourfold increase
in synthetic edges. Those tiny generated datasets are not a representative
scholarly workload or a production timing claim.

## Query optimization implemented

Previous source-and-target pattern started from both Work-property-bound
Passage nodes, then expanded the connecting SOURCE_LINK.

The new fixed read-only template explicitly:
1. Matches the source Passage where work_id equals the canonical source Work ID.
2. Uses the existing Neo4j Passage(work_id) index (passage_work_lookup,
   defined by migration 002_lookup_indexes.cypher).
3. Expands an outgoing SOURCE_LINK to the target Passage and filters its
   target work_id.
4. Requires a matching Evidence node for the edge ID and observed-source
   claim kind; projects exact Work, Passage, Edge, Evidence, source refs,
   versions and independent review states. It retains canonical edge-ID
   ordering and the original bounded result window.

There are no new schema migrations, destructive changes, writes, client
Cypher fragments, historical inference or rights approvals in the API.
An index hint is not proof of lower cost; the new plan must be measured.

## Pinned before/after evidence in CI

The CLI scripts/analytics_cost_delta_v096.py compares the current
32/128-link synthetic profile report against the exact pinned v0.9.5
historical dbHits. It rejects missing/duplicate fixture sizes, unexpected
operations, inflated sample counts, invalid medians, false release flags,
noncanonical evidence scope and reports that disclose query rows.

It emits only operation keys, old/new median dbHits, saved hits, fractional
change and 32-to-128 hit-growth factor; it never forwards untrusted plan
details, source rows, credentials, source text or names.

CI runs the normal isolated Neo4j functional tests, profiles the current
32/128 synthetic fixtures and retains a seven-day analytics-delta-v096-synthetic
artifact. The comparator marks regression_gate_enforced=false: the current
result must first be measured, validated and reviewed before a defendable
production-grade gate or cost SLO can be published.

## Research and deployment limitations

All data above are synthetic and the two fixture sizes are small.
There is no verified consistent graph snapshot across separate queries,
no global-authority metric, no independently dated authorship and no
validated literary or historical influence. Publisher/legal rights,
100+ human-reviewed links, 20 real expert-audited analysis cases, 50
authentic search judgments, DvirOS identity enforcement and realistic
scale benchmark approval remain required. Research status: HOLD.
