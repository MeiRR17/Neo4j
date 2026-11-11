# v0.8.7 — frozen search-quality evaluation contract (DRAFT)

This is an **offline evaluator**, not search relevance proof or a production
feature switch. It is explicitly constrained to versioned, frozen judgments
and captured, authenticated read-only API responses. It does not call Neo4j,
the public internet, AI, a reviewer, or source-content APIs.

## Run (synthetic, no human-research claim)

\`\`\`sh
python scripts/search_quality_eval.py \
  --judgments tests/fixtures/search_quality_judgments_synthetic.json \
  --responses tests/fixtures/search_quality_responses_synthetic.json
\`\`\`

The fixture contains **two entirely synthetic** Hebrew/English questions,
five invented work IDs judged per case, and captured metadata-only responses
using schema v0.8.2 and v0.8.3 respectively. It is a deterministic unit-test
of the harness, not a scholarly pilot or a real 50-question gold set.

## Input schema and meaning

Judgments are a UTF-8 JSON file (max 512 KB) with exactly:

\`\`\`json
{
  "schema_version": "0.8.7",
  "dataset_kind": "synthetic",
  "queries": [
    {
      "id": "q-example-001", "kind": "works",
      "query": "synthetic topic", "language": "",
      "judgments": [
        {"id": "work:<64 lowercase hex>", "relevance": 1,
         "reviewer_id": "SYNTHETIC_FIXTURE", "evidence_ref": "SYNTHETIC:NOTE"}
      ]
    }
  ]
}
\`\`\`

Five or more unique, explicitly judged canonical IDs are required **per
question**. Relevance is 0 or 1, not a model-generated estimate. This
one-row illustration is not sufficient by itself; inspect the full fixture.

The response capture has \`schema_version: "0.8.7"\` and a \`responses\` array,
one record per question ID. Each record contains \`id\` and \`pages\`: ordered
captured server response pages retaining actual \`schema_version\`,
\`kind\`, \`items\`, \`has_more\`, \`search_complete\` and \`next_cursor\`
fields. Both bounded scan (v0.8.2) and indexed prefix (v0.8.3) must be
identified accurately. A capture process must fetch **all pages**, stop
only when \`search_complete=true\`, and keep the service's original order.
This code does not claim that canonical-ID or prefix order is ranked by
relevance, and it does not certify the capture's authenticity.

## Evaluation invariants

- Every query/capture ID must be unique, every result ID canonical and
  kind-matched, and every page within a question use one API schema.
- Search completeness must be explicit. Incomplete cursor chains produce
  **no scored Precision@5**, not assumed zeros or false success.
- All observed top-five IDs require explicit reviewer relevance labels.
  An unknown hit is not silently treated as irrelevant.
- Works and passages need non-null precise source anchors; missing anchors
  make the question ineligible for scoring.
- Raw text, excerpts, rights promotion and duplicate results are refused.
  No titles, query text, document IDs or original sources appear in the
  printed report. Original JSON bytes are hashed for later comparison.
- Precision@5 is number of explicitly judged relevant hits in first five
  divided by **five** (including vacant positions). The summary mean is
  computed over eligible questions only and labeled accordingly.
- The 50-question target is never met by CI's two-question synthetic
  dataset. Even a self-declared \`human_reviewed\` dataset with mean >=0.80
  is **not** independent reviewer verification or deployment approval.

The report permanently carries \`external_human_review_verified=false\` and
\`production_release_status=HOLD\` until a separate governed release workflow
and reviewed evidence exist. The optional \`--require-quality-target\` can
reject an unqualified data snapshot, **not** authorize production.

## Remaining v0.8 acceptance gates

Establish and freeze 50 **real** Jewish-philosophy research questions, capture
licensed/rights-vetted canonical identifiers and source anchors, recruit
independent human domain reviewers, adjudicate relevance disagreements and
freeze responses at known corpus/index versions. Audit both language
subgroups, missing-document failures and incomplete paging. Publish
performance and quality results only after independent review; DvirOS
SSO/RBAC and manuscript/edition rights gates remain pending.
