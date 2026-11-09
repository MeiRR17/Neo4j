# v0.8.2 — bounded bilingual metadata search (Neo4j Research API)

Status: code implemented on feature branch; do not call this a production
search index or a research-corpus release until CI and scholarly review pass.

## Endpoint and compatibility

New private authenticated GET endpoint:

\`\`\`http
GET /v1/search/metadata?kind=works&query=%D7%9E%D7%95%D7%A8%D7%94&limit=10
\`\`\`

Accepted \`kind\`: \`works\`, \`persons\`, \`passages\`, \`concepts\`.
Optional \`query\` (<=100 characters), \`limit\` (1..20),
\`cursor\` (canonical ID matching kind) and \`language\` (he/en/ar/yi,
**only** for works). Unknown or duplicate query keys return 422.
This route inherits the existing Research API private bearer and, in the
normal signed-server deployment mode, the DvirOS HMAC exact-target,
timestamp, nonce and replay protection. No direct browser access is allowed.

The additive endpoint has its own response \`schema_version: 0.8.2\`.
The established \`/v1/integration/contract\` stays at its compatible
\`contract_version: 1.0\`, \`api_version: 0.6.0\` and original
\`schema_version: 0.5.0\`. Existing v0.6 DvirOS BFF is not implicitly
wired to this new endpoint. The owner-only adapter is still distinct.
A new cross-repository contract/route update will be needed for safe client
use. Do not swap URL paths without review.

## Real implementation

The server normalizes **disposable lookup text** with Unicode NFKD,
casefolding, combining-mark removal (Hebrew cantillation/niqqud, Latin
diacritics), and word-boundary handling for punctuation/maqaf/symbols.
Canonical database IDs and exact passage refs are NEVER rewritten.

Four fixed Cypher read operations retrieve only allowlisted **metadata**:
Work title/provider ref and a bounded work-alias list (when available),
Person display name, Passage source reference, Concept preferred label.
No full text, quotations, raw source body, arbitrary Cypher, graph writes
or source URI are returned.

All matches remain \`review_status: unreviewed\`,
\`rights_status: NOT_ASSESSED\`, \`source_verification: NOT_VERIFIED\`,
\`text_available: false\`; links do not prove influence or agreement.
No user query text or source body is written to a persistent store.

### Windowed result semantics

The pre-index version reads at most 51 candidate rows (50 visible scanned
rows plus a continuation sentinel) per request, ordered by immutable
canonical ID. It filters with normalized text in Python and stops after
the requested maximum 20 matches. The response reports:

- \`scanned_candidates\`, \`candidate_window_limit: 50\`
- \`has_more\`, \`next_cursor\`, \`search_complete\`
- \`match_order: canonical_id_scan_not_relevance_ranked\`
- \`full_text_indexed: false\`, \`source_trail_verified: false\`

**A single page can return zero matching results while has_more is true.**
Clients MUST continue with \`next_cursor\` until
\`search_complete: true\` before declaring that a term has no matches
in the accessible metadata. Page results are in stable ID order, NOT
global relevance order. This is an honest bounded scan foundation, **not**
the complete indexed or ranked production search engine.

Pagination advances by the last **scanned** ID rather than the last
matched ID, so a later exact or normalized hit cannot be skipped
between windows. This protects large-corpus searches from silently
dropping valid later results.

## Quick testing

\`\`\`sh
python -m unittest tests.test_metadata_search -v
python -m unittest discover -s tests -v
\`\`\`

CI also exercises the signed real-Neo4j smoke from the existing pipeline.
Unit tests include niqqud/English normalization, canonical-ID preservation,
work aliases, 60-row/50-candidate pagination, rights and unknown-field
rejection, full signed HMAC query binding, replay blocking, and negative
unknown-facet requests.

## Known limitations and release blockers

1. **No persisted normalized search index** exists yet; the cursor window
   is a bounded candidate scan, not performance-optimized search. A
   future version needs versioned ingestion-time indexed search keys and
   explicit backfill/coverage checks before claiming corpus-wide fast
   lookup or precision@5 targets.
2. Work alias matching uses existing \`HAS_ALIAS\` metadata only; no
   automatic translation, historical identification or authority matching.
   Other kinds do not infer aliases.
3. Edition/language filtering checks the existing \`HAS_EDITION\`
   relation but **does not grant text redistribution rights**.
4. No corpus rights approvals, real 50-question human relevance
   evaluation or 100+ source-link adjudications have been completed.
5. DvirOS real user sessions/RBAC, production rate limits, multi-instance
   nonce cache, audited cloud deployment and safe browser presentation
   adapter remain separate blocked work.

**Next:** implement an indexed normalized-search-key ingestion/backfill
with explicit review and migration, then update the DvirOS private BFF
contract to negotiate this optional endpoint without exposing secrets.
