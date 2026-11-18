# v0.10.6 — Private signed Evidence review handoff (Neo-only, DRAFT)

This offline-only handoff chooses **1–12 sorted unique canonical Evidence IDs on one exact v0.10.5 signed inbox page**. It independently verifies every original v0.10.0 preview packet, the signed v0.10.4 queue and the v0.10.5 page before producing a domain-separated SHA256/HMAC receipt. The output is a **draft transfer artifact**, not a reviewer decision, license or database write.

## Offline usage

The `--packet` options must be supplied in capture order (2–6 packets). All inputs and the protected local API token must be private owner-only files. The default filter is `all`, limit 10, and cursor absent; when selecting from another page, pass the **same** filter, limit and cursor used to generate that page.

```sh
python scripts/study_review_handoff_v0106.py build \
  --packet /private/study-1.json --packet /private/study-2.json \
  --queue /private/review-queue.json \
  --page /private/review-page.json \
  --ids 'evidence:canonical-id' \
  --token-path /private/research-api-token \
  --output /private/review-handoff.json

python scripts/study_review_handoff_v0106.py verify \
  --packet /private/study-1.json --packet /private/study-2.json \
  --queue /private/review-queue.json \
  --page /private/review-page.json \
  --ids 'evidence:canonical-id' \
  --token-path /private/research-api-token \
  --report /private/review-handoff.json
```

The output is create-once; existing files, weakly protected input and unsafe paths are refused by the existing private I/O helpers. No secret or private metadata is printed to stdout; only a bounded verification summary is emitted.

## Per-capture observation history

Each handoff item includes the source `reason_codes`, `events`, latest selected/observed status, and `observation_history` covering **every** signed capture. Each history entry has:

- `capture_index`: zero-based order of the supplied capture.
- `packet_sha256`: exact authenticated source preview packet.
- `observed_in_audit`: whether the Evidence was present in that capture's bounded Work-pair audit.
- `selected_in_study`: whether the researcher had selected it in that preview.
- `citation_metadata`: exact allowlisted `CITATION_FIELDS` when observed, otherwise `null`. It never contains raw text or researcher notes.

The separate `last_observed_citation_metadata` and `source_metadata_is_current_observation` prevent an Evidence removed from the latest capture from being presented as a current link. An Evidence selected in one preview may remain observed after it is deselected; the two flags must not be conflated.

## Consumer contract and boundaries

See `docs/integrations/RESEARCH-REVIEW-HANDOFF-v0.10.6.json`. DvirOS must authenticate the human, authorize the workspace and write its own Postgres review records and immutable decision history; **none of that exists here**. Do not interpret `PENDING_HUMAN_TRIAGE`, `DRAFT_NO_HUMAN_DECISION` or observed review-status metadata as an approved interpretation. Source rights and source edition authenticity require independent validation. Capture times are local reports; two-pass audit is not an immutable graph snapshot. Do not merge this stacked draft chain into `main` until the upstream security, scholarly and integration gates pass.

Focused checks: `python -m unittest tests.test_study_review_handoff_v0106 -v` (with project test dependencies installed). No live Neo4j or DvirOS calls are required for this offline step.
