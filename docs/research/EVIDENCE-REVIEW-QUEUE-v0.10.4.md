# v0.10.4 — Evidence review candidates from signed study history

This Neo-only increment turns the complete **2–6 capture** signed study
observation timeline into a deterministic, evidence-by-evidence *review
candidate queue*. It groups changes that a human reviewer may need to
investigate, not human decisions or automatic source approvals.

Unlike a last-vs-first comparison, the queue retains each observed
transition (including **A → B → A** row-state returns). It exposes
**selection-only changes** even when the audit rows are unchanged, and
**unselected audit-window changes** that were not among the 1–12 study
citations. Each candidate has the original canonical Evidence ID, indices
of the affected captures, changed metadata **field names**, selection and
observation flags and reason codes; it contains no source text, notes or
reviewer identity.

## Local offline invocation

Keep each complete v0.10.0 packet and the token in owner-only private
files. The order of repeated `--packet` arguments is significant:

```sh
python scripts/study_review_queue_v0104.py build \
  --packet /private/observation-1.json \
  --packet /private/observation-2.json \
  --packet /private/observation-3.json \
  --token-path /private/research-token \
  --output /private/review-queue.json

python scripts/study_review_queue_v0104.py verify \
  --packet /private/observation-1.json \
  --packet /private/observation-2.json \
  --packet /private/observation-3.json \
  --token-path /private/research-token \
  --report /private/review-queue.json
```

The verifier **recomputes** the signed timeline, each bounded v0.10.2
comparison and every candidate from the complete original source packets.
The output is domain-separated HMAC/SHA-256 sealed, private create-only
and bounded to 240 KiB canonical metadata (250 KiB file size). If the
budget is exceeded, the operation fails closed rather than truncating
evidence or dropping changes.

## Interpreting the queue

- `review_status=PENDING_HUMAN_TRIAGE` is a suggestion for follow-up,
  not a verified human decision or authorization.
- `unselected_window_drift` marks evidence whose observed metadata
  changed while it was absent from both neighboring study selections.
- `returned_to_prior_observed_state` means the **exact bounded row
  metadata** returned to a previously observed fingerprint after an
  intervening observation; it does not establish real-world restoration.
- No queue items means no observed row/selection changes in this
  **particular bounded observation sequence**, not global corpus stability.
- Row addition or removal reflects the directed Work-pair audit-window
  observations only. It is not evidence of graph deletion or publication.
- Reported capture times are **not independently trusted** timestamps.
  A local HMAC only establishes knowledge of the protected local key.

Actual DvirOS user/workspace authorization, saved-study CRUD, reviewer
decisions, attribution/license clearance and research sign-off remain
**outside Neo**, not implemented here. Research release stays **HOLD**.
See `docs/integrations/DVIROS-EVIDENCE-REVIEW-QUEUE-v0.10.4.json`.
