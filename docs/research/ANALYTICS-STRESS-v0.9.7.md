# v0.9.7 — High-fanout and distributed source-link stress (DRAFT)

This release extends the graph-cost experiments to four *synthetic* cases.
It does not assert that real scholarly corpora have this size or distribution.

## Fixed, versioned fixture matrix

| Case | Directed SOURCE_LINKs | Distinct Passages | Maximum source out-degree |
| --- | ---: | ---: | ---: |
| disjoint-256 | 256 | 512 | 1 |
| hub-256 | 256 | 385 | 128 |
| disjoint-512 | 512 | 1,024 | 1 |
| hub-512 | 512 | 769 | 256 |

Each case contains two synthetic Works, two synthetic Person authors
and one distinct Evidence node per SOURCE_LINK. Direction alternates
between the two Works; in hub cases one left-Work source Passage is shared
by all left-to-right links. The fixture hash, identities, namespace and
source anchors are generated deterministically, but only an SHA-256 and
aggregate counts enter the final report.

## Fixed read-only queries and expected cardinalities

The workload runs the existing registered ANALYSIS queries without allowing
client Cypher, variable run sizes or plan alteration. For each of the four
cases, four operations are PROFILEd exactly three times:
- Work descriptor: one returned Work metadata row;
- forward left→right cross-Work links: 11 returned rows (10 + lookahead);
- reverse right→left: 11 returned rows;
- incident frequency for the first synthetic source: 1 for disjoint cases,
  and 51 for hub cases (50 + one lookahead).

These row expectations are asserted; other counts or request shapes fail
closed. The profiler enforces a 250,000-database-hit maximum, a small
operator-tree depth/node count, 256 KB response ceiling, five-second graph
execution timeout and eight-second network timeout.

The report records only each operation's count, sanitized operator/scan
flags, minimum/median/maximum dbHits, descriptive three-sample HTTP p50
and nearest-rank p95, and 256→512 hit growth per topology. It does not
emit query result rows, Neo4j plan Details, titles, canonical IDs or source
content. Performance claims are limited to the reported generated cases.

## Write-scope security and cleanup

The runner requires both CI=true and the explicit
--ack-disposable-fixture flag; library access requires acknowledged_disposable.
It accepts only the complete four-case matrix, and connects exclusively via
the existing loopback-only local Neo4j clients. It first checks that none of
its exact namespaced node IDs exist before seeding. Cleanup uses only these
IDs, runs in finally even when seeding or PROFILE fails, and verifies that
the node inventory is empty. A failed cleanup fails the workflow. The
environment itself must remain disposable; a database outage could prevent
cleanup and therefore never authorizes running this script in production.

## CI evidence and remaining qualification

The first v0.9.7 four-case CI report was measured successfully in GitHub
Actions run #43105105335, commit 194caddf0232c515254f72b8e6ed97c4c55fc1b7:

| Fixture | Work descriptor dbHits | Work links L→R / R→L | Incident frequency |
| --- | ---: | ---: | ---: |
| disjoint-256 | 12 | 2,126 / 2,126 | 15 |
| hub-256 | 12 | 1,873 / 2,126 | 1,386 |
| disjoint-512 | 12 | 4,174 / 4,174 | 15 |
| hub-512 | 12 | 3,665 / 4,174 | 2,666 |

The highest observed 256→512 growth was 1.963x for cross-Work links
and 1.924x for hub frequency. The v0.9.6 synthetic 32/128 regression
gate remains unchanged. Based on these results, a SECOND CI-only guard
now fails on excessive fixed-fixture dbHits, potentially expensive join
operators or full/label scans, or cost growth beyond 2.8x for a twofold
fixture increase. Its ceiling matrix is conservative relative to observed
synthetic costs:

| Fixture | Work descriptor max | L→R max | R→L max | Frequency max |
| --- | ---: | ---: | ---: | ---: |
| disjoint-256 | 30 | 3,000 | 3,000 | 40 |
| hub-256 | 30 | 2,700 | 3,000 | 2,000 |
| disjoint-512 | 30 | 6,000 | 6,000 | 40 |
| hub-512 | 30 | 5,300 | 6,000 | 3,800 |

The guard verifies deterministic fixture SHA-256 and exact identities,
input cardinalities and review-nonclaim flags, and outputs only validated
allowlisted counters. It is executable in CI via
scripts/analytics_stress_gate_v097.py; its sanitized result is archived
alongside the original stress report in the seven-day
analytics-stress-v097-synthetic artifact.

No production performance SLO is inferred from this small experiment.

Pending acceptance includes representative corpora and dates, source and
edition permissions, at least 100 genuinely human-reviewed source links,
20 real audited analysis cases, 50 reviewed search questions, DvirOS
SSO/RBAC, and benchmark reproducibility across realistic deployments.
The full scholarly and public release status remains HOLD.
