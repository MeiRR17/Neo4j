# Changelog

## [0.8.16] — 2026-11-11 (DRAFT — read-only bucket governance and repeat observations)

- Added a private operator-acknowledged AWS account/bucket governance audit,
  bound to the exact v0.8.15 S3 object version and existing v0.8.11–14
  source, HMAC and pinned Ed25519 attestations.
- Uses a single named-profile AWS session to read STS GetCallerIdentity,
  S3 GetBucketVersioning, GetPublicAccessBlock, GetBucketPolicyStatus,
  GetObjectLockConfiguration, and independently rechecks HEAD/retention
  of the exact previously signed object VersionId. All bucket requests
  require ExpectedBucketOwner and only fixed HTTPS regional endpoints.
- Rejects STS account mismatch, suspended versioning, one missing
  Block Public Access switch, a public/unknown bucket policy, missing
  bucket Object Lock, malformed responses and unsupported IAM identity.
- Emits an exclusive mode-0600 HMAC observation whose fixed safety flags
  distinguish observed bucket controls from complete IAM/SCP/AccessPoint
  auditing or independently certified permanent immutability.
- Added offline comparison of two separately authenticated observations
  at least 24h apart, verifying repeated version/retention checks with
  different read request IDs. **No continuous retention guarantee**:
  observation timestamps and HMAC are not a trusted external clock.
- Unit tests mock S3/STS only, and the real isolated Neo4j integration
  uses mocked S3 governance/STS. No live AWS credentials or endpoints
  accessed in CI. Research release remains HOLD.


## [0.8.15] — 2026-11-11 (DRAFT — read-only live S3 object-version audit)

- Added opt-in AWS S3 SDK verifier using an explicitly selected named
  credential profile, AWS region and 12-digit ExpectedBucketOwner.
- Calls only HEAD on an exact object **VersionId** with ChecksumMode
  ENABLED and get_object_retention on the same version; no downloads,
  source-body reads, object writes or arbitrary custom endpoints.
- Rejects stale/changed object versions, delete markers, absent SHA256,
  multipart COMPOSITE checksums, mismatched content size/sha256, expired
  retention, unsafe governance mode, contradictory HEAD versus retention
  records and HTTP error/unauthenticated API responses.
- Requires valid upstream 0.8.11 HMAC capture, 0.8.12 source-byte receipt,
  0.8.13 membership witness and 0.8.14 pinned Ed25519 attestation BEFORE
  contacting AWS. Validates claimed S3 report against observed HEAD and
  COMPLIANCE retention metadata, and writes an exclusive mode-0600,
  locally HMAC-protected result with offline verification mode.
- Synthetic CI uses injected fake S3 API with NO AWS credentials or calls,
  plus source-chain integration against isolated real Neo4j. No actual
  S3 object or retention was verified in CI.
- Provider/organizational identity, external archival immutability
  end-to-end, source rights and scholarly release remain UNVERIFIED/HOLD.


## [0.8.14] — 2026-11-11 (DRAFT — pinned external archive-claim signature)

- Added an offline **Ed25519** signature verifier for a separately provided
  archive operator statement, bound to an operator-controlled trust policy
  and archive namespace. There is NO embedded production trust root or
  automatic signer enrollment.
- Strictly binds statement, source record, v0.8.12 retained-byte receipt,
  v0.8.13 complete source-membership witness, v0.8.11 capture HMAC and an
  operator-supplied, versioned S3 Object Lock report claim by SHA256.
- Validates exact report mode and retention claim, content SHA256 and byte
  length against locally rechecked source bytes. Rejects changed signature,
  signer/key/namespace mismatch, replay to another source chain, unsafe trust
  policy, malformed timestamp, malformed archive identity or rights promotion.
- New private verification report remains explicit:
  pinned-key signature valid, but signer-organization identity, actual S3
  object existence/object lock, external archive immutability, provider
  authenticity and legal rights are NOT independently verified. HOLD.
- Synthetic ephemeral keys in CI only, negative tests and isolated real
  Neo4j signed source/capture/receipt/membership/signature smoke. No private
  keys, credentials or actual source reports committed.


## [0.8.13] — 2026-11-11 (DRAFT — bounded SourceRecord membership witness)

- Added a read-only, signed local SourceRecord set enumerator that replays
  every bounded source metadata page through the existing bearer/HMAC API.
- Recomputes the **exact** v0.8.11 ordered, length-framed source projection
  SHA256 and missing-checksum count, and checks them against a validated
  HMAC capture manifest. A v0.8.12 local receipt must refer to an exact
  metadata row in that captured projection; otherwise fail closed.
- Generates a private 0600 witness containing the bounded metadata-only
  source rows, receipt and capture hashes, and a separate domain-specific
  HMAC; the offline verifier rehashes all rows and the actual retained
  source file without accessing the network or printing source content.
- Rejects missing or altered source rows, unsafe extra fields, partial
  cursor scans, wrong binding, changed file bytes, expired proof context,
  and forged independent provider/rights claims.
- Synthetic negative tests and signed real isolated Neo4j membership smoke.
- **No external provider signature or immutable archive is verified.**
  Observed API projection membership does not imply a database snapshot,
  author/licensing provenance, or production approval. Release HOLD.


## [0.8.12] — 2026-11-11 (DRAFT — retained local source receipts)

- Offline issue/verify CLI computes source snapshots from actual retained
  local file content and compares them with an exported SourceRecord digest,
  version identifier, URI, canonical ID and metadata-only rights tag.
- Supports two explicit, noninterchangeable modes: Sefaria links CSV raw-byte
  SHA256 and Sefaria version-metadata JSON canonical SHA256. Also records
  the raw JSON file SHA256 to detect changed representation.
- Domain-separated HMAC receipt; exclusive 0600 output; source file is
  bounded, never uploaded or printed. Optional v0.8.11 capture-event
  manifest attachment is authenticated but does not prove individual
  source membership in that graph observation.
- Synthetic negative tests and live signed SourceRecord comparison against
  locally retained synthetic CSV in isolated Neo4j CI.
- NOT an independent provider attestation, legal rights certification,
  external immutable archive, graph snapshot, or scholarly signoff. HOLD.


## [0.8.11] — 2026-11-11 (DRAFT — source/edition/evidence provenance observation)

- Implemented a new authenticated, bounded, metadata-only provenance API
  for SourceRecord, Edition and Evidence with three fixed read-only Cypher
  queries, strict canonical-ID order and explicit cursor completion.
- Added signed before/after observations of these metadata projections and
  their provider-supplied checksums/version identifiers; records only digests,
  missing-data counts and source uncertainty in a v0.8.11 HMAC manifest.
- Unapproved text/unknown fields, rights elevation, broken pagination,
  forged manifests and mixed observation scopes are rejected.
- Extended synthetic unit and live CI Neo4j bridge/capture checks. Existing
  v0.8.9/v0.8.10 capture and verification remains supported.
- Does not establish actual source checksum trust, edition licensing,
  relationship stability, whole-database isolation or production approval.


## [0.8.10] — 2026-11-11 (DRAFT — bounded search projection and index revision binding)

- Added a signed private API observation of all bounded visible metadata
  titles/source anchors and physical index capability for catalog entity kinds.
- Optional --pin-observed-projection scans this observed projection both before
  and after research capture, rejecting drift and incomplete/oversized scans.
- Emits backward-compatible v0.8.10 HMAC-bound revision observation in
  the capture manifest; offline verify checks exact catalog kinds, index
  coverage, schema/rights flags and observation hash.
- CI tests index drift rejection and exercises revision-pinned scan/indexed
  metadata capture end-to-end over synthetic Neo4j.
- Important limits: not a cryptographic whole-corpus revision. Aliases,
  edition links, hidden text and graph edges are NOT observed; no snapshot
  isolation or independent DB/server attestation is claimed; release HOLD.


## [0.8.9] — 2026-11-11 (DRAFT — signed localhost search capture)

- Added an opt-in localhost-only research metadata capture tool using the
  existing DvirOS bearer authentication and fresh HMAC signature per GET.
- Uses fixed API routes, schema constraints, strict canonical cursor checks
  and per-page/request/response budgets; never falls back to weaker search.
- Writes v0.8.7-compatible frozen responses and a locally HMAC-authenticated
  trace of request targets, cursors and page responses to private 0600 files.
- Added a signed FastAPI-to-real-Neo4j integration smoke for both scan and
  indexed-prefix paths, with only disposable synthetic data and no files.
- Added a standalone offline verifier, negative tests for unsafe source
  fields, tampering, incorrect pagination, remote hosts and auth denials.
- Documentation distinguishes local-client integrity from server attestation;
  production use, source rights, reviewer identities and scholarly quality
  remain unapproved, release HOLD.


## [0.8.8] — 2026-11-11 (DRAFT — private dual-review preparation)

- Built offline, non-destructive commands to prepare bounded review packets
  from complete metadata-only search captures, generate truly empty per-reviewer
  annotation templates, and freeze two independently completed assessments.
- Explicit third-reviewer adjudication required whenever relevance judgments
  conflict; no default majority, auto-labelling, model-generated review or
  implied scholarly approval.
- Packet includes only query, title, source anchor, canonical ID and matching
  semantics; unsafe rights/source text and incomplete paging fail closed.
- Forms bind to exact packet SHA256; audit records input fingerprints,
  disagreement counts, and permanent unverified/HOLD release status.
- Local files are exclusive-create mode 0600 and never overwritten. Added
  synthetic-only CLI/negative tests and CI smoke; no human corpus invented.
- 50 verified expert evaluations, content rights, BFF identity/RBAC,
  live capture authentication and production release remain outstanding.


## [0.8.7] — 2026-11-11 (DRAFT — frozen research search-quality evaluation)

- Added an offline, deterministic evaluation CLI for versioned frozen judgment
  files and complete v0.8.2/v0.8.3 metadata-only search page captures.
- Computes Precision@5 over **explicit** 0/1 relevance labels, with five
  positions in the denominator and transparent eligible-query counts.
- Blocks inflated quality claims when pagination is incomplete, top-five hits
  are unjudged, canonical IDs duplicate, required source anchors are missing,
  or review/source-safety contracts are violated.
- Produces reproducible input SHA256 hashes and safe diagnostics without
  printing queries, titles, record IDs, excerpts or license-sensitive text.
- Adds small Hebrew/English **synthetic-only** test fixtures and CI smoke;
  cannot manufacture 50 genuine reviewed research questions.
- Independent review not verified and release always HOLD; DvirOS RBAC,
  scholarly sources/rights and representative 50-question scoring remain open.


## [0.8.6] — 2026-11-11 (DRAFT — bounded index query-plan evidence)

- Added a local-loopback-only `EXPLAIN`/opt-in `PROFILE` CLI for the exact
  shipped read-only indexed metadata queries, never arbitrary user Cypher.
- EXPLAIN summarizes a bounded Neo4j Query API `queryPlan` and detects
  actual planned `search_key_v1` range seek vs label scan, without
  presenting planned index availability as demonstrated performance.
- PROFILE is restricted to `CI=true` plus `--ack-disposable-fixture`,
  runs only a fixed 6-row read operation under a 5-second query timeout,
  and emits only aggregate DB hits / safe timing counters, never titles.
- Added plan-response negative/limits tests and a disposable Neo4j CI
  EXPLAIN/PROFILE step. Small synthetic fixture plans are **informational**;
  representative workload, p95, index-use threshold and source licensing
  remain outstanding release gates.
- No API, schema migration or production graph write is performed.


## [0.8.5] — 2026-11-11 (DRAFT — typed signed indexed-search capability)

- Introduced private typed `GET /v1/search/metadata/indexed/capability`,
  with exactly one allowlisted kind and the existing bearer/HMAC protection.
- Returns readiness states ready/missing/not_online/empty/incomplete, validated
  coverage counts, bounded-scan caveats and explicit metadata-only restrictions.
- Preserves all per-request index safety checks; capability never authorizes
  writes, guarantees search success, silently selects fallback or releases text.
- Added service and HTTP denial/state tests, signed real Neo4j CI smoke, docs
  and an implementation-derived SVG architecture diagram.
- Not deployed; rights, human-quality, BFF sessions/RBAC and representative
  search relevance/EXPLAIN performance remain release blockers.


## [0.8.4] — 2026-11-11 (DRAFT — physical index readiness guard)

- Corrected v0.8.3 indexed metadata search readiness: complete backfilled
  properties alone no longer imply the underlying Neo4j index exists.
- Added a fixed, parameterized read-only SHOW INDEXES registry operation;
  each indexed request now requires the exact migration 004 index name,
  ONLINE state, RANGE type, NODE entity type, correct label and property.
- Missing, populating, failed, swapped, or malformed physical indexes fail
  closed with the existing sanitized HTTP 503, before any coverage or
  indexed-result query. No change to the v0.8.3 response schema or writes.
- Added focused negative tests; existing real Neo4j signed indexed-read CI
  exercises the physical-index check in an isolated fixture only.
- Still no production activation, human rights clearance, service RBAC,
  realistic PROFILE/EXPLAIN evidence or main merge.


## [0.8.3] — 2026-11-09 (DRAFT — indexed, rights-conservative metadata lookup)

- Added migration 004, four additive range indexes over normalized title keys, and schema-manifest 0.2.1 (IDs and provenance unchanged).
- Implemented explicit local-only metadata backfill with full preflight, 25-row batches, 50k-per-kind safety cap, conflict checks and freshness tracking.
- Introduced signed, authenticated `GET /v1/search/metadata/indexed` with a strict title-prefix-only contract; absent, stale or partial indexes fail closed.
- Verified an isolated CI synthetic Work index migration/backfill/check and signed read; no real scholarly corpus, production backfill or live-site activation.
- Preserved the v0.8.2 bounded substring/alias scanner as a separate optional path. DvirOS private adapter for v0.8.3 remains pending.
- Outstanding: SSO/RBAC, licensed editions, human quality review, query-plan latency benchmarking, safe operational rollout. **No main merge.**


## [0.7.1] — 2026-11-09 (bounded graph evidence trail)

- Exposed exact, typed relationship-to-Evidence provenance on each bounded graph neighborhood path: source reference, source URI, link category, rights tag, source-record ID, and separate evidence review status.
- Bounded candidate path selection before Evidence enrichment; retained a fixed parameterized read-only Cypher registry, no text bodies and no inferred citation direction.
- Extended isolated Neo4j HTTP smoke to verify real linked source metadata and review-state fields.
- Paired with DvirOS Graph Explorer evidence-inspector hardening in a separate dependent feature branch.
- No change to signed service identity, licensing or production approval state.

## [0.6.0] — 2026-11-09 (signed DvirOS backend integration)

### Added
- Versioned `/v1/integration/contract` endpoint with service identity, semantic version, evidence-first flags and human-review-pending status.
- DvirOS HMAC-SHA256 service identity with exact GET target+query, timestamp ±60s, 128-bit random nonce, constant-time digest comparison and bounded in-process replay cache, layered on existing bearer authentication.
- Separate local signing-key bootstrap, explicit signed-mode requirement in local API runner, cross-language deterministic HMAC vector and denial tests for modified path/query, replay, stale time and missing authorization.
- Real Neo4j CI smoke for the signed integration contract and authenticated read access; read-only API from v0.5 remains backward-compatible within isolated test harnesses.
- Cross-repo integration contract and runbook paired with DvirOS BFF PR.

### Security and deployment caveats
- No public-facing DvirOS user sessions or graph UI yet. The DvirOS BFF is disabled by default and owner-token guarded.
- Replay nonce cache and request budgets are per-process; production distributed deployment still requires shared state, PKI/TLS front door, rotation and signed operator review.
- Human edition licensing and 100+ source adjudications remain pending; research corpus is not GA-ready.

## [0.5.0] — 2026-11-09 (private typed Research API implementation)

### Added
- Internal FastAPI read-only Research API with 14 bounded operations covering health, work/person/passage/concept/source reads, provenance links, graph neighborhoods and data status.
- Generated OpenAPI schema, typed public DTOs, distinct process liveness and real Neo4j/schema-checksum readiness.
- Dedicated locally generated server-to-server bearer secret; fail-closed authentication on all /v1 routes, request IDs, sanitized errors and no-store headers.
- Fixed read-only parameterized Cypher registry, 5-second DB query budget, 2 MB response limit, controlled depth 1–2, per-page 1–50 results and canonical keyset pagination.
- Explicit no-excerpt policy for unlicensed texts, separate research corpus human-review status (never fabricated as GA-ready).
- Offline FastAPI/security tests and isolated CI integration exercising actual Neo4j with synthetic work/passage/evidence nodes, plus operational runbook and SVG architecture.

### Deferred
- No real corpus rights clearance or 100+ real human source adjudications yet.
- No DvirOS BFF/SSO integration, production TLS, Enterprise read-only database principal or public deployment (v0.6/v0.14). Neo4j Community Read routing is not database authorization.

## [0.4.0] — 2026-11-09 (engineering implementation; human scholarly gates BLOCKED)

### Added
- Candidate inventory of 18 Jewish philosophy/ethics/thought works; exact indices are verified at runtime, never assumed available or licensed.
- Opt-in metadata-only Sefaria versions discovery; bounded HTTPS response, source snapshot checksums, edition/language/version IDs, quarantine of invalid mappings.
- Per-edition rights review contract bound to inventory checksum, explicit human reviewer, dated rationale, license, rights evidence and attribution.
- Source-link review queue with deterministic 100–500 candidate sampling, separate human adjudication, immutable queue hash and no inferred citation direction.
- Research quality audit: work/edition coverage, 100+ inspected links, missing anchors/evidence, collisions, unresolved titles and incomplete rights.
- Local-only Neo4j upserts for reviewed **version metadata only** with evidence, rights status and deterministic provenance; no full-text downloads or AI review.
- CI synthetic-only metadata upsert smoke, offline negative tests, operations runbook, architecture diagram.

### Outstanding human acceptance gates
- No real Sefaria edition has yet been approved by this change.
- 100+ real source link adjudications, actual edition license/attribution review for 12–20 works, unresolved candidate names and independent scholarly signoff remain necessary.
- v0.4 is *code-complete for the review workflow*, not a populated, licensed research corpus or production GA.

## [0.3.0] — 2026-11-09 (implementation candidate)

### Added
- Opt-in Sefaria-Export GCS link shard download with bounded bytes, ETag/Content-Range validation, safe partial resume and receipt checksums.
- Curated REST links API fallback using `with_text=0`, strict allowlisted endpoints, request size/time limits and quarantined unresolved mappings.
- Streaming CSV adapter supporting upstream `Conection Type` header, canonical full passages and source snapshot hashes; no inferred citation direction.
- Deterministic JSONL planning, immutable checksum manifest, quality gate and zero-quarantine requirement before metadata writes.
- Explicit local-only parameterized Neo4j upserts with reviewed schema, unreviewed SourceRecord/Evidence/Work/Edition/Passage graph records, 50,000 edge pilot limit and rerun-safe identity.
- Synthetic data tests, CI integration, source contracts, operations docs and pipeline SVG.

### Deferred
- License-cleared editions/actual text passages, scholarly review and seed corpus remain v0.4; no independent DvirOS UI, GraphRAG or public deployment.

## [0.2.0] — 2026-11-09 (implementation candidate)

### Added
- Deterministic provider-backed SHA-256 IDs for Work, Edition and full Passage references.
- Source-grounded ontology: Work, Edition, Passage, Person, Concept,
  SourceRecord, Evidence, ImportRun, NameAlias and SchemaMigration.
- Evidence type/review state validation and parameterized, allowlisted
  relationship writer to prevent ungrounded edges and provider-driven Cypher.
- Three versioned idempotent Neo4j Community schema migrations, a manifest,
  checksummed migration ledger and local-only CLI with drift detection.
- Synthetic-only graph integration smoke, repeat migration verification,
  unit tests and documented safe rollback requirements.

### Out of scope
- Real Sefaria ingestion, scholarly source review, graph browsing UI, DvirOS
  integration and production deployment. No legacy Text data was migrated.

## [0.1.0] — 2026-11-09

### Added
- Pinned Neo4j Community Docker image, localhost-only development bindings,
  named data/log/import volumes and Docker secret-based bootstrap.
- Dependency-free cross-platform Python secret initializer and authenticated
  local Query API smoke with explicit anonymous-access rejection.
- Lightweight offline policy tests and GitHub Actions validation, local
  operations instructions, safe .env example and ignored runtime state.

### Changed
- Replaced legacy Windows-only/unsafe container guidance with DvirOS
  research-engine development documentation.
- Retained original Sefaria acquisition/Cypher files as **legacy research
  prototypes only** until provenance and ontology refactor (v0.2–v0.4).
