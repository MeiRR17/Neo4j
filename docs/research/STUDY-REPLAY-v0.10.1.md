# v0.10.1 — Signed study preview replay comparison (Neo-only)

This increment adds a **read-only, offline** integrity-sealed comparison of
two v0.10.0 study citation preview envelopes. It supports a future DvirOS
saved-study re-open workflow by reporting exactly which selected Evidence
citations were added, removed, or had any reference/edition/review field
changed. A change in selected citations is *not* evidence that the graph
deleted a source; the graph is not frozen.

## Local operator flow

1. Obtain **two independently signed, complete** v0.10.0 preview JSON
   envelopes from the authenticated Neo service, preserving both with
   owner-only permissions. Never commit real research exports.
2. Compare them offline, with the protected local service token:

```sh
python scripts/compare_study_packets_v0101.py compare \
  --baseline /private/study-before.json \
  --current /private/study-after.json \
  --token-path /private/research-token \
  --output /private/study-diff.json
```

3. Independently reverify the receipt with the **same two original** inputs:

```sh
python scripts/compare_study_packets_v0101.py verify \
  --baseline /private/study-before.json \
  --current /private/study-after.json \
  --token-path /private/research-token \
  --report /private/study-diff.json
```

The output contains canonical IDs, SHA-256 bindings, added/removed Evidence
IDs and explicit changed metadata field names. It does **not** contain private
notes, researcher IDs, full source text or user approval. Output is private
create-only and will not overwrite an existing file. Both inputs must be
private regular files, non-symlinks, and individually verifiable. The current
capture must not report an earlier time than the baseline; this is only a
local-observation check, **not a trusted timestamp proof**.

## Trust and ownership

- Neo4j remains read-only. No Postgres study, DvirOS user/workspace,
  authorization record or review decision is created here.
- The comparator does not compare entire graph revisions. A zero-change
  result means only that the **selected citation metadata** agrees between
  the two verified signed preview envelopes; changes outside the selection,
  aliases and unobserved edges can still exist.
- BFF user/workspace authorization, Postgres persistence, immutable reviewer
  decision history, rights checks, versioned saved studies and UI are
  **DvirOS-owned future work**. Do not merge blocked stacked PRs or claim a
  production scholarly release based solely on this result.

See `docs/integrations/DVIROS-STUDY-REPLAY-v0.10.1.json` for the machine
contract. Research release status remains **HOLD**.
