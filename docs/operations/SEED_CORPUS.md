# v0.4 — scholarly seed corpus, licenses and human research review

**Engineering baseline implemented; scholarly/rights release gates remain human-blocked.**
The candidate catalog is not proof an index exists, a translation is licensed,
a quotation is correct or a historical-influence claim is true.

This release adds a **reviewable metadata corpus** to the DvirOS Neo4j research
service. It does not fetch or redistribute book text, does not run AI
classification, and does not create any user-facing app. The unrelated
Learning_Modules copy is untouched.

## Why each edition needs a separate decision

Sefaria associates a different license with each **version/edition** of
a work. The original work's antiquity does not prove a modern translation's
text is public domain. Never assume that its appearance on Sefaria authorizes
redistribution. Supported metadata-license names requiring human confirmation:
`Public Domain`, `CC0`, `CC-BY`, `CC-BY-SA`, `CC-BY-NC`.
Missing, unfamiliar or changed terms block automatic approval.
For CC-BY-NC, the human decision must record a noncommercial context.
Attribution, donor notes and rights evidence should be checked manually.

Sources:
- https://developers.sefaria.org/reference/get-versions
- https://help.sefaria.org/hc/en-us/articles/18490043237148-How-to-Find-and-Understand-Licensing-or-Copyright-Information
- https://github.com/Sefaria/Sefaria-Export/blob/master/LICENSE.md

## Step 1 — candidate inventory, not a generated fact

`config/philosophy-seed-candidates.json` contains 18 **candidates** across
philosophy, ethics, thought and mysticism. Titles are speculative exact index
identifiers until Sefaria confirms them. Some may be unavailable or have
different official names: the tool reports them as unresolved, never quietly
substitutes another work.

Read the [catalog](../../config/philosophy-seed-candidates.json). For a
network-opted-in run:

```bash
python scripts/seed_corpus.py discover --live \
  --output private_research/versions/seed-inventory.json
```

Only `GET https://www.sefaria.org/api/texts/versions/{index}` is used,
with a strict host/path, 2 MB response cap, no redirect, bounded retries,
and a small delay between candidate works. It does NOT fetch text endpoints.
Keep the raw version response snapshots or their independently verifiable
checksums on your private research host. Do not commit live inventory or
personal human reviews to a public repository by default.

Offline replay from a local mapping of index title to API version objects:

```bash
python scripts/seed_corpus.py discover \
  --offline-snapshots private_research/versions/version-response-map.json \
  --output private_research/versions/seed-inventory.json
```

Inventory records source version URL and exact payload hash. It does **not**
set permissions, `verified_edition_count` remains zero and
`allowed_text_redistribution` always remains false.

## Step 2 — human rights decisions, separate from discovery

Create an owner-controlled `rights-decisions.jsonl`, one explicit decision
per actual edition ID, with all of the following fields (values shown are a
**schema example only**, not an authorized decision):

```json
{
  "edition_id": "<real edition ID from seed-inventory.json>",
  "inventory_sha256": "<SHA-256 computed over canonical inventory JSON>",
  "decision": "approve_metadata",
  "license_confirmed": "CC-BY",
  "intended_use": "research_metadata_only",
  "reviewer_id": "<real reviewer ID>",
  "reviewed_at": "<ISO-8601 with timezone>",
  "rationale": "<at least 24 characters explaining the terms checked>",
  "rights_evidence_uri": "https://www.sefaria.org/...",
  "attribution": "<verified edition attribution, at least 8 characters>",
  "use_context": "noncommercial"
}
```

One object per line, not an array. A decision may instead be `reject`
(with reviewer, timestamp and rationale); no automatic approval is possible.
Review decisions are tied to an exact inventory SHA and cannot be reused if
new source metadata is discovered. **CC-BY-NC approvals** require
`use_context=noncommercial`. `approve_metadata` is **never permission
to download or republish full book text**.

If you have separately verified edition metadata and want to upsert only
the catalog nodes:

```bash
python scripts/bootstrap.py
docker compose up -d --wait
python scripts/migrate.py check
python scripts/seed_corpus.py apply-editions \
  --inventory private_research/versions/seed-inventory.json \
  --rights private_research/rights-decisions.jsonl \
  --ack-reviewed-metadata-only
```

No text is stored. The resulting `:Edition` record has the reviewed raw
license, attribution, rights-review metadata, and evidence to the original
versions-list snapshot. Existing license conflicts are rejected, not silently
overwritten. This is a **local** operation, not a production deployment.

## Step 3 — scholarly review queue for observed links

First use v0.3's `ingest_sefaria.py plan-csv` to create an integrity-
checked, zero-quarantine link metadata plan. Then sample a deterministic
queue (120 by default, at least 100 required for release):

```bash
python scripts/seed_corpus.py review-queue \
  --stage private_research/staging/links-batch-001 \
  --output private_research/review/queue.json
```

Each item exposes original source reference, raw link category, right/left
full passage anchors and the Evidence ID. No automatic adjudication,
inference of direction or AI evidence promotion takes place.

In a separate `evidence-decisions.jsonl`, reviewers enter one JSON object
per reviewed item:

```json
{
  "evidence_id": "<an exact ID from queue.json>",
  "queue_sha256": "<SHA-256 over canonical queue JSON>",
  "decision": "uncertain",
  "reviewer_id": "<real reviewer ID>",
  "reviewed_at": "<ISO-8601 with timezone>",
  "rationale": "<at least 24 characters explaining source inspection>",
  "asserted_influence": false,
  "asserted_citation_direction": false
}
```

Other choices: `confirmed_observed_link`, `not_supported`.
Even a confirmed link is **not proof of direct citation, intellectual
dependence, chronology or agreement**. Reviewers check source anchors
rather than merely voting on graph structure.

## Step 4 — evidence and edition quality report

```bash
python scripts/seed_corpus.py audit \
  --inventory private_research/versions/seed-inventory.json \
  --rights private_research/rights-decisions.jsonl \
  --review-queue private_research/review/queue.json \
  --evidence-reviews private_research/review/evidence-decisions.jsonl \
  --stage private_research/staging/links-batch-001 \
  --output private_research/reports/v0.4-audit.json
```

Nonzero exit code 2 = scholarly readiness still blocked (not software test
failure). The report inspects 12–20 approved distinct works, at least
100 separate human adjudications, duplicate identities, missing passage
anchors, missing evidence and unresolved catalog/version mapping.
It reports separately that human identity was **not cryptographically
verified** and that manual release signoff is always required. No public
GA marker is emitted automatically.

### Current blockers

- Need real edition discovery and individual rights reviews for 12–20 works.
- Need 100+ *actual* manually inspected source-link examples.
- Need to resolve missing upstream index names and malformed version responses.
- Need an independent scholarly/rights signoff and a reviewed attribution
  manifest before publishing licensed source material.
- v0.4 stores edition/link metadata, not full source texts. The read-only
  DvirOS Research API is planned for v0.5. No new text-rights grant is inferred.

## Safety and rollback

The CI integration uses **invented synthetic versions and simulated
approvals, explicitly marked as fixtures**. This never counts toward real
review readiness. Operational metadata may be backed up and independently
restored, but broad graph cleanup is prohibited. The current network
boundary remains localhost-only and security checks are unchanged.
