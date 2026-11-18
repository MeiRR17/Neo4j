# Neo v0.10.2 — Signed full audit-window drift

v0.10.1 reports metadata differences for up to 12 **selected** Evidence citations.
This increment verifies the complete original v0.10.0 input packets and
compares **all Evidence rows present within each of their already-signed
v0.9.11 directed Work-pair audit windows** (at most 100 per window).

A change outside the study selection is reported separately, so a consumer
cannot interpret an unchanged selection as an unchanged audit window.
Added/removed records and per-field changes identify canonical Evidence IDs
and changed field *names*, not full text or private user notes.

## Offline usage

Both input JSON envelopes and the token must be protected local private files:

```sh
python scripts/compare_study_audit_window_v0102.py compare \
  --baseline /private/study-before.json \
  --current /private/study-after.json \
  --token-path /private/research-token \
  --output /private/audit-window-diff.json

python scripts/compare_study_audit_window_v0102.py verify \
  --baseline /private/study-before.json \
  --current /private/study-after.json \
  --token-path /private/research-token \
  --report /private/audit-window-diff.json
```

The command refuses invalid HMACs, changed Work direction, backwards *reported*
observation times, unsafely readable input and symlink/overwrite of output.
It writes a new owner-only metadata receipt, never a graph write.

## Interpretation and approval boundaries

- `window_metadata_changed=false` means only that the two independently
  signed bounded audit *row lists* agree, not that a database snapshot,
  whole corpus, provider authenticity or 24/7 archive protection is proven.
- `audit_receipt_changed=true` can indicate capture time differences only.
  Do not interpret that flag alone as a source-link or review-state change.
- `unselected_window_change_count` counts changes neither selected
  before nor after. Selected-only changes remain independently visible.
- DvirOS must separately establish workspace-level user authorization,
  store user notes in its own Postgres, and obtain qualified human review
  and licensing clearance. This implementation does **none** of those.
- The comparison covers metadata only; status changes do not constitute a
  human approval, and a source link does not prove historical influence.

See `docs/integrations/DVIROS-STUDY-AUDIT-WINDOW-v0.10.2.json`.
The Neo-only PR is stacked above the v0.10.1 draft and cannot be merged to
`main` while upstream research/security release blockers remain open.
