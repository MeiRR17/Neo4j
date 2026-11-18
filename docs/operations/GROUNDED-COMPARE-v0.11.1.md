# v0.11.1 — Cross-Passage Evidence grounding comparison (DRAFT / OFF)

## Purpose and scope

The v0.11.0 private GraphRAG preview matches source-reference metadata for **one** Passage. This phase adds a bounded, read-only comparison across **2–3 canonical Passage IDs** with one research query. It provides a deterministic list of Evidence anchors, exact source-reference grouping and observed metadata divergence requiring human evaluation. It is **not** a factual answer generator, edition-citation validator, genuine contradiction detector or proof of influence.

Only the Neo repository is changed. DvirOS BFF/UI/SSO/RBAC and saved-study databases remain separate, unimplemented dependencies.

## Endpoint

```http
GET /v1/research/grounded-context/compare?passage_ids=passage:ID1,passage:ID2&query=מורה%20נבוכים&limit=10
Authorization: Bearer <private-service-token>
```

This route is protected by the existing private service bearer and optional signed-call policy. It shares the strict default-**OFF** `DVIROS_ENABLE_GROUNDED_CONTEXT` flag with the v0.11.0 endpoint. Setting it to `1` enables the **metadata-only** endpoint for explicitly authorized private operators. OFF returns 404 without a graph read; malformed flags return 503. No graph writes or remote provider calls exist.

Inputs are exactly `passage_ids`, `query` and optional `limit`. Passage IDs must be 2–3 distinct canonical `passage:` IDs, total length at most 600; IDs are internally sorted for deterministic comparison. Query uses the same 2–120 character, at most 12 normalized terms, Unicode case/niqqud handling from v0.11.0. `limit` is 1–12. Duplicate keys, unsupported filters (`rights=approved`, `model=...`), invalid IDs or control characters receive 422, without graph reads. Authorization is verified before accessing the graph.

## Retrieval and reconciliation

The implementation calls the existing strict, immutable, read-only `analysis_source_links` query for each Passage, via `grounded_context_preview`: **up to three reads**, inspecting **at most 20 observed links per Passage**, with up to 10 matched contexts per source Passage preview. It never executes arbitrary Cypher, downloads source text or builds a prompt for an LLM.

- De-duplicate exact `evidence_id` if the same source link is observed in more than one focus Passage; preserve all `observed_in_passage_ids`.
- Fail closed when one Evidence ID has inconsistent Edge/Passage IDs, source reference, edition/version ID, rights tag or recorded review-status across the separate observed windows. This is an integrity anomaly, not an automatic merge.
- Group returned candidates **only by byte-identical `source_ref`**. A group with multiple version IDs, rights tags or review-status labels gets `OBSERVED_*_DIVERGENCE` flags; missing metadata and disputed/rejected recorded statuses receive separate flags.
- These flags are **operational metadata triage**. Different editions or recorded approval labels are not necessarily contradictory interpretations; `disagreement_is_scholarly_conflict=false` always.
- Return `CONTEXTS_FOUND`, `NO_METADATA_MATCH` or `INCOMPLETE_NO_MATCH`. `additional_matches_may_exist` indicates any truncated per-Passage graph window, locally truncated match list, or truncated final selection. No complete corpus coverage is claimed.
- Preserve original `source_ref`, canonical IDs, exact observed review statuses, version and rights *tags*. Tags are not verified legal permissions. All returned contexts include `source_text_available=false`, `source_rights_verified=false` and `human_claim_approved=false`.

Every response sets `generated_answer=null`, `scholarly_conflict_verified=false`, `source_text_available=false`, `source_rights_verified=false`, `graph_snapshot_verified=false`, `whole_corpus_retrieval_verified=false`, `research_release_status=HOLD`. Source metadata remains untrusted text, never executable instructions.

## Remaining gates

Production integration, independent edition/license review, content-addressed Passage quotations, cross-version rights validation, adversarial Hebrew/English and malicious-document evaluation, optional local hybrid retrieval and any model-written answer builder remain **future work**. Cross-Passage observations are separate reads, **not** a Neo4j transaction or immutable graph snapshot. No PR may merge to `main` until upstream stacked PRs and human security/scholarly release gates pass.

Contract: `docs/integrations/GROUNDED-COMPARE-v0.11.1.json`. Focused check: `python -m unittest tests.test_grounded_compare_v0111 -v`.
