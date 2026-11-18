# v0.11.3 — Offline grounded Evidence dossier comparison (DRAFT)

## What changed

A v0.11.2 grounded Evidence dossier captures the **selected metadata subset**
for one bounded 2–3 Passage search, but an operator comparing two such
dossiers had to inspect raw JSON. v0.11.3 adds an offline, create-once
`build/verify` command and deterministic change report. It distinguishes:

- **Newly selected** Evidence: present in the later dossier, not the earlier.
- **Deselected** Evidence: present earlier, absent later. This does **not**
  mean the Evidence was removed from Neo4j, that a citation ceased to exist,
  or that it became unlicensed.
- **Metadata-changed** Evidence: selected in both, but an exact allowlisted
  provenance field changed. Output includes `field`, `before`, `after`
  for Edge/Passage ID, source reference, observed focus membership, version,
  rights tag, review status, lexical match basis, triage flags or completeness.
- **Unchanged** Evidence: selected in both with identical listed fields.

Each change carries bounded human-triage warnings, including
`ANCHOR_ID_CHANGED`, `SOURCE_REFERENCE_CHANGED`,
`VERSION_METADATA_CHANGED`, `RIGHTS_METADATA_CHANGED`,
`REVIEW_STATUS_CHANGED`, `OBSERVED_FOCUS_CHANGED`,
`TRIAGE_FLAGS_CHANGED` and `METADATA_COMPLETENESS_CHANGED`.

## Strict input scope and checks

Both inputs must be exact typed v0.11.2 metadata-only envelopes, with
a valid independently recomputed `dossier_sha256`, strictly sorted/unique
Evidence IDs, coherent counts, matching observation windows and no
source-text/approval fields. The `passage_ids`, `query_sha256` and
selection-scope marker must match across both inputs. Cross-query or
cross-Passage comparison is rejected rather than conflated.

**Important:** v0.11.2 SHA256 is **not an HMAC or signature**. A malicious
actor can replace the dossier *and* its checksum. This tool verifies shape,
self-consistency and exact replay of the two supplied files, not their
original authorship, capture time, licensed source authenticity or graph
snapshot. It never calls Neo4j or any LLM. No saved human review is created.

## Private CLI

Create two private `0600` JSON files containing the exact v0.11.2
dossier envelopes for the same query and Passage scope, with different file
paths. Run locally:

```sh
python scripts/grounded_dossier_diff_v0113.py build \
  --before /private/dossier-before.json \
  --after /private/dossier-after.json \
  --output /private/dossier-diff.json

python scripts/grounded_dossier_diff_v0113.py verify \
  --before /private/dossier-before.json \
  --after /private/dossier-after.json \
  --report /private/dossier-diff.json
```

The CLI uses the existing owner-only JSON reader (rejects symlinks, weak
permissions, duplicate JSON object fields and oversized input) and
create-once owner-only writer (rejects overwrite). Only aggregate
verification counts are logged, not Evidence IDs, source references,
query text, tokens or researcher notes.

The result is `comparison`, `comparison_sha256`,
`comparison_digitally_signed=false`; all human approval, rights,
immutable graph and independent source-validation fields remain **false**
with `research_release_status=HOLD`. A changed Rights *tag* is only a
metadata warning, not a legal ruling. Do not publish, quote or approve
research claims on the basis of this report.

## Operations, tests and remaining release blockers

The diff does not introduce a public API or alter the default-OFF
GraphRAG endpoints. No DvirOS RBAC, save/review service, licensed
edition-text attestation, corpus revisions, private signed receipts or
production security signoff exists in this increment. Upstream PRs
remain Draft/HOLD; **do not merge to main** until all release gates pass.

Focused check: `python -m unittest tests.test_grounded_dossier_diff_v0113 -v`.
Integration contract:
`docs/integrations/GROUNDED-DOSSIER-DIFF-v0.11.3.json`.
