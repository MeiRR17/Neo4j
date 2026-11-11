# Neo4j Jewish Philosophy Research Engine — DvirOS Production Roadmap

**Date:** 2026-11-09 | **Owner:** MeiRR17 | **Status:** APPROVED PRODUCT DIRECTION / PROPOSED IMPLEMENTATION | **Canonical development repository:** MeiRR17/Neo4j  
**Parent product:** MeiRR17/dvir-os | **Release policy:** Semantic Versioning; milestones are planned, not released.

## 0. Product directive — this is NOT a learning module

This repository is the dedicated **Jewish Philosophy Research & Knowledge Graph service of DvirOS**. Its purpose is a fully operational, source-grounded research system. The separate snapshot in Learning_Modules/tools/neo4j-sefaria is **out of scope** for all future engineering, tracking and deployment. Leave that snapshot unchanged; do not implement features or new infrastructure there. There is one canonical implementation: this repository.

DvirOS remains the product shell, authenticated access point, research workspace, approvals and agent orchestration. This Neo4j repository owns the graph domain, ingestion, scholarly evidence, query API, analysis and research evaluation. UI integration belongs in DvirOS, **not** a second independent end-user application.

## 1. Verified baseline (audit on 2026-11-09)

The existing main branch contains README.md, docker-compose.yml, one Sefaria Python ingestion script, two PowerShell helper scripts and two Cypher files. There is no service API, research UI, versioned migrations, automated tests, deployment pipeline, fine-grained provenance or operational observability.

**P0 correctness/security:**
- Docker uses neo4j:latest, hard-coded neo4j/password, unrestricted apoc.* and host-exposed Bolt/Browser ports; the README repeats these unsafe demo credentials.
- Local filesystem paths are hard-coded to C:\neo4j, so the workflow is Windows-specific.
- The Sefaria bulk links URL points to an obsolete JSON gzip path. Current Sefaria-Export documentation shows text exports in Google Cloud Storage and intertext links in links/linksN.csv; verify live schema and rights before implementing adapters.
- normalize_title() truncates refs with colon to the first whitespace-delimited token; for multiword works this can merge distinct works or destroy passage anchors.
- :CITES relationships are conflated with Sefaria link categories; a structural link is not automatically a direct citation. Link orientation and canonical identifiers need explicit semantics.
- Graph metrics currently interpret co-citation or mutual links as evidence of intellectual influence or an echo chamber; these interpretations require careful caveats and historical controls.
- No claim is made that the existing scripts or container have been executed successfully in this audit.

**DvirOS constraints already documented:** Next.js mobile-first Hebrew RTL PWA; proposed FastAPI/Postgres control plane; evidence-first review; source code in GitHub, original planning in Drive; research corpus remains local/read-only; no unsolicited pay-as-you-go AI; no public database ports; a MacBook host may sleep, so do not promise guaranteed 24/7 uptime.

## 2. Target architecture and boundaries

**Interaction:** DvirOS Next.js Research UI -> authenticated server-side BFF / orchestration -> Neo4j Research API (FastAPI/Python) -> Neo4j DB. DvirOS Postgres (planned) stores users, workspaces, saved research, approvals and agent execution metadata. Do not duplicate account management in Neo4j. The Neo4j service stores graph entities, relationships, source snapshots and evidence references.

**Data plane:** Sefaria and independently permitted sources -> connector adapters -> raw immutable manifests / local permitted cache -> parse & canonicalize -> quality checks/quarantine -> idempotent batch upserts -> graph -> read-only query/analysis. Original local Corpora are read-only and must never be bulk copied, synced or uploaded as an integration side effect.

**Security:** No browser-direct Bolt, no unrestricted Cypher endpoint, no secret in repo, no unchecked LLM Cypher generation. Use private network; HTTPS front door, service-to-service auth, scoped tokens and server-side queries. Cross-boundary API contracts are versioned.

**Scholarly epistemics:** Distinguish [OBSERVED_SOURCE_LINK], [HUMAN_INTERPRETATION], [MODEL_SUGGESTION]. Every visible claim has an exact source anchor, edition/version, provenance, review status and uncertainty. Similarity does not prove causation, influence, agreement or chronological dependence. Not a halachic ruling engine.

**Suggested monorepo directories (to be implemented, not yet present):**
- services/research-api — typed FastAPI endpoints and policies.
- research_graph/ — domain models, controlled vocabulary, Cypher migrations and repository abstraction.
- ingestion/ — provider adapters, schema validation, checkpoints and manifests.
- evaluation/ — golden questions, citation QA, retrieval and performance benchmarks.
- deploy/ — compose profiles, hardened configs, backups, staging/recovery runbooks.
- docs/architecture, docs/adr, docs/operations, docs/research — contracts and rationale.
- tests/ — small deterministic unit/integration fixtures without large corpora.

## 3. Exact version plan

**Note:** time boxes below are *relative estimates* for sequencing, not completion promises; progress is measured by GitHub code + Definition of Done, not by percentages of files written.

### v0.1.0 — Production-safe engineering baseline [P0; 1–2 focused cycles]
**Changes:** secure local Docker Compose with pinned supported Neo4j image/version; localhost-only dev ports; auth from local secret input; remove literal password, open network and APOC unrestricted settings; portable named volumes; .env.example without real secrets; Docker healthcheck; make targets or cross-platform scripts; .gitignore and developer quickstart. Replace README insecure instructions with safe setup and flag legacy paths as deprecated.  
**Acceptance:** fresh local bootstrap and restart preserve data; unauthenticated Bolt access denied; no real secrets in tracked content; compose validation and minimal smoke checks pass. **Blocked by:** none. **Out:** any public deployment.

### v0.2.0 — Canonical ontology, migrations and evidence semantics [P0; 2–3 cycles]
**Changes:** implement migration runner and idempotent versioned Cypher for Work, Passage, Person, Concept, SourceRecord, Evidence, ImportRun, NameAlias; relationships AUTHORED, HAS_PASSAGE, MENTIONS_CONCEPT, SOURCE_LINK, HUMAN_CLAIM and SUGGESTED_RELATION with explicit type/status. Define normalized identifiers, multilingual aliases, valid-from/source timeframe and edition metadata.  
**Acceptance:** rerun migrations safely; no key collisions on multi-word titles or different refs; 100% of inspected relationships identify evidence type; migration manifest and rollback plan. **Depends:** v0.1.0.

### v0.3.0 — Sefaria V2 acquisition + provenance [P0; 2–3 cycles]
**Changes:** replace obsolete export URL with discovery/versioned GCS link-CSV adapter and API fallback; configurable output path; robust HTTP retry, timeout, rate limit, checksum/checkpoint; streaming, parsing, quarantine and dry-run; preserve exact refs, raw link-type, provider/version/time/license. Curated list of philosophy texts only; no blind full export ingestion.  
**Acceptance:** offline fixture reruns produce identical stable IDs and edge counts; partial download resumes; no silent ref truncation; mismatch/quarantine report visible; logs contain no secrets. **Depends:** v0.2.0.

### v0.4.0 — Scholarly seed corpus & quality gates [P0; 2 cycles]
**Changes:** choose 12–20 available Jewish-philosophy works and their permitted editions, such as Emunot VeDeot, Kuzari, Guide of the Perplexed, Hovot HaLevavot, Or Hashem, Sefer HaIkkarim, Derech Hashem, Nefesh HaChaim. Verify *each* edition's reuse terms; create a reproducible source inventory, version manifest, attribution metadata and 100+ manually reviewed edge examples. Resolve author/time aliases and controlled concept tags conservatively.  
**Acceptance:** no unlicensed full text served; all pilot passages have canonical reference and provenance; explicit data-quality report covers collisions, duplicates, missing anchors, orphan edges and uncertain links. **Depends:** v0.3.0.

### v0.5.0 — Typed research API v1 [P1; 2 cycles]
**Changes:** FastAPI service with /health/live, /health/ready, /v1/works, /v1/persons, /v1/passages, /v1/concepts, /v1/links and /v1/graph/neighborhood; OpenAPI + generated typing guidance. Use parameterized Cypher, bounded traversal, pagination, read-only credentials, query timeout, input validation, stable errors and correlation IDs.  
**Acceptance:** unit/contract/integration tests with tiny fixture; readiness checks actual Neo4j connectivity; arbitrary Cypher cannot be submitted; fail closed for unauthorized requests. **Depends:** v0.4.0.

### v0.6.0 — DvirOS service integration contract [P1; 1–2 cycles]
**Changes:** versioned HTTP contract, authentication and signed service identity, DvirOS BFF adapter, error states, rate limits and research-evidence response schema. Document DvirOS Research workspace navigation: research / philosophy, projects, source trail and saved studies. Neo4j has no independently managed human accounts. Mock provider for DvirOS while real service unavailable.  
**Acceptance:** DvirOS can query sandbox research service through server only; no Neo4j URI/credentials leaked into frontend bundle; contract tests between repos pass; offline/empty/error UX is explicit. **Depends:** v0.5.0.

### v0.7.0 — Graph explorer inside DvirOS [P1; 2–3 cycles]
**Changes:** integrated Next.js routes/components in DvirOS for book/person/concept pages; interactive directed graph with type/evidence legend, bounded neighborhoods, breadcrumbs, detail drawer and Sefaria source links; Hebrew RTL, accessible keyboard navigation and mobile layout. Work stays split across both repos and is tracked by cross-repo PR links.  
**Acceptance:** navigate Work -> Passage -> cited source with exact reference; visible distinction verified vs inferred; stable UI at 500 visible nodes by progressive expansion/clustering; accessibility smoke. **Depends:** v0.6.0.

### v0.8.0 — Bilingual text, metadata and concept search [P1; 2 cycles]
**Changes:** search on Hebrew and English titles/aliases, diacritic and punctuation normalization without losing canonical IDs, lexical passage index where licensed; filters for author, work, period, concept, text version, link status and evidence type. Saved filters in DvirOS.  
**Acceptance:** 50 frozen research questions evaluated by reviewer; target precision@5 >= 0.80 on annotated pilot set, with failure analysis; every result includes precise anchor. **Depends:** v0.7.0.

### v0.8.7 — Offline quality-evaluation harness (DRAFT)
**Implemented foundation:** bounded frozen judgment/capture evaluator, explicit Precision@5 over judged top-five results, source-anchor and pagination-completeness checks, synthetic-only CI fixture, and reproducible SHA256 evidence hashes.
**Remaining acceptance:** collect and adjudicate 50 genuine independently reviewed Jewish-philosophy questions, verify authorized source anchors and rights, produce representative query metrics and obtain a separately authorized human sign-off. This version does **not** satisfy the v0.8.0 research-quality release gate.

### v0.8.8 — Private dual-review preparation (DRAFT)
**Implemented foundation:** offline import of frozen complete metadata-only search captures into reviewer packets; independently completed judgment templates, packet-SHA provenance, explicit dispute adjudication and generation of the v0.8.7 evaluator input plus HOLD audit. Outputs are private 0600, synthetic fixtures remain clearly labelled.
**Remaining:** implement authorized audited capture on the approved research host; real independent reviewer identification, question selection, edition rights clearance, evidence adjudication and 50-question release evidence. No auto approval or production switch.

### v0.8.9 — Signed private search capture (DRAFT)
**Implemented foundation:** local bearer/HMAC GET collection of bounded scan or indexed prefix results; stable per-page request and cursor fingerprints; private frozen snapshots and HMAC manifests verified offline; synthetic unit and CI checks.
**Remaining:** authorized deployment with DvirOS SSO/RBAC and enforcement of signed-call policy; corpus/index revision pinning, independent provenance and rights controls, 50 genuine reviewed research questions and external approval. No production rollout.

### v0.8.10 — Bound observed search projection and index status (DRAFT)
**Implemented:** opt-in signed before/after capture observation of bounded, all-visible result titles/anchors per queried kind plus physical index readiness/coverage, with a versioned HMAC-bound observation, offline verification and drift rejection. Backward-compatible with older v0.8.9 manifests.
**Limitation:** not a database snapshot or complete corpus fingerprint; aliases, edition links, source text and graph edges may change undetected. Full immutable versioning, licensed corpus provenance and reviewer signoff remain HOLD.

### v0.8.11 — Bounded source/edition/evidence provenance (DRAFT)
**Implemented:** signed private, allowlisted read-only listing of SourceRecord, Edition and Evidence metadata; explicit cursor completion and before/after HMAC-bound SHA256 observations of source checksums and edition/evidence version/status. Preserves the v0.8.10 search projection guard and v0.8.9 legacy output contract.
**Remaining:** provider hash verification against real approved source snapshots, immutable source/edition receipts, relationship/alias coverage, true cross-request snapshot isolation, independent rights adjudication and the 50-question pilot. Remains HOLD.

### v0.8.12 — Retained local metadata-source receipt (DRAFT)
**Implemented:** HMAC tamper-evident local receipt generation/verification for retained original link CSV bytes or canonical JSON version metadata, matched to exported SourceRecord ID, URL, stored SHA256, and metadata-only rights status. Exclusive private outputs; optional authenticated association to a v0.8.11 capture event; synthetic tests and isolated graph smoke.
**Remaining:** external immutable source snapshots, independently verified provider authenticity, actual graph membership/edition rights proof, 50 real scholarly judgments, BFF security and production approval. Local checks do not grant source rights or immutable corpus revision.

### v0.8.13 — Bounded SourceRecord membership in frozen observation (DRAFT)
**Implemented:** private signed complete enumeration of the SourceRecord metadata subset; exact SHA256 reconstruction matching the v0.8.11 HMAC-protected source projection; a verified v0.8.12 retained-file receipt must match exactly one member. The offline 0.8.13 HMAC witness contains bounded source metadata rows and is independently recomputable from the captured aggregate digest, receipt and original local bytes. Synthetic and isolated Neo4j integration tests.
**Remaining:** independent public-key signatures by the source provider/trusted archival operator, externally immutable storage, a transactionally consistent graph revision, rights clearance, 50 genuine scholarly reviews and production security approval. Observed membership is not full-corpus membership; release HOLD.

### v0.8.14 — Pinned Ed25519 archive-claim verification (DRAFT)
**Implemented:** a private, offline Ed25519 public-key verification interface with operator-pinned trust policy and restricted archival namespace; binds a signed archive-operator claim to the exact 0.8.13 bounded source membership witness, 0.8.12 file checksum receipt, 0.8.11 capture manifest and claimed versioned S3 Object Lock metadata report. Fail-closed envelope, replay, role, schema, rights, content and retention checks. No production trust keys or source reports in repository; synthetic-only CI.
**Remaining:** external organizational identity validation, authenticated provider archive APIs/version metadata, independently checked Object Lock retention/WORM immutability, verifiable timestamp/third-party trust governance, source license and scholarly reviews. Cryptographic validity of a pinned key is NOT independent archive immutability. HOLD.

### v0.8.15 — Version-scoped AWS S3 checksum and Object Lock observation (DRAFT)
**Implemented:** optional read-only AWS S3 HeadObject + GetObjectRetention checks,
after the verified 0.8.14 signed operator claim and 0.8.11–0.8.13 local chain.
ExpectedBucketOwner, object version, FULL_OBJECT SHA-256, content length, mode,
retain-until and successful API status must agree exactly; region/HTTPS/SigV4
client and standard endpoint required. Private failure-closed 0600 report,
synthetic-only tests, pinned opt-in boto3 dependency and accurate architecture
diagram. No live AWS account or production credentials were available.
**Remaining:** independent archive history/custody attestation, signer organization
onboarding/revocation, legal rights, trusted non-synthetic S3 evidence,
50 human scholarly judgments and production signoffs. No research release; HOLD.

### v0.9.0 — Research-grade graph analytics [P1; 2 cycles]
**Changes:** five original questions rewritten as versioned, parameterized API analyses; shortest path with edge provenance; centrality as frequency measure not authority; co-citation as hypothesis; chronology constraints; author/work/period comparisons; analysis results include definition and limitations.  
**Acceptance:** 100+ gold-set links and at least 20 manually checked analytical examples; no assertion of influence without supported temporal/primary evidence; performance tests with published fixture sizes. **Depends:** v0.8.0.

### v0.10.0 — Research project / notes / annotation workflow [P1; 2 cycles]
**Changes:** DvirOS saved research questions, notebook artifacts, annotations, graph paths, query snapshots, citations and source collections; operational records in DvirOS Postgres, graph references in Neo4j. Human review queue for interpretation with proposed/reviewed/rejected/accepted and immutable audit. Export BibTeX/CSV/JSON.  
**Acceptance:** full trace from research claim -> evidence -> source edition; approvals cannot be forged by read-only researcher; reproduce saved study from recorded graph/corpus versions. **Depends:** v0.9.0.

### v0.11.0 — Evidence-constrained GraphRAG [P2; 2–3 cycles; feature flagged]
**Changes:** graph-neighborhood+passage retrieval, optional local lexical/embedding hybrid, refusal/uncertainty paths, cited answer builder, prompt-injection boundary, provider abstraction; no paid APIs without explicit approval. AI outputs create proposals, never verified graph edges.  
**Acceptance:** each asserted quotation resolves to extant passage/version; blind evaluation covers missing sources, hostile documents, Hebrew/English and conflicts; hallucination rate metric documented and release gate chosen before enabling. **Depends:** v0.10.0. **May ship disabled** in v1.0.

### v0.12.0 — DvirOS evidence/agent orchestration [P1; 2 cycles]
**Changes:** registered research tool with read-only typed operations, task input/outputs, bounded costs, progress/checkpoints, interruption/retry and review-inbox evidence cards. Research agents can suggest claim/relationship edges but cannot publish/alter verified knowledge without review.  
**Acceptance:** agent run visible in DvirOS with source trail, exact queries, outcome and failed/rejected states; no unrestricted Bolt or graph write access for agents. **Depends:** v0.10.0; v0.11 optional.

### v0.13.0 — Reliability, backup and corpus lifecycle [P0 before GA; 2 cycles]
**Changes:** importer run states and metrics, snapshot manifests, repeatability, disk alerts, restore verification, start/stop/resume procedures, data retention and disaster recovery guide. Use offline dump/restore for Neo4j Community; do not assume enterprise online backup is available. No public 24/7 SLA until hosting is actually always on.  
**Acceptance:** restore drill into isolated DB succeeds; pilot RPO <=24 h and RTO <=4 h are demonstrated or GA remains blocked; update source snapshot is reversible. **Depends:** v0.4.0+.

### v0.14.0 — Security and release hardening [P0 before GA; 2 cycles]
**Changes:** threat model, explicit RBAC boundary in DvirOS, service-to-service authentication, TLS reverse proxy, secrets rotation, rate limiting, dependency/SBOM scans, audit, safe logging; hardened CI and deployment docs.  
**Acceptance:** no tracked secrets, critical/high exploitable findings or open network Bolt; permission and prompt injection negative tests pass; security checklist signed off. **Depends:** v0.6.0+.

### v0.15.0 — CI/CD staging, monitoring and release candidate [P0 before GA; 1–2 cycles]
**Changes:** minimal fast PR checks (format/type/unit/contract + short Neo4j integration), on-demand intensive tests, immutable image tags/digests, staging configuration, migration dry run, rollback guide, metrics and alerting.  
**Acceptance:** build/publish/staging smoke and rollback pass, instrumented request p95 and data freshness are visible, reproducible release manifest includes code SHA, DB schema version and corpus version. **Depends:** v0.13.0 and v0.14.0.

### v1.0.0 — Production GA: DvirOS Philosophy Research [P0; release gate]
**Deliverable:** users launch a complete source-grounded research workflow from the DvirOS UI; service health, search, graph exploration, analysis, saved study and review function; API backed by recoverable Neo4j + traceable corpus; AI is strictly optional/disabled unless its evaluation passes.  
**Go/no-go:** all P0 and P1 DoD + cross-repo integration green; verified rights/attribution; restore drill; security signoff; manually audited scientific claims; approved operations/runbook. Avoid 24/7 availability claim if Mac sleeps.

### v1.1.0 — Comparative schools & concepts [P2]
**Changes:** curated philosophical positions in Divine providence, prophecy, freedom, God, ethics, mitzvot; explicit quotation vs interpretation and alternative readings. **Acceptance:** three reproducible expert-review studies, each with conflicting interpretation where appropriate.

### v1.2.0 — Multilingual editions, commentary and temporal reasoning [P2]
**Changes:** map translations/editions, Hebrew/English alias governance, chronology uncertain ranges, historical provenance and scholarly bibliographies. **Acceptance:** cross-version reference resolution with audited examples; no implied direct influence from later sources.

### v1.3.0 — Corpora integration [P2]
**Changes:** read-only import *indexes/metadata* from permitted Corpora collections, local adapters, dedup, license checks, provenance mapping; no large transfer to GitHub/Drive and no coupling to pending Corpora readiness. **Acceptance:** one external corpus read-only pilot with full lineage and zero unauthorized replication.

### v2.0.0 — Multi-researcher / publication-grade system [P2]
**Changes:** collaborative workspaces, peer review, publication snapshot exports, scoped API access, multi-user permission model, model evaluations and governance. **Acceptance:** acceptance tests for cross-user data isolation, conflict handling, traceable edits and reproducible published snapshots.

## 4. Release grouping and dependencies

- **Foundation (v0.1–v0.4):** correctness, sources, ontology, licensed pilot; not user-facing.
- **Useful vertical slice (v0.5–v0.9):** working API + actual DvirOS UI + research queries.
- **Research workflows (v0.10–v0.12):** review, saved studies, bounded agent tools, optional GraphRAG.
- **Production controls (v0.13–v1.0):** restore, security, staging, release.
- **Post-GA (v1.1–v2.0):** richer academic knowledge and collaboration.

**Critical path:** v0.1 -> v0.2 -> v0.3 -> v0.4 -> v0.5 -> v0.6 -> v0.7 -> v0.8 -> v0.9 -> v0.10 -> v0.12 -> v0.13/14/15 -> v1.0. v0.11 is parallel/optional; no paid model requirement.

## 5. Definition of Done for every version

1. Real code, docs, migration (if applicable), minimal targeted tests and reproducible commit on its own feature branch.
2. Clear version bump and CHANGELOG entry only when implementation exists; proposed version number alone does not confer release.
3. Source/evidence reference or contract fixture attached for graph-affecting changes; no fabricated sample treated as real Sefaria result.
4. No new real secrets, credential leaks, unauthorized data copies or unbounded DB/LLM query execution.
5. PR to main and merged only after required minimal checks, review/permission boundaries and no conflicting work; verify merged SHA.
6. Report actual code files changed, PR URL, SHA, checks run vs deferred, visible before/after screenshot only for real UI changes. Diagrams are explicitly illustrative, not screenshots.

## 6. Measurable Production GA release gates

| Dimension | Gate |
| --- | --- |
| Authenticity | Every displayed research claim linked to exact source, version and evidence type; AI proposals visibly unverified |
| Data quality | Pilot 100+ manually reviewed examples; no unexplained canonical ID collisions or orphan links; repeat runs idempotent |
| Licensing | Rights metadata and attribution validated per source edition; no unauthorized raw-text distribution |
| Security | Neo4j inaccessible from public browser/network; service authentication, no secrets or high/critical exploitable findings |
| Reliability | Restored backup verified; target RPO <=24h/RTO <=4h measured; no fabricated availability guarantee |
| Performance | Initial goal: p95 <=700ms for lightweight queries on specified benchmark host/dataset; measure and revise before gate |
| Integration | DvirOS route uses real authenticated API, displays failure states, submits research to review and saves versioned results |
| Quality | CI checks and staging smoke green; 20+ gold analytical checks; minimum accessibility checks; rollback demonstrated |
| Research integrity | Claims of historical influence/authority appropriately qualified, with manual review where inference exceeds source linkage |

## 7. Operating policy for future 'continue development'

Review canonical main, this roadmap, existing PRs and the latest real completed milestone. Select and implement the next incomplete SemVer version with meaningful code. Prefer feature progress and small focused tests over exhaustive regression runs, while retaining mandatory security/data checks. Push each actual update to GitHub. Merge prepared branches only after safety, permissions and branch protections are satisfied. For any UI work, show an authentic screenshot/render from implemented code when available; label conceptual diagrams as conceptual. **Never claim a release or deployment until verified.**

## 8. Primary references

- DvirOS: https://github.com/MeiRR17/dvir-os
- Sefaria current public export structure: https://github.com/Sefaria/Sefaria-Export
- Sefaria API: https://developers.sefaria.org/
- Neo4j Operations Manual: https://neo4j.com/docs/operations-manual/current/
- Neo4j Python Driver: https://neo4j.com/docs/python-manual/current/

**Architectural decision:** Neo4j is part of DvirOS product. Learning_Modules is unrelated to further development and deployment.