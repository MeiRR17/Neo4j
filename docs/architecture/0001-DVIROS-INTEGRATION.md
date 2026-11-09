# ADR 0001 — Neo4j is the Jewish Philosophy Research Engine inside DvirOS

**Status:** Proposed for implementation; product direction accepted by owner, technical contract pending implementation.
**Date:** 2026-11-09
**Canonical service repository:** MeiRR17/Neo4j
**Product shell / client:** MeiRR17/dvir-os
**Supersedes:** Treating Neo4j as a learning exercise or a Learning_Modules feature.

## Context

DvirOS currently provides a Next.js PWA bootstrap, source-of-truth governance, planned FastAPI/Postgres and evidence-first agent approval, but no live research-service bridge. Neo4j currently supplies a Windows-specific demo Compose, Sefaria acquisition script and five Cypher examples, not a production service.

## Decision

1. **One research service:** Neo4j repository owns its graph domain, ingestion, migrations, read API, research analysis and provenance. DvirOS owns authenticated product UX, account identity, saved research workspace, approval inbox and cross-domain orchestration.
2. **One user-facing application:** Research routes reside inside the DvirOS Next.js application, not in a separate Neo4j React site. Neo4j Browser is developer/admin-only.
3. **Boundary:** DvirOS server/BFF calls private Neo4j Research API over HTTPS/service network; end-user browsers never receive Bolt credentials and cannot issue arbitrary Cypher. No consumer connects directly to graph DB.
4. **Storage:** Neo4j holds Work/Passage/Person/Concept/SourceRecord/Evidence/Edge with canonical IDs; DvirOS Postgres holds identity, research project, note, saved query, review and agent execution record, storing opaque graph IDs only.
5. **Data:** Sefaria and independently licensed sources feed an idempotent, resumable pipeline. Corpora may be read-only source adapter later, not a hard dependency. Preserve raw source snapshots or checksums with permission boundaries; never automatically duplicate an entire local corpus.
6. **Epistemic boundary:** graph links are *observed references*, *reviewed interpretations* or *unverified suggestions*. Algorithms/AI never upgrade a suggestion to an asserted scholarly fact on their own.

## Integration sketch

DvirOS Next.js UI (/research/philosophy)
  -> DvirOS authenticated BFF (/api/research/philosophy/*)
  -> Private Neo4j Research API (/v1/*)
  -> Neo4j graph database

DvirOS user identity + permissions -> BFF authz -> service credential.
DvirOS Postgres -> saved sessions/projects/annotations, linking stable graph IDs.
Research API ingestion worker -> Sefaria permitted data -> immutable manifest -> graph.

## Contract v1 (planned)

All payloads include schema_version; any research answer includes corpus_snapshot_id, graph_schema_version, query_id, request_id, generated_at and evidence_id[] as applicable. IDs MUST be stable; dates UTC ISO-8601; cursor pagination for lists. Hebrew text is UTF-8; use language tags he/en, not title-string parsing.

### Read endpoints
- GET /health/live — process liveness only.
- GET /health/ready — Neo4j connectivity + schema compatibility, no false green on process-only check.
- GET /v1/works?query=&language=&cursor=&limit= — work summary, stable work_id, title aliases, edition evidence.
- GET /v1/works/{work_id} — metadata, authorship, source license, coverage.
- GET /v1/passages/{passage_id} — source_ref, normalized_ref, version_id, citation_url and permitted excerpt.
- GET /v1/persons/{person_id} — author metadata, date ranges with uncertainty.
- GET /v1/concepts/{concept_id} — controlled name, alternate names and anchored evidence.
- GET /v1/graph/neighborhood?entity_id=&depth=1&edge_types= — bounded neighbors; max depth fixed server-side.
- GET /v1/paths?from=&to=&edge_types=&max_depth= — bounded path exploration with step-by-step source evidence.
- GET /v1/analytics/{analysis_id} — named, reviewed and versioned query output, never user-supplied Cypher.
- GET /v1/sources/{source_id} — provenance and rights metadata; no raw unlicensed text.
- GET /v1/data/status — snapshot freshness, ingest state and data-quality warnings, no private source paths.

### Workflow callbacks (planned, DvirOS-owned)
- POST /api/research/philosophy/projects — create study in DvirOS operational store.
- POST /api/research/philosophy/review-items — propose interpretation with evidence links; review in DvirOS.
- POST /api/research/philosophy/agent-runs — register bounded research run with review boundary.

Do not implement write operations directly from the browser to Neo4j. Future review-approved graph writes use a dedicated service principal and transactional audit.

### Minimal evidence shape

- evidence_id: stable opaque ID.
- claim_kind: OBSERVED_SOURCE_LINK | HUMAN_INTERPRETATION | MODEL_SUGGESTION.
- review_status: unreviewed | approved | rejected | disputed.
- source_provider, source_ref, source_uri, version_id, rights_tag.
- source_passage_id, target_passage_id (optional depending on claim).
- link_category and observed_at.
- curator/reviewer identity only where legitimately recorded; no invented provenance.
- limitation_note and uncertainty label.

### Response errors

- 400 bad request / invalid canonical identifier.
- 401 missing authentication / 403 scope denied.
- 404 unknown canonical entity / no evidence when absent.
- 409 incompatible corpus/schema snapshot or proposed state conflict.
- 422 request understood but disallowed bounds/semantic input.
- 429 per-client limit with retry hint.
- 503 research service offline, Neo4j unavailable or snapshot maintenance.

Never silently fall back to fabricated data. DvirOS must distinguish offline, unavailable, not found and not evidenced.

## Security and performance envelopes

- Service access from DvirOS backend only, allowlisted identity, HTTPS/TLS or private Unix service boundaries.
- Reader driver credential cannot write; special ingestion principal isolated.
- Parameterized Cypher, max_depth and hard result/page limits, read timeouts and DB query budgets.
- Sources can be malicious untrusted text: escape in UI, isolate from prompt instructions, never execute generated Cypher.
- Local-first deployment on personal machine is best-effort while sleeping; public production requires always-on host and tested restore before claiming SLO.
- Do not introduce pay-as-you-go AI or embedding jobs without approval.
- Publish only permitted source excerpts; Sefaria version and licensing are not uniform across editions.

## Cross-repo implementation discipline

Every coupled feature should include:
1. Research API change and contract fixture in Neo4j.
2. DvirOS BFF+UI change referencing that contract version.
3. Thin consumer tests with real mock responses, not a second copy of business logic.
4. Links to both PRs, explicit deployed version compatibility, a way to disable UI while backend unavailable.
5. Evidence screenshot from actual DvirOS code after UI implementation.

This ADR describes a target architecture, **not a claim of current integration**.
