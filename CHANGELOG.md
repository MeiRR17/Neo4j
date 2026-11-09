# Changelog

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
