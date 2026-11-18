# v0.10.5 — Signed, filtered review-candidate pages

A v0.10.4 queue can contain many independent Evidence candidates. This
Neo-only increment introduces bounded, **deterministically ordered**
pages of up to 20 candidates for a future authenticated DvirOS inbox.
It does not create a DvirOS UI, accept reviewer decisions, or connect
to Neo4j: both the original signed queue and all original v0.10.0
private packets are verified afresh for every page.

Reason filters: `all`, `source_or_review`, `membership`,
`selection`, `other_metadata`, `returned_state`.

The default display order places source/review changes first, observed
membership next, selection changes next, then other metadata changes.
**This is an operational display preference, not a measure of research
importance, safety or scholarly certainty.** Within each group the
canonical Evidence ID is the stable key.

## Offline operator usage

Prepare the owner-only v0.10.4 queue JSON and 2–6 complete signed
v0.10.0 packet files, in the original capture order.

```sh
python scripts/study_review_pages_v0105.py page \
  --queue /private/review-queue.json \
  --packet /private/capture-1.json \
  --packet /private/capture-2.json \
  --token-path /private/research-token \
  --filter source_or_review --limit 10 \
  --output /private/review-page-1.json
```

The result printed to the terminal contains `next_cursor`. If
`has_more=true`, repeat the command using the same `--filter`,
`--limit` and queue, adding `--cursor '<next_cursor>'` and a **new**
output path. Omit `--cursor` for page one.

Independently replay a saved page with the exact same inputs and
pagination parameters:

```sh
python scripts/study_review_pages_v0105.py verify \
  --queue /private/review-queue.json \
  --packet /private/capture-1.json \
  --packet /private/capture-2.json \
  --token-path /private/research-token \
  --filter source_or_review --limit 10 \
  --report /private/review-page-1.json
```

For later pages, supply the precise cursor used to generate that page
to the `verify` command. A cursor is bound to the exact queue digest,
filter and page limit and cannot be silently reused across scopes.
Incorrect HMAC, corrupted source packet, duplicate or forged field,
unsafe output, invalid limit or cursor are refused without truncation.

The output remains **HOLD**, even for an empty page. No DvirOS user
authentication or workspace access decision is performed here;
the consumer must independently authenticate, authorize, retain original
packets and record any human review decision in DvirOS Postgres.
These are only metadata candidates from bounded observed audit windows,
not proof of corpus immutability, licensed sources or influence.

See `docs/integrations/DVIROS-REVIEW-PAGES-v0.10.5.json`.
