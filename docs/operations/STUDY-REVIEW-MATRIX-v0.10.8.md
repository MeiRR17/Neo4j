# v0.10.8 — Signed cross-filter Evidence review matrix (Neo-only, DRAFT)

## Purpose

A v0.10.7 HMAC receipt proves a **single filtered** v0.10.5 queue view was traversed completely. Six independent views can overlap. v0.10.8 verifies **all six complete source-backed views** and produces an auditable per-Evidence membership matrix, without silently treating overlapping reason families as disjoint counts or human-approved research findings.

The six mandatory filters are `all`, `source_or_review`, `membership`, `selection`, `other_metadata`, and `returned_state`. Empty filters still require exactly one signed empty v0.10.5 terminal page and corresponding v0.10.7 coverage receipt.

## Integrity and logic

1. Revalidate all 2–6 original v0.10.0 private signed study previews and deterministic v0.10.4 Evidence queue.
2. Independently replay **each** v0.10.7 full-view coverage receipt against all its original signed v0.10.5 pages, with exactly the selected queue, filter and `--limit`.
3. Independently derive each expected filter-membership set from the signed review queue's exact reason codes and intermediate-return flag. Reject any count/set disagreement with the signed complete view, including an omitted or swapped view.
4. Emit one sorted per-Evidence row with exact matched filter names, reason codes, current observed/selected flags, and an explicit count of overlapping **specific** (non-`all`) filters.
5. SHA256/HMAC-sign a bounded metadata-only matrix tying the original queue digest, source packet digests, all six v0.10.7 coverage hashes, exact filter counts and candidate membership matrix. The receipt itself and all six input views can be replayed independently.

This is an **operational review routing view**, not a scholarly severity score, rights grant, graph snapshot, decision or approval. It never writes to Neo4j or DvirOS. The source queue can contain observations not selected by the researcher; this is deliberate.

## Private offline CLI

The operator must already have a complete set of v0.10.7 coverage receipts and their exact original v0.10.5 page sequences. The following command uses placeholders: `--coverage` occurs once per filter; `--page` repeats in cursor order within each filter. Supply **all six filters**, including signed empty views. Files must be owner-only private inputs. Example for just one filter's arguments (repeat corresponding arguments for the other five):

```sh
python scripts/study_review_matrix_v0108.py build \
  --packet /private/capture-1.json --packet /private/capture-2.json \
  --queue /private/queue.json --limit 10 \
  --coverage all=/private/coverage-all.json \
  --page all=/private/page-all-1.json \
  --page all=/private/page-all-2.json \
  --coverage source_or_review=/private/coverage-source-or-review.json \
  --page source_or_review=/private/page-source-or-review.json \
  # ... provide coverage and page inputs for the other four required filters ... \
  --output /private/six-filter-matrix.json
```

The abbreviated command above intentionally omits four filters; **it will not succeed as shown**. Use `verify` in place of `build` with all the same source arguments plus `--report /private/six-filter-matrix.json`. `build` requires `--output` and fails rather than overwrite an existing path. CLI prints only an aggregate verification summary, never the token, source metadata or selected Evidence IDs.

## Security and release boundaries

Every row sets `human_review_approved=false`, and the report sets `human_review_decisions_recorded=false`, `licensed_source_rights_verified=false`, `immutable_graph_snapshot_verified=false`, `dviros_workspace_authorization_verified=false` and `research_release_status=HOLD`. DvirOS still needs its own authenticated BFF, owner/workspace RBAC, Postgres revisions, genuine human review, source/edition licensing, graph revision governance and external verification. No cross-repository changes are made here.

**Do not merge to main** while the upstream stacked Draft chain, v0.9.6 synthetic cost gate, research release and security prerequisites are unapproved.

Contract: `docs/integrations/RESEARCH-REVIEW-MATRIX-v0.10.8.json`.

Focused unit tests (subject to project dependencies):
```sh
python -m unittest tests.test_study_review_matrix_v0108 -v
```
