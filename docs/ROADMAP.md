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

### v0.8.15 — Read-only S3 exact object-version and COMPLIANCE observation (DRAFT)
**Implemented:** named-profile, expected-owner and fixed-region AWS SDK checks for exact object VersionId using HEAD with FULL_OBJECT SHA256 and separate GetObjectRetention; validates current COMPLIANCE mode and expiry against a pinned v0.8.14 Ed25519 signed archive-operator claim, and exact local v0.8.11–0.8.13 source/corpus receipt chain. Produces a locally HMAC-signed private audit and offline re-verification. Synthetic mocked S3 client in CI only.
**Remaining:** real read-only AWS operator credentials, independently on-boarded organizational identity and bucket policy controls, verified external immutable retention over time, full transactionally frozen source corpus/edition/graph revision, legal rights, human-reviewed 50 questions and DvirOS production approval. Snapshot read is point-in-time, not immutable archival proof. Release HOLD.

### v0.8.16 — STS and S3 bucket governance, separated sampling (DRAFT)
**Implemented:** operator-authorized read-only STS caller-account validation and exact ExpectedBucketOwner S3 bucket control reads (versioning, four public access blocks, bucket policy public status, bucket Object Lock enabled) layered on the existing v0.8.15 exact-version FULL_OBJECT checksum and COMPLIANCE retention check. HMAC-signed private report and offline verification. Separate signed observations can be compared after at least 24h, with distinct AWS request IDs, without claiming continuous protection.
**Remaining:** independently documented organizational signer identity, full IAM/AccessPoint/SCP and account-level public-access audit, external trusted timestamps, ongoing actual AWS archive retention verification, licensed/immutable corpus source editions, 50 human-reviewed research questions, DvirOS SSO/RBAC and authorization. CI uses synthetic fake AWS and real isolated Neo4j only. HOLD.

### v0.9.0 — Research-grade graph analytics [P1; 2 cycles]
**Implemented first slice (DRAFT):** authenticated, fixed-Cypher exploratory endpoints for directed observed SOURCE_LINKs and shared-target co-reference candidates, retaining exact Evidence IDs and separate review statuses, with strict request filters, bounded rows and no inference of historical influence. Synthetic contract and denial tests. **Still pending:** shortest paths, frequency/chronology analyses, author/work comparisons, 100+ manually reviewed links, 20 real analytical cases, legal rights and production authorization. HOLD.
**Changes:** five original questions rewritten as versioned, parameterized API analyses; shortest path with edge provenance; centrality as frequency measure not authority; co-citation as hypothesis; chronology constraints; author/work/period comparisons; analysis results include definition and limitations.  
**Acceptance:** 100+ gold-set links and at least 20 manually checked analytical examples; no assertion of influence without supported temporal/primary evidence; performance tests with published fixture sizes. **Depends:** v0.8.0.

### v0.9.1 — Bounded evidence-linked directed path discovery (DRAFT)
**Implemented:** new authenticated /v1/graph/evidence-path reads a direct observed SOURCE_LINK if available; only otherwise checks bounded 2-hop directed source-link candidates. Fixed Cypher binds each edge to an Evidence record and filters rejected/disputed observations; responses retain precise passage, edge, evidence ID, source reference and two review states, with strict input and projection guards. Synthetic API-denial tests and a separate real isolated Neo4j direct/two-hop/reverse integration smoke. This is a scoped path-discovery feature, **not** proof of historical influence or global graph shortest path.
**Remaining:** external source authenticity and edition rights, graph snapshot isolation, 100+ real reviewed links, 20 real analytical cases, meaningful denominator-based frequencies, chronology validation, author/work comparisons, performance evidence and DvirOS identity authorization. Both v0.9.0 and v0.9.1 are draft; production/research status HOLD.

### v0.9.2 — Bounded SOURCE_LINK frequencies and tentative author chronology (DRAFT)
**Implemented:** authenticated, fixed-Cypher link metrics for the first 50 canonically ordered incident edges plus one lookahead, with explicit sample denominator, incoming/outgoing counts and internal approval/contested/pending statuses. A separate endpoint reads one eligible direct SOURCE_LINK Evidence binding and up to two linked Person author metadata records per Work; it records disjoint or overlapping author year ranges only when each Work has exactly one dated author. Missing/ambiguous chronology returns unknown rather than guessed dates. Fixed typed DTOs, strict allowlisted query parameters, synthetic denial tests and disposable Neo4j integration smoke.
**Remaining:** genuine whole-corpus centrality, audited source chronology and publication dates, verified author/Work edition identities, 100+ manually checked links, 20 real analytical examples, 50 genuine search questions, benchmarks, rights and DvirOS production approval. Author year relation is not proof of citation or intellectual influence. Release HOLD.

### v0.9.3 — Evidence-linked Work and author comparison (DRAFT)
**Implemented:** authenticated metadata-only comparison of two distinct canonical Works. A fixed Work descriptor read returns its recorded title, provider reference, and up to two Person author IDs/year ranges with a third-item ambiguity lookahead. A second fixed, evidence-linked SOURCE_LINK query is run in both directions, each capped at 10 displayed canonical passage pairs plus one lookahead. Every observed edge retains exact matching Evidence ID, link/evidence review statuses, source anchors, rights/version tags and direction. Per-direction sampled denominator and joint-approved/pending/contested status counts are explicit. Missing Works return 404; malformed IDs, author records, out-of-scope Work/passages, duplicate Evidence and unexpected source text fail closed. Nine synthetic security/contract tests, synthetic real-Neo4j two-Work integration, docs and diagram.
**Remaining:** 100+ scholarly reviewed link examples, 20 independently assessed analyses, provenance and edition rights verification, evaluated historical authorship, full-population centrality/period metrics, reproducible benchmark and DvirOS identity/SSO/RBAC. Two small samples and catalog author IDs never prove historical influence or publication order; release HOLD.

### v0.9.4 — Repeatable bounded Work-comparison receipts and synthetic fixture timing (DRAFT)
**Implemented:** a metadata-only comparison receipt at GET /v1/analysis/works/compare/receipt, wrapping the validated v0.9.3 result. The Work author query now orders Person IDs before taking its 3-row author lookahead, eliminating one source of nondeterministic samples. A local, UNSIGNED SHA-256 over sorted-key UTF-8 JSON identifies the exact returned comparison; a separate SHA-256 identifies the two fixed server-owned Cypher templates. One sampled, bounded comparison still consists of four sequential graph queries, not a transactionally isolated graph snapshot. Strict response typing and fail-closed request/row boundaries remain. Nine synthetic contract/security tests cover replay, drift, tampering, invalid input and 20 distinct *synthetic* analytic cases. The disposable CI Neo4j smoke repeats one 2-Work/2-author/1-cross-link fixture 20 times and logs p50/p95 latency without a performance pass claim.
**Remaining:** scale-representative fixture sizes and cost budgets, independently verified source authenticity and rights, 100+ real manually checked source links, 20 human-assessed analytical examples, 50 genuinely reviewed search questions, trusted authorship/chronology, global centrality definitions, DvirOS RBAC/SSO and final approvals. Matching unsigned hashes prove only that the bounded encoded observations match, never historical influence, source licensing or corpus completeness. HOLD.

### v0.9.5 — Reproducible synthetic analytics cost profiles (DRAFT)
**Implemented:** deterministic namespaced fixture generator for 32 and 128 fabricated SOURCE_LINKs between two synthetic Works and two Person author records, yielding stable SHA-256 fixture fingerprints and exact node inventory. CI-only, localhost-only benchmark requires both CI=true and --ack-disposable-fixture, refuses pre-existing fixture nodes, seeds two sizes, runs fixed READ-only PROFILE queries (Work descriptor, both source-link directions, incident link frequency) three times per operation and size, validates expected row budgets, then attempts cleanup using only enumerated fixture IDs. Sanitized plan parser discards returned rows and query Details while reporting bounded operator types/count, database hits, scan indication and descriptive p50/p95 HTTP timings. CI preserves a 7-day synthetic-only report artifact. Eleven focused test methods cover fixture repeatability, injection and budget denials, cost parsing, interrupted seeding cleanup and CI guard. No production performance or corpus completeness claim.
**Still pending:** representative/high-cardinality corpus benchmarks and explicit SLO budgets, tuned indexed paths, independent historical/author/edition validation, 100+ manually reviewed links, 20 truly human-checked analytical cases, 50 real quality questions, licensing, DvirOS SSO/RBAC and research approval. This fixture is NOT scholarly gold-set evidence and release stays HOLD.

### v0.9.6 — Index-anchored cross-Work SOURCE_LINK traversal and pinned cost deltas (DRAFT)
**Measured baseline (isolated v0.9.5 synthetic Neo4j):** at 32 SOURCE_LINKs, each cross-Work direction cost 4,366 dbHits; at 128, 66,382 dbHits, a 15.204x cost growth for 4x graph links. The Work descriptor stayed at 12 dbHits; incident frequency at 15. Evidence: GitHub Actions run #43099681819, artifact #13891625668, commit ae10aad62fb7b5fb1be2278b0b52536711a14bee.
**Implemented:** changed the fixed read-only cross-Work query to start from a source Passage indexed on work_id (migration 002: passage_work_lookup), traverse directed SOURCE_LINK and filter target Work, while retaining Evidence matching, review state and all bounded identifiers. Added a strictly validated median-dbHits comparison with the pinned baseline, reporting old/new costs and 32→128 scaling with no text/plan Details. CI retains a seven-day sanitized delta artifact. The revised non-indexable target filter (coalesce) was validated in successful isolated CI run #43102371908, artifact #13892712664: both directions dropped from 4,366 to 334 dbHits at 32 links (92.35% less), and from 66,382 to 1,102 at 128 links (98.34% less); observed growth is 3.299x instead of 15.204x. A fixed-fixture CI regression gate now enforces conservative dbHits ceilings and scale-growth budget; twelve tests cover validation, status nonclaims and indexed Cypher. These figures do not establish production performance.
**Remaining:** representative benchmark data and production-grade cost/SLO gates beyond the new synthetic-only regression checks, 100+ human-reviewed links, 20 authentic human-audited analyses, source/edition rights, author history verification, DvirOS SSO/RBAC and release approval. HOLD.

### v0.9.7 — Distribution-sensitive SOURCE_LINK cost stress matrix (DRAFT)
**Implemented:** an opt-in, disposable-CI-only stress suite with 256 and 512 synthetic source links under two deterministic graph topologies: (1) fully distinct source/target Passages and (2) a high-fanout shared source Passage with 128 or 256 outgoing links, with separate Evidence per edge and two Work/Person records. Every case uses namespaced canonical IDs, a SHA-256 fixture fingerprint, exact pre-seed inventory absence, safe synthetic write scope and post-cleanup verification. Four fixed read-only analytical PROFILE operations are run three times for each case, validating the 11-row cross-Work windows, 1-row Work descriptor, and 1- versus 51-row incident-frequency query windows. Output retains only sanitized hit counts, timing, operator safety flags, fixture sizes/fanout and 256→512 cost growth by topology. Twelve suite-contract tests plus eight gate-security tests and a seven-day GitHub Actions artifact are included. First complete CI run #43105105335, commit 194caddf0232c515254f72b8e6ed97c4c55fc1b7, measured per-direction Work-link costs of 2,126 dbHits (disjoint-256), 1,873/2,126 (hub-256), 4,174 (disjoint-512) and 3,665/4,174 (hub-512); hub incident-frequency costs were 1,386/2,666 hits. A second fail-closed topology-specific cost gate now checks 256/512 cost ceilings, zero full/label scans or expensive joins, and no more than 2.8x cost growth for 2x edges. The older v0.9.6 32/128-link regression gate remains enforced.
**Still pending:** verify exact-head CI after adding the topology-specific synthetic cost gate; realistic corpus scale, multi-Work imbalance and long-tail distribution, independently validated and licensed source metadata, human-reviewed real examples, DvirOS SSO/RBAC, real throughput and SLA tests. Neither fixture shape is a real historical corpus and research release remains HOLD.

### v0.9.8 — Isolated four-Work distractor-interference cost probes (DRAFT)
**Implemented:** fixed 128 observed SOURCE_LINKs between two selected Works plus a separate pair of unrelated Works with 0, 128 or 512 disjoint source links. Each of the three deterministic synthetic cases has four Work/Person records, Evidence per relationship, canonical IDs, fixture SHA-256, exact pre-write inventory absence, and post-cleanup verification. The CI-only, opt-in runner profiles four fixed read-only analytics operations three times per case (36 observations total), compares median dbHits with the 0-distractor baseline and records per-operation ratios, without leaking query results, source text or credentials. Nineteen negative and contract tests cover isolation, graph size, repeated runs, failure cleanup, input denial, fixture hash validation and research HOLD flags. First complete isolated Neo4j run #43108294329 (head 2e8faf49) observed stable 1,102 dbHits per Work-link direction with 0, 128, and 512 unrelated links; Work descriptor stayed 12 and incident frequency 15. No full/label scans or expensive joins appeared. A new fail-closed fixture-specific gate checks per-operation budgets (Work 30, directional links 1,600, frequency 30), ratio-to-control <=1.25, exact fixture hashes, bounded rows, and approval-denial flags. CI archives raw sanitized observations and gate evidence for seven days; existing v0.9.6/v0.9.7 regression gates are unchanged.
**Remaining:** verify exact final-head CI after adding the new synthetic gate, measure selectivity at representative corpus scale, historical source and rights validation, multi-query snapshot isolation, full research acceptance, DvirOS RBAC/SSO and production release approval. The new budgets are synthetic CI ceilings only; never a production SLO. HOLD.

### v0.9.9 — Bounded evidence-linked Work audit pages (DRAFT)
**Implemented:** authenticated, private metadata-only GET /v1/analysis/works/links/audit with two distinct canonical Work IDs, optional canonical edge-ID keyset cursor and 1–20 ordered SOURCE_LINK results per page. One fixed read-only query anchors the source Passage to existing work_id index, expands *directed* links, filters the target Work with the proven v0.9.6 query shape, verifies its exact Evidence node and independent edge/Evidence review status, returns at most 21 records (20 + lookahead), and never exposes source texts. Two bounded Work descriptor reads reject nonexistent Works; strict row projection and monotonic Edge-ID checks prevent inconsistent or injected pagination. Cursor reflects only the most recent bounded read, never a consistent multi-page graph snapshot. Thirteen security/contract tests plus isolated real Neo4j API smoke cover authorization, cursor traversal, scope, duplicate/extra query arguments, safe error responses, lookahead integrity and missing Works. An existing v0.9.6 synthetic cost gate exposed a preexisting incident-frequency plan instability (181/661 dbHits versus previous 15 at 32/128 links); v0.9.9 now explicitly anchors this read to the canonical Passage.id uniqueness index before undirected expansion, without raising the guard budgets. Existing performance gates remain unchanged.
**Remaining:** independently reviewed source-licensing and attribution records, snapshot-consistent resumable auditing, cross-page tamper-resistant export, multi-Work representative workload performance, 100+ validated historical links and 20 human-reviewed cases, DvirOS SSO/RBAC. This API is metadata observation for private review and scholarly/public release remains HOLD.

### v0.9.10 — HMAC-bound immediate-prior-page audit witness (DRAFT)
**Implemented:** authenticated GET /v1/analysis/works/links/audit/checked with a server-issued HMAC-SHA256 checkpoint bound to directed Work pair, canonical Edge cursors, page size, full previous metadata-window fingerprint, query-template SHA-256 and ten-minute expiry. Domain-separated MAC uses the existing protected 0600 service bearer key. On continuation, token signature/scope/expiry are checked before DB reads, then the immediately previous page is independently re-observed with the same read-only bounded query. Changed Evidence metadata returns sanitized 409 AUDIT_DRIFT before advancing. 14 focused contract/security tests and real isolated Neo4j mutation-then-restore smoke added. During CI, the unchanged v0.9.8 unrelated-Work gate detected an actual incident-frequency regression: at 512 unrelated SOURCE_LINKs, dbHits jumped from 15 to 6,425 while Work comparison stayed at 1,102. The frequency query now binds its indexed Passage incident relationships before separately matching Evidence using a second WITH boundary; a source-level regression test protects this query shape. CI now retains sanitized diagnostic cost reports even if the gate fails. The prior synthetic cost thresholds remain unchanged.
**Explicit limits:** one preceding page only; NOT transactional snapshot isolation, complete prior-chain replay, detection of all simultaneous writes or unseen edits, cryptographically signed corpus export, source rights, historical influence, or research/public release. HOLD. Next: immutable corpus-revision governance, archival verification and DvirOS RBAC/SSO, independent scholarly review.

### v0.9.11 — Bounded two-pass Work-link metadata export and offline HMAC verification (DRAFT)
**Implemented:** authenticated read-only GET /v1/analysis/works/links/audit/export traverses an entire *bounded selected Work pair* with at most five pages of 20 links (100 max). It repeats the traversal, validates exact Evidence IDs, independent review states, global edge monotonicity and duplicate Evidence denial. Any observed discrepancy returns sanitized 409 AUDIT_DRIFT; a result beyond 100 fails closed rather than silently truncating. Equal passes produce a canonical UTF-8 JSON metadata-only manifest and a domain-separated HMAC-SHA256 receipt derived from the protected local API bearer secret, with immutable file bytes possible after downloading but NO claim that Neo4j source data are immutable. A standalone offline verification CLI checks integrity and fixed signed envelope shape using the local 0600 service token. Twelve focused security/functional tests and isolated real Neo4j API smoke added. Existing cost gates unchanged.
**Limitations:** two sequential passes may both include the same unobserved error and are not transactionally snapshot consistent; changes can occur between or after reads. HMAC authenticates local-key knowledge but is not an independent digital signature or archival key-management scheme. Work pairs with over 100 observed links are refused. No rights, historical influence, corpus-wide release or human-reviewed quality is established. HOLD.
**Next:** governed immutable corpus version identifiers with database-backed revision/transaction controls, durable exported receipts and key rotation, scholarly review, DvirOS RBAC/SSO, representative performance and license assessment.

### v0.9.12 — Governed append-only observation revision ledger (DRAFT)
**Implemented:** non-destructive migration 005 introduces unique AuditRevisionHead and AuditRevision IDs, plus an indexed scope/sequence lookup. A fixed local-only metadata writer first verifies the complete v0.9.11 HMAC export, derives a directed Work-pair scope, and bootstraps one ledger head without resetting earlier history. New append operations lock that head in one Neo4j statement, compare expected sequence, chain SHA-256, previous revision ID and Work scope, create a new canonical hashed observation-revision record, and advance the head atomically. A local verifier replays up to 32 records, recalculates SHA-256 chain links and denies gaps/tampering. Explicit CLI approvals require a local operator flag plus DVIROS_AUDIT_REVISION_WRITE_ENABLE=1; disposable CI writes require CI=true plus a separate fixture acknowledgment. No public write API or Work/Evidence mutation. Twelve focused tests cover integrity, stale CAS, HMAC tampering, operator guardrails and capacity. Real isolated Neo4j smoke checks append/rejected-stale/replay and exact synthetic cleanup. Existing source rights and performance gates are unchanged.
**Critical boundary:** database uniqueness and cooperating-writer CAS protect this *metadata observation chain* only. They do not prevent other privileged Neo4j users from rewriting or deleting these nodes, do not freeze Work/Evidence records, and do not establish a DB-wide transaction snapshot, archival Object Lock or historical source authenticity. Production DB roles, durable independent attestations, revision-aware graph writers and DvirOS SSO/RBAC remain outstanding. HOLD.
**Next:** storage-governed immutable evidence revision anchors, real corpus data version checks and independent archival evidence before a production release or research approval.

### v0.9.13 — Independently pinned revision-ledger anchor (DRAFT)
**Implemented:** a read-only v0.9.12 chain-checkpoint capture, an offline Ed25519 detached signature using an explicitly supplied local private key, and a fixed pinned-public-key policy with signer/Work-scope matching. A bounded live comparator first validates the full chain, then checks the signed anchored sequence and historical revision digest against the current Neo4j prefix. This detects stale/removed/rewritten anchored records, while accepting legitimate later appended revisions. An explicit CLI offers capture/sign/verify/compare; private signing keys are never generated, printed, uploaded or committed by the application. Fifteen contract/security tests cover policy tampering, signature substitution, prefix rollback/rewrite, safe key permissions, scope mismatches and CLI operations. Existing disposable Neo4j integration now exercises an ephemeral CI-only signer, tamper denial and preservation of the signed prefix after a second append; seven-day sanitized artifact provided. No changes to source graph writers or current performance budgets.
**Limits:** operator-pinned key possession is not independent organizational identity verification. The signed ledger observation is not an immutable database snapshot, does not prevent privileged database edits between checks, is not a remote WORM/Object Lock archive, and does not license/verify historical sources. External durable anchoring, retention/IAM proofs, key rotation and true graph revision controls remain pending. Research release HOLD.
**Next:** optional independently governed artifact persistence and read-only S3 version/retention proof for ledger checkpoints, signed key rotation policy, real graph revision authorizations, DvirOS SSO/RBAC, source licensing and human scholarship review.

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