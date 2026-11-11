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
   target work_id with coalesce(b.work_id, ''). This preserves equality for
   a nonempty canonical Work ID, while avoiding a second independent
   indexable target-Passage predicate as a join starting point.
4. Requires a matching Evidence node for the edge ID and observed-source
   claim kind; projects exact Work, Passage, Edge, Evidence, source refs,
   versions and independent review states. It retains canonical edge-ID
   ordering and the original bounded result window.

There are no new schema migrations, destructive changes, writes, client
Cypher fragments, historical inference or rights approvals in the API.
The first index-hinted trial produced NO improvement at the same fixture
sizes. Only the refined target condition, which prevents the planner
from independently seeding the target Work side, yielded lower measured
database hits. The result was verified using run 43102371908 (exact
commit fb4240e649ea750a8617a8bc60350824c6f32f6d) and delta
artifact 13892712664:

| Graph links | Baseline dbHits per direction | Refined dbHits | Reduction |
| --- | ---: | ---: | ---: |
| 32 | 4,366 | 334 | 92.35% |
| 128 | 66,382 | 1,102 | 98.34% |

For 4x growth in the number of synthetic links, dbHits grew only 3.299x
rather than 15.204x. Descriptor (12) and incident frequency (15) costs
remained unchanged. No real-corpus speedup is inferred.

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
artifact. After the measured improvement, CI additionally calls
--require-synthetic-cost-gate. This fail-closed mode requires no more than
600 dbHits per direction at 32 links and 2,400 at 128 links, with a
growth factor no higher than 6.0. Work-descriptor and incident-frequency
caps are 30 and 40 dbHits, respectively, at either size.
These fixture-specific ceilings allow headroom above the observed 334/
1,102 hits, while preventing a return to the old quadratic join in CI.
The final sanitized report includes regression_gate_enforced=true and
synthetic_regression_gate_passed=true only after the gate passes.
This is NOT a production performance SLO or proof of real-world scale.

## Research and deployment limitations

All data above are synthetic and the two fixture sizes are small.
There is no verified consistent graph snapshot across separate queries,
no global-authority metric, no independently dated authorship and no
validated literary or historical influence. Publisher/legal rights,
100+ human-reviewed links, 20 real expert-audited analysis cases, 50
authentic search judgments, DvirOS identity enforcement and realistic
scale benchmark approval remain required. Research status: HOLD.
