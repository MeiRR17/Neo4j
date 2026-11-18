# v0.10.9 — Signed cross-page Evidence review handoff (Neo-only, DRAFT)

## Problem addressed

The v0.10.6 private handoff accepts Evidence **only from one exact signed page**. A human reviewing different pages would otherwise need to track unrelated handoff files. This version builds one bounded **cross-page draft** for **1–12 sorted, distinct canonical Evidence IDs** from the complete six-filter v0.10.8 triage matrix.

It does not skip the earlier security controls: first independently verifies the six complete v0.10.7 inbox coverage receipts, all v0.10.5 pages, the v0.10.4 queue and 2–6 original study captures. It then builds one signed v0.10.6 handoff **per page actually containing a selected Evidence**, retaining each original per-capture observation history, source/version/rights tags, exact page digest and HMAC receipt. Every selected Evidence is uniquely bound to a source page and to the six-filter matrix.

## API and output

`build_cross_page_review_bundle(matrix, queue, previews, coverages, pages_by_filter, secret=..., evidence_ids=..., limit=...)`

`verify_cross_page_review_bundle(receipt, matrix, queue, previews, coverages, pages_by_filter, secret=..., evidence_ids=..., limit=...)`

The result is one domain-separated SHA256/HMAC-sealed JSON receipt with:

- `selected_evidence_ids` (strict canonical sorted selection), `selected_count`, `source_page_count`.
- `parent_matrix_sha256`, `all_filter_coverage_sha256`, `parent_queue_sha256`, and all signed source packet digests.
- `selected_rows`: per-Evidence exact matched filters, reason codes, observed/selected flags, signed page and handoff hash.
- `page_handoffs`: nested **complete v0.10.6 signed page handoffs**, including exact per-capture citation metadata and explicit stale/historical source states. No separate uploads of raw text or researcher notes.
- Explicit `DRAFT_NO_HUMAN_DECISION` and `HOLD` flags, with all approval, license, immutable snapshot and user-authorization booleans false.

When an Evidence has been removed from the latest capture, the earlier observed source is **historical**, not a current citation. This is metadata-only triage, never an archival/rights/approval decision.

## Private CLI

Use the same `--packet`, `--queue`, `--coverage FILTER=PATH` and `--page FILTER=PATH` parameters from the v0.10.8 matrix CLI. Add the existing signed matrix and the desired selection. All six filter receipts and *every* corresponding signed page are mandatory, even when the selected Evidence only appear under one filter. The page size must equal that of the original receipts.

```sh
python scripts/study_review_bundle_v0109.py build \
  --queue /private/queue.json \
  --matrix /private/triage-matrix.json \
  --packet /private/capture-1.json \
  --packet /private/capture-2.json \
  --coverage all=/private/coverage-all.json \
  --coverage source_or_review=/private/coverage-source.json \
  --coverage membership=/private/coverage-membership.json \
  --coverage selection=/private/coverage-selection.json \
  --coverage other_metadata=/private/coverage-other.json \
  --coverage returned_state=/private/coverage-returned.json \
  --page all=/private/page-all-1.json \
  --page all=/private/page-all-2.json \
  --page source_or_review=/private/page-source.json \
  --page membership=/private/page-membership.json \
  --page selection=/private/page-selection.json \
  --page other_metadata=/private/page-other.json \
  --page returned_state=/private/page-returned.json \
  --ids 'evidence:first-canonical-id,evidence:last-canonical-id' \
  --limit 10 \
  --token-path /private/research-api-token \
  --output /private/cross-page-review.json
```

The example paths are placeholders; replace them with all your **actual** signed pages (including additional pages beyond the two shown for `all`, if any). IDs must be canonical and lexicographically sorted. Use `verify` instead of `build` with all the same source arguments, replacing `--output` with `--report /private/cross-page-review.json`. Inputs are owner-only, output is create-once owner-only (0600) and cannot overwrite an existing file. No token or private Evidence IDs are logged.

## Research and security HOLD

Neo remains read-only: no user/workspace authorization, DvirOS BFF/Postgres persistent research notes, human decision or approval log, licensed edition validation, graph-snapshot immutability or trusted timestamp is implemented. Source metadata and observed review states cannot be promoted to approved scholarly interpretation, legal right or causal influence. The API and CLI are strictly offline; never call an external LLM or provider.

This is stacked on v0.10.8 Draft PR #64. All upstream draft and research/security release gates remain; **do not merge to main** until they are cleared.

Contract: `docs/integrations/RESEARCH-REVIEW-BUNDLE-v0.10.9.json`.

Focused tests: `python -m unittest tests.test_study_review_bundle_v0109 -v`.
