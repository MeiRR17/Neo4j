# v0.9.8 — Cross-Work distractor isolation benchmark (DRAFT)

## Rationale

The v0.9.6 query optimization reduced SOURCE_LINK costs on two-Work,
32/128-link graphs, and v0.9.7 extended those tests to fanout-heavy
256/512-link graphs. Neither fixture investigated **unrelated Work growth**:
a planner regression could scan extra Works even when the queried pair
and its answer set remained unchanged.

v0.9.8 is a bounded, synthetic diagnostic probe of that specific risk.
It neither proves global workload selectivity nor validates source rights.

## Workload and expected results

The same *population shape* for two selected Works is generated in
each case, with exactly 128 directed SOURCE_LINKs alternating directions.
Two **other** Works and their two Person author records exist throughout.
Additional SOURCE_LINK relationships bind only those unrelated Works:

| Case | Selected links | Unrelated links | Total links | Works |
| --- | ---: | ---: | ---: | ---: |
| control-0 | 128 | 0 | 128 | 4 |
| distractor-128 | 128 | 128 | 256 | 4 |
| distractor-512 | 128 | 512 | 640 | 4 |

Every Passage, Evidence and SOURCE_LINK edge is given a canonical,
namespaced deterministic identity. Source anchors are fabricated.
A unique fixture SHA-256 describes each generated graph.

Three repeats each of the same four fixed read-only operations:
Work descriptor (expected 1 row), forward / reverse 11-row Work-link
windows, and incident frequency of a selected Passage (expected 1 row).
The first 128 selected links remain semantically identical in shape
even as unrelated graph links grow. All 36 PROFILE calls are made only
against disposable CI Neo4j using the existing loopback transport and
read-only query registry. No dynamic Cypher or real corpus is ingested.

The report compares median dbHits with the 0-distractor case and
includes absolute added hits and a ratio per operation, plus bounded
operator and timing metrics. It never includes query output records,
plan Details, credentials, user source text or IDs.

## Security and cleanup

Both CI=true and --ack-disposable-fixture are required, including for
the library entrypoint. Before any write, the runner checks that the
exact generated node inventory is absent. The only writes create the
four synthetic Works and authors and the fixed row populations, with
bounded batch sizes. Cleanup uses only exact generated node IDs and
recounts them afterward, even if seeding or profiling fails; failure
to clean up fails the workflow.

The first complete GitHub Actions Neo4j test (run #43108294329,
head 2e8faf491b1c7ec1b8fe150d0b4850727474ef42, artifact
#13895291726) recorded these synthetic median dbHits:

| Operation | 0 distractors | 128 distractors | 512 distractors |
| --- | ---: | ---: | ---: |
| Work descriptor | 12 | 12 | 12 |
| SOURCE_LINK left-to-right | 1,102 | 1,102 | 1,102 |
| SOURCE_LINK right-to-left | 1,102 | 1,102 | 1,102 |
| Incident frequency | 15 | 15 | 15 |

No full/label scan or expensive-join operator was observed. The recorded
ratio-to-control was 1.0 for all operations and all three cases.

Following those observations, the new scripts/analytics_distractor_gate_v098.py
CI gate validates **exact fixture SHA-256 fingerprints** and all three
case populations, rejects any unsafe or unexpected projection fields,
and enforces both absolute synthetic budgets and relative interference:
Work descriptors <=30 dbHits, directional links <=1,600 dbHits,
incident frequency <=30 dbHits, and every observed ratio-to-control
<=1.25 (25% headroom). It also rejects full/label scans, expensive
joins, malformed row counts, invalid timing or risk/rights claims.
The gate result is archived alongside the sanitized 36-observation
report for seven days.

The pre-existing v0.9.6 and v0.9.7 cost regression guards are unchanged.
All three sets of thresholds concern tiny, fabricated CI fixtures;
they are neither representative production performance SLOs nor
research-quality approval.

## What this does not establish

All measurements are synthetic, local, sequential, and subject to
Neo4j plan-cache and runner effects. Comparisons across separate
temporary fixtures are not transactionally snapshot-consistent.
No representative production cost, legal source rights, scholarly
authorship/historical influence, 100+ manually reviewed links, 20 real
case studies, SSO/RBAC or formal release approval is certified. HOLD.
