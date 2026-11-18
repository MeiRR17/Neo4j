# v0.11.2 — Grounded Evidence Dossier (metadata-only, DRAFT)

## Purpose

Create a **human-review-ready metadata dossier** from exactly selected Evidence
anchors returned by the default-off v0.11.1 cross-Passage grounded comparison.
This closes the gap between exploratory reference matching and a reproducible
manual review handoff, without model-written answers or licensing assertions.

The endpoint verifies **2–3 canonical Passage IDs**, the same v0.11.0 bounded
source-reference query and **1–8 sorted, unique canonical Evidence IDs**.
It replays the v0.11.1 comparison at its 12-context ceiling, refuses selected
IDs absent from that window and packages original Evidence/Edge/Passage IDs,
source references, version IDs, rights *tags*, recorded review-status labels,
observed focus-Passage memberships and triage warnings. There are at most
three fixed read-only graph queries per call and at most 20 observed links
per focus Passage. All IDs are source metadata, not confirmed citations.

## Private API (feature OFF by default)

```http
GET /v1/research/grounded-context/dossier?passage_ids=passage:ID1,passage:ID2&query=reference&evidence_ids=evidence:ID1
Authorization: Bearer <private-service-token>
```

Remove the illustrative space before `evidence_ids` in a real URL and
URL-encode the query. The example identifiers are placeholders. The endpoint
shares `DVIROS_ENABLE_GROUNDED_CONTEXT=1` with the v0.11.0 and v0.11.1
preview APIs. Without explicit private operator opt-in, it returns HTTP 404
without graph reads. Invalid flag values return 503; missing authentication
returns 401. Unknown/duplicate query fields, out-of-order or duplicate IDs,
out-of-range limits and invalid scopes fail closed with 422.

## Receipt and trust boundaries

The output has `dossier`, `dossier_sha256` and
`dossier_digitally_signed=false`. The digest is SHA256 of the existing
canonical metadata JSON encoding, useful for **local change detection**.
It is **not a digital signature**, source authenticity attestation or
adversary-proof approval. The query text itself is represented only by a
`query_sha256` fingerprint. Provider source metadata is never treated as
instructions.

`verify_grounded_evidence_dossier` recomputes the dossier from *current*
bounded graph reads and rejects changed input metadata or a changed receipt.
Multiple graph reads are not a transaction or immutable corpus snapshot.
Changing the source between reads may fail, and results cannot establish
which historical graph state was canonical.

Every selected item has `human_review_approved=false`,
`source_rights_independently_verified=false`, and
`quote_verified_against_edition=false`. Every dossier has
`generated_claim=null`, `human_approval_recorded=false`,
`source_text_available=false`, `graph_snapshot_verified=false`,
`corpus_completeness_verified=false`, `research_release_status=HOLD`.
A recorded graph status of `approved` is still only an unverified metadata
label for this separate research task. An empty or out-of-window selection
will not produce fabricated citations.

## Remaining requirements

DvirOS user/workspace identity, permission checks and persistent human review
history; independent source/edition rights confirmation; quote verification;
snapshot identity; robust bilingual retrieval evaluation; live provider/LLM
policy and security release approval remain **unimplemented**. This is
Neo-only code, not a cross-repo integration or production release.
Keep PRs stacked in Draft and do not merge to main until upstream and
scholarly/security release gates are met.

Focused test: `python -m unittest tests.test_grounded_dossier_v0112 -v`.
JSON contract: `docs/integrations/GROUNDED-DOSSIER-v0.11.2.json`.
