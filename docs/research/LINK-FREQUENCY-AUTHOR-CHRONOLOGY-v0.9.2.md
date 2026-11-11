# v0.9.2 — Observed source-link frequencies and author chronology (DRAFT)

Both operations are private and read-only. They do not grant permission to
release scholarly content or certify a historical influence relationship.

## 1. SOURCE_LINK sample frequency

GET /v1/analysis/metrics/link-frequency?passage_id=passage:CANONICAL

The fixed graph query returns at most 51 incident SOURCE_LINK records, sorted
by canonical edge ID, only where a matching Evidence node claims
OBSERVED_SOURCE_LINK. The response validates all 51 and counts the first 50.
No client-adjustable window or arbitrary query is allowed.

- observed_link_denominator: distinct validated links counted, 0–50.
- outgoing_observed_links / incoming_observed_links: explicit direction.
- joint_approved_status_links: BOTH relationship and Evidence have internal
  approved status, NOT a rights license or real expert quality signoff.
- contested_status_links: either layer is rejected or disputed.
- pending_status_links: remaining status combinations.
- joint_approved_status_fraction: approved pair count / denominator, rounded
  to four decimals, or null when denominator is zero.
- window_truncated: an extra row exists; more links remain uncounted.

This is a bounded frequency of observed records, not centrality, population
coverage, authority, relevance ranking or source verification.

## 2. Tentative author lifetime metadata

GET /v1/analysis/chronology/author-lifetimes?source_id=passage:CANONICAL&target_id=passage:CANONICAL

The fixed graph query selects ONE direct, direction-specific SOURCE_LINK,
with a matching Evidence node, eligible claim kind and no rejected/disputed
review state. It requires Work IDs from both Passages and reads up to two
AUTHORED-linked Person records per Work. Person.date_from_year and
Person.date_to_year are unverified metadata. Exactly one fully dated author
per distinct Work is required for an interval comparison.

Missing, same-Work, ambiguous or partial year metadata yields status and
unknown, not a guessed answer. Disjoint author lifetimes do NOT establish
composition/publication dates or citation direction, and the existence of a
SOURCE_LINK does NOT prove scholarly influence. Author metadata may be
unverified even if a SOURCE_LINK is internally marked approved.

## Security and remaining gates

- Service-level bearer and optional signed-call policy remain mandatory.
- Only exact documented query keys are allowed; duplicates are rejected.
- Invalid canonical IDs, duplicate Evidence, malformed year intervals,
  oversized rows and unexpected properties fail closed.
- All outputs explicitly deny independent historical proof, corpus snapshot
  consistency, rights clearance and research release; status HOLD.
- Query timeout and response caps still apply. Fixed output windows do not
  guarantee bounded underlying database work.
- Synthetic tests and isolated disposable Neo4j fixtures are not expert
  review or production validation.

The v0.9.0 acceptance gate remains incomplete: real expert-reviewed links
and case studies, historically validated dates, measured graph performance,
licensed source/edition rights, DvirOS SSO/RBAC and production signoff.
