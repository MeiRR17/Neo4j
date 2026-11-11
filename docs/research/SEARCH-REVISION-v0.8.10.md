# v0.8.10 — bounded search-projection revision binding (DRAFT)

This adds an opt-in check to the v0.8.9 signed capture tool. It observes
**only what the existing research metadata-search API exposes** and checks
for drift in that visible metadata and physical index capability across
a complete capture. It does **not** create an immutable database version,
a transactionally consistent snapshot, or a copyright/source license.

## Use on an explicitly authorized local research host

The Research API must already be started, local-only and configured with
\`DVIROS_REQUIRE_SIGNED_CALLS=1\`. Existing local files hold the bearer
token and DvirOS HMAC key; do not add secrets to command arguments or Git.

\`\`\`sh
umask 077
python scripts/search_capture.py capture \
  --questions /private/review_questions.json \
  --search indexed --url http://127.0.0.1:8000 \
  --ack-authorized-metadata-only \
  --pin-observed-projection \
  --output /private/revision_bound_responses.json \
  --manifest /private/revision_bound_manifest.json

python scripts/search_capture.py verify \
  --questions /private/review_questions.json \
  --responses /private/revision_bound_responses.json \
  --manifest /private/revision_bound_manifest.json \
  --require-observed-projection
\`\`\`

The \`scan\` mode is also supported. The operator must choose one search
semantics per catalog. When the flag is omitted, the backward-compatible
v0.8.9 manifest is still emitted but cannot satisfy the strict
\`--require-observed-projection\` verification option.

## What is measured and how

For each distinct entity kind referenced by the v0.8.8 catalog (works,
persons, passages, concepts), the tool issues signed bearer/HMAC GET calls:

- A single private indexed capability probe with the exact kind, including
  the server's validated physical index status and coverage counts.
- A cursor-complete, empty-query metadata scan of the kind; it hashes
  all visible safe returned metadata projections in canonical-ID order,
  without printing or persisting the raw values in the observation.
- These observations run *before* and *after* the catalog search capture.
  The capture is rejected if the observed projection, coverage or physical
  index status differs. For indexed mode, the index must be ready.

The revision observation captures an ordered set of entity kinds, record
counts, a SHA256 of the visible result fields, observed index version/state
and coverage, explicit safety qualifications and a hash of the observation.
It is embedded in the **v0.8.10 capture HMAC manifest**, which also
authenticates the original v0.8.9 request/response/cursor trace and exact
snapshot bytes. An offline \`verify\` checks the observation envelope,
hash, catalog-kind set, index validity, HMAC and original search trace.

Revision checks are **bounded**: at most 25 pages / 500 items per kind for
each pass. An incomplete observation, invalid or changed capability,
unexpected field, timestamp/nonce issue, invalid response, exceeding
the configured limits or a differing pre/post digest causes fail-closed
rejection. Original search capture bounds remain in force.

## Explicit non-guarantees

This fingerprint is **not a cryptographic hash of the entire graph**.
Metadata aliases, edition relationships and language eligibility,
unexposed source text, evidence records, cross-graph edges and other
hidden fields can change without affecting the observed projection.
There is no shared Neo4j read transaction across the many HTTP GETs,
so pre/post equality cannot detect every transient change (ABA),
nor authenticate a third-party server, fix a production corpus edition
or verify rights. A compromised local signing key can forge manifests.
The proof also covers only the current pilot-size cap; it refuses a
larger incomplete corpus instead of labelling it complete.

\`snapshot_isolation_guaranteed=false\`,
\`corpus_immutable_revision_verified=false\`, and
\`alias_edition_source_text_not_covered=true\` are mandatory and
cannot be upgraded by changing a client CLI flag.

## Next research gates

To meet the full v0.8.0 quality acceptance, independently version the
licensed corpus and its source/edition graph with trusted immutable
ingestion receipts and an atomic database snapshot or explicit write
freeze; then collect 50 real questions, verify independent scholarly
reviewer identities, adjudicate relevance, and evaluate Precision@5.
DvirOS BFF SSO/RBAC and production authorization are still outstanding.
No main merge or production enablement is implied.

## v0.8.11: Expanded metadata scope (opt-in)

The next version can additionally bind SourceRecord, Edition and Evidence
version/checksum metadata to the search capture HMAC without exposing source
texts. This checks only the private API's bounded projection, not actual
provider bytes or full graph relationships. See SEARCH-PROVENANCE-v0.8.11.md.
