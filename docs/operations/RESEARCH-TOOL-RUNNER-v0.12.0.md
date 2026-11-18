# v0.12.0 — Registered read-only research-tool runner (Neo-only, DRAFT)

This is the **first Neo-side integration slice** for a future DvirOS research agent. It does **not** integrate with a real DvirOS agent, persist an asynchronous job, supply a model, execute tools selected by an LLM, store human annotations or perform Neo4j writes.

## Three registered operations

| Operation | Required input | Fixed graph reads | Output |
|---|---|---:|---|
| `source_context` | One canonical Passage, bounded metadata query | 1 | Up to 10 exact observed SOURCE_LINK context candidates |
| `compare_contexts` | 2–3 canonical Passages, same query | 2–3 | Up to 12 deduplicated metadata candidates and exact source-ref divergence warnings |
| `review_dossier` | 2–3 Passages, query, 1–8 sorted canonical Evidence IDs | 2–3 | One unsigned metadata-only v0.11.2 review dossier |

The registry is static in `services/research_api/research_tool_runner_v0120.py`. There is no dynamic tool registration, unrestricted Bolt access, arbitrary Cypher, write operation, remote LLM/provider or source text. Each tool reuses earlier bounded, strictly projected v0.11.0–v0.11.2 APIs. All context-source metadata, rights *tags* and graph review labels remain untrusted observations, not approved scholarly claims, authenticated source editions, or license grants.

## Private API (both flags OFF by default)

Both flags must be set to `1` by an authorized operator:

```sh
DVIROS_ENABLE_GROUNDED_CONTEXT=1
DVIROS_ENABLE_RESEARCH_TOOL_RUNNER=1
```

All three endpoints use the existing private service bearer token and existing optional signed-call policy, which covers the full path and query string. Inactive endpoints return 404 with **no graph reads**; malformed flag values fail with 503. This is private operator tooling only; it is not ready for a public browser or DvirOS end-user.

The endpoints are read-only GETs, so request parameters remain in the URI and are included when the existing signed-request mode is used:

```http
GET /v1/research/agent-tools/catalog
Authorization: Bearer <private-service-token>
```

```http
GET /v1/research/agent-tools/plan?operation=compare_contexts&passage_ids=passage:ID1,passage:ID2&query=reference&limit=8&read_budget=3
Authorization: Bearer <private-service-token>
```

```http
GET /v1/research/agent-tools/execute?operation=compare_contexts&passage_ids=passage:ID1,passage:ID2&query=reference&limit=8&read_budget=3&request_checkpoint_sha256=<64-hex-from-plan>
Authorization: Bearer <private-service-token>
```

Example IDs are placeholders. URL-encode user query values and all IDs. `review_dossier` additionally requires `evidence_ids` (1–8 sorted distinct canonical IDs). `source_context` accepts exactly one Passage, not comma-separated IDs. Any extra/duplicate query parameters, invalid selection, wrong tool name, bool-as-budget, out-of-range result limit or insufficient read budget fail closed before querying.

## Two-stage execution and explicit checkpoints

1. **Plan:** validate the operation and all scopes, query and selection; derive an SHA256 of the canonical request parameter fingerprint, including query SHA256, normalized Passage IDs, selected Evidence IDs, result cap and graph-read budget. Return `READY_TO_EXECUTE` with `graph_reads_executed=0` and scheduled upper bounds.
2. **Execute:** require the exact plan fingerprint with the same request parameters. If changed, reject before any graph read. Execute only the hardcoded registered operation (1–3 fixed read-only source-link queries); strictly validate its typed output, and return 0–12 **metadata-only Evidence cards** plus the original typed tool result.
3. **Phase log:** contains three completed synchronous phase records for validation, fixed read-only retrieval and review card projection. It is **not** streaming task progress.
4. **Retry:** replaying the same plan is a *fresh read*, not a continuation or cached result. Checkpoints are **unkeyed SHA256**, not identity proofs, MACs, persistent job-state checkpoints or immutable graph snapshots. They are only plan/request drift detectors. DvirOS must implement authenticated user/workspace state, durable idempotency, cancellation, retry, progress, tracing and review history in its own approved service.

The planned graph-read count is a deterministic upper bound from the fixed tool implementation, **not** a metered cost/latency statistic. Up to 20 observed SOURCE_LINK rows are inspected per graph read, with at most three reads per execution. A truncated sample does not prove full corpus coverage.

No tool result claims user approval, licensed source rights, generated research output or immutable graph history. `human_review_required=true`, `human_approval_recorded=false`, `graph_writes_performed=false`, `provider_or_llm_calls=false`, and `research_release_status=HOLD`.

## Release constraints and tests

The existing upstream PR chain is still Draft; source edition licensing, human scholarly signoff, DvirOS RBAC, full agent orchestration/inbox, security controls, saved tasks and production release approval are **not implemented here**. **Do not merge to main** on the basis of a passing unit/CI test alone.

Focused test: `python -m unittest tests.test_research_tool_runner_v0120 -v`.

Contract: `docs/integrations/RESEARCH-TOOL-RUNNER-v0.12.0.json`.
