# v0.9.5 — Isolated graph-cost benchmarking (DRAFT)

## Scope and fixed fixture sizes

This feature builds **synthetic metadata only**. It does not ingest Sefaria
text, external research sources, credentials, scholarly interpretations or
licensed editions. It is a cost-observation tool, not release approval.

The checked-in generator emits two exact fixture sizes: **32** and **128**
directed SOURCE_LINK relationships. For each size it uses:
- 2 unique Work IDs and 2 unique Person IDs with one AUTHORED link each;
- 2 unique Passage nodes per SOURCE_LINK (64 / 256 Passage nodes);
- 1 distinct Evidence node per SOURCE_LINK (32 / 128 Evidence nodes);
- alternating directed links between left and right Works;
- one immutable-in-scope fixture SHA-256 of deterministically serialized
  node/edge metadata, generated from a stable seed namespace;
- exact node IDs used for first checking absence and then cleanup.

The two sizes are deliberately small. They show query-plan and cost
differences under a known fixture, not representative production scale.
They do not satisfy the roadmap requirement for 100+ human-reviewed links.

## Running in disposable isolated CI only

After the existing authenticated Research API smoke checks, CI invokes:

\`python scripts/analytics_cost_benchmark.py --ack-disposable-fixture\`

The runner rejects all requests unless CI=true and explicit acknowledgment
are BOTH present, including when called directly as a Python library.
Only the existing local 127.0.0.1:7474 Query API and validated secret file
are permitted. Never run on a persistent or shared database.

The runner first checks that **none of the expected synthetic node IDs
already exist**. If they do, it aborts before writing. After starting,
the runner attempts cleanup for exactly those IDs even when seeding or
profiling fails. A temporary disconnected DB could prevent cleanup;
the disposable CI container is never substituted for a production DB.

## Plan and timing methodology

Four fixed registered analytical operations are PROFILEd **three times**
for each dataset size, always with accessMode=Read and a five-second DB
execution limit:
1. Work descriptor (one canonical Work, bounded author IDs).
2. Left-to-right cross-Work SOURCE_LINK sample (limit 11).
3. Right-to-left cross-Work SOURCE_LINK sample (limit 11).
4. Incident source-link frequency on the first synthetic Passage
   (limit 51, one actual incident link in this fixture).

The authorized profiler validates Query API read-only metadata, no errors,
bounded result rows and plan tree depth. It discards ALL returned rows and
Cypher plan Details. It reports only fixed query-template SHA-256, safe
operator names, database hits, scan indication, operator counts,
number of rows and observed wall-clock milliseconds.

The profile budget is intentionally conservative for CI: 250,000 total
database hits per operation, 100 plan nodes, depth 18, 256 KB maximum
response, 8 second network timeout, 8 second wall budget, and fixed
result row sizes. Violations fail the CI gate rather than silently being
treated as fast enough. The limit is a safety ceiling, NOT an endorsed
production SLO or p95 latency target.

The JSON provides p50 (median of three) and p95 (nearest-rank, which is the
maximum of three samples), plus min/median/max dbHits. Such a small sample
cannot establish a precise latency percentile or typical production
performance. Sorting by canonical ID and small output windows do not
guarantee efficient underlying graph scans.

## Artifact and trust boundaries

The workflow emits \`analytics-cost-v095-synthetic\` as a seven-day GitHub
Actions artifact, containing only sanitized generated graph counts,
fixture/template SHA-256 values, operator types, hits and durations.
It intentionally contains no raw graph rows, source excerpts, credentials,
file-system secrets or Cypher plan Details.

The reported statuses are always:
- real_corpus_benchmarked=false;
- representative_performance_proven=false;
- graph_snapshot_verified=false;
- producer_digest_digitally_signed=false;
- research_release_status=HOLD.

The benchmark may reveal expensive scans or unfavorable size scaling.
Its purpose is to generate inspectable evidence to inform later indexing
and cost-budget changes, not to certify an implementation as fast or safe
for authentic research users. Full research release still requires legal
rights review, independent corpus validation, human scholarly review,
identity/RBAC and representative query benchmarks.
