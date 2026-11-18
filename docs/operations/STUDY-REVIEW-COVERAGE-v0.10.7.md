# v0.10.7 — Signed complete review inbox coverage (Neo-only, DRAFT)

## Why

A signed v0.10.5 page proves the contents of **one page**, not that all eligible review candidates were handed off. v0.10.7 takes a **complete ordered keyset walk** of authenticated pages and produces one independently verifiable SHA256/HMAC receipt for the **exact selected filter and page size**. It contains operational metadata, not source text, researcher notes, reviewer decisions or license approvals.

## Input constraints

- **2–6** complete, signed v0.10.0 source preview packets in the same capture order used to build the parent queue.
- One independently authenticated v0.10.4 review queue.
- **1–600** v0.10.5 signed pages in complete cursor sequence, beginning without a cursor and ending when `has_more=false`.
- Exact `--filter` (one of `all`, `source_or_review`, `membership`, `selection`, `other_metadata`, `returned_state`) and `--limit` (1–20) from the original page creation.
- All input and protected service-token files must satisfy the existing owner-only private I/O rules. An empty filtered view requires **one signed empty terminal page**.

## Example

The example uses synthetic placeholder filenames. Generate each v0.10.5 page first, passing its `next_cursor` into the next request. The final page has no next cursor.

```sh
python scripts/study_review_coverage_v0107.py build \
  --packet /private/capture-1.json \
  --packet /private/capture-2.json \
  --queue /private/queue.json \
  --page /private/page-1.json \
  --page /private/page-2.json \
  --filter all --limit 10 \
  --token-path /private/research-api-token \
  --output /private/inbox-coverage.json

python scripts/study_review_coverage_v0107.py verify \
  --packet /private/capture-1.json \
  --packet /private/capture-2.json \
  --queue /private/queue.json \
  --page /private/page-1.json \
  --page /private/page-2.json \
  --filter all --limit 10 \
  --token-path /private/research-api-token \
  --report /private/inbox-coverage.json
```

The CLI creates private output exactly once and refuses overwrites. It prints only bounded verification fields; private source packets, notes, token and citations are never printed.

## What is guaranteed

The original signed captures, deterministic candidate queue and **each** signed page are independently recomputed. The verifier fails closed on missing or reordered pages, duplicate candidates, an extra page after the terminal page, cursor/filter/page-size mismatch, forged decisions, wrong token, altered HMAC or weakly protected files. A receipt records the queue SHA256, capture packet SHA256s, exact page SHA256s, Evidence IDs, page counts, filtered population and **first/terminal cursor `null`**. This is a filtered-inbox completeness statement only; different filters are different signed views.

## What is not guaranteed

No external user identity, workspace authorization, DvirOS BFF/Postgres review history, human approval, source edition rights validation, trusted timestamp, live Neo4j snapshot or graph writes are provided. No research claims may be published on the strength of this receipt. Upstream draft PRs and human scholarly/security review block main merge and production release.

Integration schema: `docs/integrations/RESEARCH-REVIEW-COVERAGE-v0.10.7.json`.

Focused test: `python -m unittest tests.test_study_review_coverage_v0107 -v`. Other production checks remain separate.
