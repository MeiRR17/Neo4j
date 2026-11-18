# Neo v0.10.3 — Signed multi-capture study timeline

A researcher may revisit the same directed Work-pair study over time. The
v0.10.1 and v0.10.2 tools compare exactly two signed source observations.
This Neo-only increment accepts **2–6 individually verified v0.10.0 study
preview envelopes**, orders them by strictly increasing *locally reported*
capture timestamps, computes a v0.10.2 full bounded audit-window diff at
each transition and builds an HMAC-sealed hash-chained timeline.

It can detect **A → B → A**: intermediate changes that would be invisible
if a consumer compared only the first and final observed metadata rows.

## Private offline workflow

Both input packets and the service token must be local, owner-readable
private files. Retain the complete original packets to allow replay.

```sh
python scripts/study_timeline_v0103.py build \
  --packet /private/study-01.json \
  --packet /private/study-02.json \
  --packet /private/study-03.json \
  --token-path /private/research-token \
  --output /private/study-timeline.json

python scripts/study_timeline_v0103.py verify \
  --packet /private/study-01.json \
  --packet /private/study-02.json \
  --packet /private/study-03.json \
  --token-path /private/research-token \
  --report /private/study-timeline.json
```

The packet order is significant. Out-of-order or duplicate local timestamps,
changed directed Work scope, invalid HMAC, forged report flags and attempts
to overwrite existing output are refused. The saved file is owner-only,
create-only and limited to 250 KB.

## Reading the result

Each snapshot records the exact source packet and audit SHA-256, observed
Evidence row count, citation selection count, reported time and hash of the
ordered audit metadata rows. Each transition includes the ordered per-row
v0.10.2 changes, selected/unselected scope, source packet and audit-diff
hashes, and a chained SHA-256 digest. The final report records total change
events and distinct changed Evidence IDs. A revisit records an index
returning to earlier *observed metadata row contents* after an intermediate
change. It is **not** a proof of source deletion or restoration.

## Strict security and epistemic boundary

- Only the same Work pair's two-pass signed audit observations are examined
  (at most 100 Evidence rows in each capture). No full graph/corpus snapshot.
- Timestamps are locally reported by each packet's original service clock,
  **not independently trusted**. Replayed monotonic times do not establish
  continuous retention or immutability.
- HMAC authenticates possession of the local protected service token; it
  is not an independent scholar's approval or archival timestamp.
- Does not retrieve/publish full source text, accept human accounts, save
  researcher notes, write Neo4j, or use cloud/network services.
- DvirOS BFF, authorization, Postgres saved-study revision history and
  independent scholarly/rights approvals remain outside this repository.
  Keep the stacked PR **DRAFT** and research release **HOLD**.

Machine contract: `docs/integrations/DVIROS-STUDY-TIMELINE-v0.10.3.json`.
