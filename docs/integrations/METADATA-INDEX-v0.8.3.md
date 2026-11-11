# v0.8.3 — normalized metadata prefix indexes, controlled backfill and coverage gate

**State:** source code and tests on a draft GitHub PR. NOT deployed or a
production release. This branch is stacked on v0.8.2 PR #18; it is not
built from current \`main\`.

## Added in Neo4j

The additive migration \`004_search_key_v1_indexes.cypher\` declares four
secondary range indexes (\`Work\`, \`Person\`, \`Passage\`, \`Concept\`) on
\`search_key_v1\`, with schema migration manifest version \`0.2.1\`.

A node's index contains only **normalized existing metadata**:

- \`search_key_v1\`: disposable Unicode NFKD + casefold + combining mark
  removal + normalized punctuation/space for the *title* field.
- \`search_source_v1\`: exact original metadata title used to calculate
  the key; allows an API coverage check to detect changed source titles.
- Identity fields (\`id\`), raw title, source refs, edition records and
  evidence are never rewritten.
- No passages' text, quotations, authorship inference, translations or
  third-party content bodies are imported.

The existing v0.8.2 substring/alias scan remains unchanged. The new
indexed route is intentionally **prefix-only**, not arbitrary substring,
full-text, alias, semantic similarity or ranked relevance search.

## Operator workflow — local only

\`\`\`sh
# With locally applied checked Neo4j migrations and loopback DB:
python scripts/migrate.py dry-run
python scripts/migrate.py apply
python scripts/migrate.py check

# Inspect candidate titles and identify any conflicts before writing.
python scripts/search_index_backfill.py dry-run --kind works

# Explicit opt-in. Run only on isolated CI or a deliberately authorized
# local test deployment, NEVER against unreviewed production data blindly:
ALLOW_LOCAL_INDEX_BACKFILL=1 python scripts/search_index_backfill.py \
    apply --kind works --ack-metadata-only

python scripts/search_index_backfill.py check --kind works
\`\`\`

The command refuses writes without explicit
\`--ack-metadata-only\` and either \`CI=true\` or
\`ALLOW_LOCAL_INDEX_BACKFILL=1\`. Its database URI is constrained by
the existing loopback \`LocalQueryClient\`. An operator should take a DB
backup and ensure ingestion is paused, because this is a migration/backfill.

The script first scans and validates every candidate (at most 50,000
records per selected entity kind; cursor windows of 25) **before** issuing
a write. It rejects malformed ID/title, empty normalized key, existing
index/source conflicts and missing schema migration. Updates use
hardcoded, parameterized Cypher with exact matching source text and are
idempotent on unchanged data. A conflict can leave an earlier batch
already applied; until all records pass verification, indexed lookup
continues failing closed.

The \`check\` command returns a nonzero exit code for missing/stale/empty
indexes, rather than treating an empty graph as proof of completeness.
New ingestion or title edits require another controlled backfill; the
\`search_source_v1\` equality check detects stale indexed titles.

## New authenticated read endpoint

\`\`\`http
GET /v1/search/metadata/indexed?kind=works&query=guide&limit=10
Authorization: Bearer <private Research API secret>
X-DvirOS-Client: dvir-os/research-bff/v1
X-DvirOS-Timestamp: <timestamp>
X-DvirOS-Nonce: <nonce>
X-DvirOS-Signature: <HMAC>
\`\`\`

Authentication is the same private service bearer + signed HMAC/replay
guard used in the existing Neo4j service deployment. The endpoint never
takes arbitrary Cypher, label names, tenant IDs or source URIs.
Keys are allowlisted (kind, query, cursor, limit, language), duplicate
keys and unsupported facets are rejected. Nonempty normalized title
prefix is mandatory. \`limit\` is 1..20. \`language\` applies only to
works with edition metadata and does **not** confer text rights.

Every request checks the selected kind's coverage; when any record is
missing or stale or there are no indexable records, the endpoint returns
a sanitized 503 with **no partial index result**. It also rejects invalid
canonical ordering, unexpected columns, aliases or unlicensed content.

The versioned response is **0.8.3** and explicitly includes
\`index_version: search_key_v1\`, \`index_coverage: {total,covered,complete}\`,
\`match_order: indexed_title_prefix_canonical_id\`,
\`alias_matching_available: false\`, \`full_text_indexed: false\`,
\`source_trail_verified: false\`, \`text_available: false\`.
As before, every record is marked \`unreviewed\`, source verification
\`NOT_VERIFIED\` and rights \`NOT_ASSESSED\`.

An index on \`search_key_v1\` makes Neo4j *eligible* to use a range-index
prefix lookup. **Actual query-plan index use and latency/throughput gains
still require PROFILE/EXPLAIN verification on realistic data.** Coverage
counts on every request are deliberately conservative and not yet an
optimized high-throughput mechanism.

## CI verification

\`\`\`sh
python -m unittest discover -s tests -v
\`\`\`

The existing CI builds a disposable, loopback-only Neo4j instance,
applies migration 004, plans/applies/verifies metadata indexing on
synthetic Work nodes, and performs a real signed HTTP smoke for the
new endpoint without exposing full text. It also runs existing ontology,
API, signed-request, rights and ingestion tests. No real Sefaria text or
live research database is touched by CI.

## Integration boundaries

The DvirOS BFF stacked in PR #148 is still pinned to the previous
bounded-scanner schema \`0.8.2\`. It is **not automatically switched** to
the indexed prefix endpoint. Future DvirOS integration requires a
separate signed contract, exact DTO schema change and an explicit
runtime feature flag. It must not claim that the new title-prefix
results include aliases, substrings, translations or full corpus text.

Outstanding release gates: real scholarly rights reviews, licensed
corpus acquisition, 50 human-annotated search questions, 100+ source
adjudications, authenticated DvirOS users/SSO/RBAC, browser controls,
index query-plan performance validation, reproducible Backfill on the
target *authorized* host, and production operational review.

**No main merge or live service activation** should occur merely
because this infrastructure code passes synthetic tests.

## v0.8.4 additive safety hardening (draft)

The v0.8.3 response schema remains unchanged. The read path now uses the
fixed read-only `SHOW INDEXES` query before coverage and lookup. An exact
migration-004 index with matching name/label/property, `RANGE` type,
`NODE` entity type and `ONLINE` state must exist; absent, populating,
failed or swapped indexes return the same sanitized 503. This closes the
v0.8.3 gap where completely backfilled properties could look sufficient
even after the physical index had been removed.

The check does **not** prove the Neo4j planner chose an index seek, that
normalized keys match their source titles cryptographically, or that p95
latency meets production goals. Those still require representative local
`EXPLAIN`/`PROFILE` benchmarks, human research evaluation, and deployment
review. Existing CI exercises the signed route against a disposable Neo4j
instance with migration 004; it never runs a live production backfill.

## v0.8.5 — signed index capability discovery (DRAFT)

Read-only, service-authenticated (bearer plus configured DvirOS HMAC) endpoint:
`GET /v1/search/metadata/indexed/capability?kind=works`.
The only accepted query key is one `kind`: works, persons, passages or
concepts. Duplicate or unknown keys and facets are refused with HTTP 422.

Example **synthetic** response (not production evidence):

```json
{
  "schema_version": "0.8.5",
  "kind": "works",
  "index_version": "search_key_v1",
  "index_status": "ready",
  "indexed_prefix_ready": true,
  "index_coverage": {"total": 3, "covered": 3, "complete": true},
  "bounded_scan_supported": true,
  "scan_candidate_window_limit": 50,
  "scan_requires_cursor_completion": true,
  "alias_matching_on_index": false,
  "full_text_indexed": false,
  "source_trail_verified": false,
  "text_available": false,
  "corpus_status": "unreviewed_metadata_only"
}
```

Status is one of ready, missing, not_online, empty or incomplete. No raw
index names, titles, excerpts, source bodies, arbitrary Cypher or human
approval are returned. A missing index yields null coverage; malformed index
definitions/counts and storage errors fail closed with sanitized HTTP 503.
This endpoint never initiates a backfill or graph query for search hits.

`bounded_scan_supported` means the separate v0.8.2 scanner exists, not
that the graph is healthy or the result set is complete. A client that
explicitly uses it must paginate until `search_complete=true`. No automatic
fallback or feature switch is implemented here. A capability probe is a
point-in-time observation: every indexed search independently revalidates
index state and complete current metadata coverage.

DvirOS BFF #148 remains on the v0.8.2 scan contract. Session/RBAC, schema
wiring, real corpus evaluation and operational activation are not approved.

## v0.8.6 — reproducible read-only query-plan evidence (draft)

Neo4j Query API returns `queryPlan` after EXPLAIN, and `profiledQueryPlan`
plus results after PROFILE. The new script uses only fixed `indexed_{kind}`
registry entries, a localhost-only Query API connection, read access mode,
five-second server execution bound, eight-second socket timeout and bounded
256 KB response. It never prints query rows or original source titles.

```sh
# Safe EXPLAIN: plan only; no query execution or graph modifications.
python scripts/search_index_plan.py --kind works --prefix synthetic

# PROFILE executes the fixed read query, permitted ONLY for a disposable CI fixture:
CI=true python scripts/search_index_plan.py --kind works --prefix synthetic \
  --profile --ack-disposable-fixture

# Optional strict gate for a representative authorized test dataset only:
python scripts/search_index_plan.py --kind works --prefix synthetic \
  --require-range-seek
```

The output schema `0.8.6` contains only allowlisted operator type names,
`search_key_range_seek_planned`, `node_or_label_scan_planned` and, in fixture
PROFILE mode only, row count, operator DB hits and optional Query API timing.
It contains no Cypher plan details, text, credentials, titles, IDs, links or
private source metadata. The CI stage after synthetic metadata-only backfill
executes both EXPLAIN and bounded PROFILE as an *engineering smoke test*.

The small fixture does not establish that the optimizer will choose the range
index on representative data; `--require-range-seek` is an optional reviewer
gate and deliberately not enforced in tiny CI. PROFILE executes a read and can
be more expensive, therefore the script rejects PROFILE unless explicitly
acknowledged within a disposable CI process. This is **not** production
latency p95, throughput or a certified security/performance acceptance.
