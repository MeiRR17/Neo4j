# v0.11.0 — Feature-flagged GraphRAG metadata grounding preview (phase 1)

This is the **first, deliberately limited GraphRAG vertical slice** in Neo. It introduces a real, authenticated research endpoint which takes a canonical Passage ID, a short source-reference search string and a bounded result limit. It reuses the already deployed, fixed, read-only `analysis_source_links` graph query and validates every Evidence/Edge/Passage ID through the existing analysis projection guard.

No language model or paid provider is used. This is *not* a generated answer, scholarly citation check against licensed text, graph snapshot, evidence of influence, or a DvirOS end-user integration.

## Security flag

The endpoint is **disabled by default**:

```sh
DVIROS_ENABLE_GROUNDED_CONTEXT=1
```

An authenticated call while disabled returns 404 **without graph reads**; malformed flag values return 503. Authentication uses the existing private bearer (and existing signed-call mode if independently enabled). Never set the flag on a public browser-facing deployment or enable it without operator authorization.

## Read-only API

```
GET /v1/research/grounded-context?passage_id=passage:canonical-id&query=source-reference&limit=5
Authorization: Bearer <private-server-token>
```

Parameters: `passage_id` must be a canonical Passage ID; `query` is 2–120 Unicode characters without control characters, with 1–12 normalized alphanumeric terms, each no longer than 64 characters; `limit` is 1–10. Unknown or repeated query keys are rejected (HTTP 422), and the private token is required before querying the graph. No arbitrary Cypher, raw source text, URL fetching, LLM provider or provider-controlled tools are introduced.

The query matches **only** source-reference metadata from at most the first 20 graph SOURCE_LINK records for that Passage. Search comparisons use Unicode NFKC, case folding and combining-mark removal for Hebrew niqqud; the actual original reference and canonical IDs are never rewritten. Match ranking is deterministic: contiguous reference substring first, otherwise all query terms. It returns exact Evidence ID, Edge ID, source/target Passage IDs, `source_ref`, observed review statuses, `version_id`, `rights_tag` and explicit limitation flags. A field such as `review_status=approved` is an **observed catalog label**, not independent human review or source rights clearance for a new claim.

## Explicit refusal / uncertainty modes

- `CANDIDATES_FOUND`: one or more observed metadata references match within the sampled window.
- `NO_METADATA_MATCH`: the **complete observed window** contains no reference match. This does **not** prove no source elsewhere in the entire corpus.
- `WINDOW_TRUNCATED_NO_MATCH`: no match in the bounded sample, but more graph links may exist. Never present this as an exhaustive negative conclusion.

Every response sets `generated_answer=null`, `claim_approved=false`, `licensed_source_text_available=false`, `independent_source_rights_verified=false`, `graph_snapshot_verified=false`, `historical_influence_proven=false`, `research_release_status=HOLD`. Each context has `source_text_available=false`. Malformed/unexpected source projection fails closed as HTTP 503 and may not leak source payloads. Metadata text is **untrusted data**, never an instruction for an LLM.

## Remaining v0.11.x work

A licensed Passage text adapter, version-aware source text proofs, optional local-only lexical/embedding hybrid retrieval, conflict-aware answers with explicit uncertainty, safety evaluation on adversarial Hebrew/English questions and an approved enablement gate are **not implemented**. Do not enable model-written claims or merge this Draft into main until the upstream security, corpus rights, reviewer and release gates pass.

Focused check: `python -m unittest tests.test_grounded_context_v0110 -v`. Dedicated integration contract: `docs/integrations/GROUNDED-CONTEXT-v0.11.0.json`.
