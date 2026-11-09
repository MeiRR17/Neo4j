# Changelog

## [Unreleased 0.6.0] — 2026-11-09 (DvirOS service contract; live approval pending)

- Added explicit versioned BFF route and security contract, synthetic offline fixture and route OpenAPI compatibility tests.
- Added DvirOS integration states and service-to-service authorization boundary documentation; research API schema remains 0.5.0.
- Live integration, DvirOS identity/session issuer, TLS and production deployment remain blocked; no source text or rights claims.

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
