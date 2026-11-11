# v0.8.8 — Private dual-review work packets (DRAFT)

v0.8.7 can score a frozen set of existing labels but does not produce labels.
v0.8.8 adds a **local, offline** operational workflow that does not invent
labels or claim reviewer identities have been verified.

## Procedure

1. Obtain an **authorized, already-frozen** \`schema_version: "0.8.7"\`
   search response capture (for v0.8.2 scanner or v0.8.3 title-prefix API).
   Collection requires the existing DvirOS private auth boundary and is **not**
   automated by this version. Only metadata with approved handling rules can
   be supplied; copyrighted excerpts and source text are prohibited.
2. Prepare a non-public question catalog \`schema_version: "0.8.8"\` with
   \`dataset_kind\` \`synthetic\` or \`candidate_human\`, and a \`questions\`
   array: \`id\`, \`kind\`, \`query\`, \`language\`. IDs must match capture IDs
   exactly. The following commands use **synthetic fixtures only**.
3. Prepare a local packet and two independent *blank* human reviewer forms:

\`\`\`sh
umask 077
python scripts/search_review_workflow.py prepare \
  --questions tests/fixtures/search_review_questions_synthetic.json \
  --responses tests/fixtures/search_quality_responses_synthetic.json \
  --output /tmp/review_packet.json
python scripts/search_review_workflow.py template \
  --packet /tmp/review_packet.json --reviewer-id SYNTHETIC_A \
  --output /tmp/review_A.json
python scripts/search_review_workflow.py template \
  --packet /tmp/review_packet.json --reviewer-id SYNTHETIC_B \
  --output /tmp/review_B.json
\`\`\`

Templates contain each frozen top-five \`query_id\` + canonical \`id\`,
\`relevance: null\`, and \`evidence_ref: null\`. There is no machine-generated
label. Each reviewer must *independently* enter relevance 0/1 and a bounded
evidence reference for all rows; signed identity, scholarship credentials,
rights and quality of evidence are **not** established by CLI identifiers.
Store packet and forms only in authorized private locations.

4. After both reviewers fill the forms, freeze and audit:

\`\`\`sh
python scripts/search_review_workflow.py freeze \
  --packet /tmp/review_packet.json \
  --review-a /tmp/review_A.json --review-b /tmp/review_B.json \
  --output /tmp/frozen_judgments.json --audit /tmp/review_audit.json

python scripts/search_quality_eval.py \
  --judgments /tmp/frozen_judgments.json \
  --responses tests/fixtures/search_quality_responses_synthetic.json
\`\`\`

A disagreement causes \`freeze\` to fail. A *third*, distinct adjudicator
must submit the **same packet SHA** and label only disputed question/result
IDs, and the freeze command must include \`--adjudicator path.json\`.
There is no implicit tie-break. A consensus judgment stores the two declared
reviewer IDs, while an adjudicated judgment stores the third person's ID.
The audit includes packet and form SHA256 hashes and disagreement count.

The resulting \`frozen_judgments.json\` has exactly the v0.8.7 evaluator
schema. Inputs declared \`candidate_human\` become self-described
\`human_reviewed\` judgments, but this never means identities were externally
verified. Both audit and quality evaluator permanently carry HOLD until a
separate governed human/rights release review is complete.

## Security properties and known limitations

- Entire workflow is offline; no Neo4j, HTTP, OAuth, model inference or source
  text ingestion. Untrusted capture metadata is limited to IDs, titles, source
  anchors and matching semantics for private reviewer display.
- Validates complete cursor chains *as represented in the capture* before
  packet generation; capture authenticity and actual request cursor replay
  cannot be proven from the legacy v0.8.7 snapshot schema.
- Refuses less than five hits, missing Work/Passage anchors, source text,
  partial pages, repeated hits, malformed refs, duplicate judgments,
  unchecked labels and unadjudicated disagreements.
- Exclusive creation mode 0600 is applied to each output. Existing paths
  and symlinks are never overwritten. Avoid storing outputs in Git, cloud
  sharing or a public CI artifact. Filesystem permissions do not replace
  operational access control and encryption at rest.
- The included two-query Hebrew/English data and synthetic reviewer tests
  exercise mechanics only; **zero actual human evaluations have occurred.**
- Still required: 50 real frozen reviewed questions, controlled Sefaria or
  licensed-source rights, reviewer conflict governance, DvirOS SSO/RBAC,
  authenticated capture acquisition, independent signoff and production plan.
