# v0.9.9 — Evidence-linked Work source audit (DRAFT)

## Purpose

The v0.9.3 Work comparison returns only the first ten observed links
in each direction, and v0.9.4 fingerprints that one bounded result.
Researchers also need to inspect *subsequent* metadata windows, without
exposing source text or claiming that a generated relationship is a
historical citation. v0.9.9 introduces a private, strictly bounded keyset
page for that workflow.

## API contract

Authenticated GET /v1/analysis/works/links/audit accepts exactly:

| Query parameter | Allowed value | Default |
| --- | --- | --- |
| source_work_id | Canonical work:SHA256 identifier, required | — |
| target_work_id | Different canonical work:SHA256 identifier, required | — |
| cursor | Canonical edge:SHA256 ID from a previous page | omitted |
| limit | Integer from 1 to 20 | 10 |

Duplicate or unknown parameters are rejected with HTTP 422. An
unconfigured/missing token fails authentication before querying.
Missing Work records return HTTP 404. Unsafe graph data and inaccessible
storage produce sanitized HTTP 503 responses.

Successful responses use strict WorkLinkAuditPage schema 0.9.9. They
include a *single directed* set of up to 20 WorkCrossLink rows, the
canonical source/target Passage/Edge/Evidence IDs, separate
SOURCE_LINK/Evidence review states, source metadata anchors, version and
rights tags, and joint-approved/contested/pending counters. The sum of
these counters equals the number of included rows, not any global corpus
population. Every graph field is validated against an exact allowlist.

The next_cursor is the last **included** edge ID only when the one-row
lookahead indicates another eligible record. To continue, send the same
source_work_id and target_work_id and set cursor=next_cursor. The
query filters r.id > cursor and orders by edge_id; lookahead records
are inspected but never returned on that page. An empty or exhausted
page reports next_cursor=null.

The fixed Cypher anchors the source Passage using migration 002's
Passage(work_id) lookup index, expands the directed SOURCE_LINK edge,
filters target Work through coalesce(), requires the exact Evidence
node, and checks both independent research review states. The query is
registered server-side; users cannot submit Cypher, arbitrary filters,
a different direction or an unbounded limit.

## Explicit limitations

- These are separate read transactions, **not** a snapshot-consistent
  graph export. A concurrent write can create, delete or change edges
  between pages; a cursor does not prove completeness or authenticity.
- Reaching next_cursor=null does not certify the full corpus, rights
  to excerpts, source reliability or scholarly human review.
- Review labels describe stored metadata only. Joint approved status
  is not independent manuscript inspection, author attribution, citation
  authenticity, chronological proof or demonstrated literary influence.
- This endpoint returns no full-text contents and grants no rights to
  copy or publish licensed source works.
- No signed full-corpus receipt or DvirOS production identity policy is
  introduced. Private research/public release status stays HOLD.

## Verification

The isolated TestClient suite validates cursor chaining, one-direction
scope, safe status counts, malformed or duplicate query keys, missing
Works, out-of-order rows, repeated Evidence and untrusted lookahead.
The existing authenticated live Neo4j smoke verifies the new endpoint,
a one-row synthetic Evidence link, exhausted-edge cursor behavior,
reverse direction and invalid arguments.

The existing v0.9.6 fixed-fixture cost guard also detected a planning
regression in the earlier incident-frequency query during this cycle:
181 dbHits on 32 synthetic links and 661 on 128, compared with the
prior 15-hit observation. Without changing any release or budget gate,
we re-anchored the frequency query on Passage(id), using the existing
canonical-ID uniqueness index, before undirected SOURCE_LINK expansion.
This targeted repair is independently guarded by the same 32/128
synthetic PROFILE checks and a new fixed-query-shape test. Its new cost
must be verified from exact-head CI before claiming an improvement.

Next acceptance steps: corpus-level revision/snapshot handling,
reviewer workflow, 100+ authentic manually vetted links, 20 real
scholarly cases, source rights, production query-cost budgets, DvirOS
SSO/RBAC and final research signoff.
