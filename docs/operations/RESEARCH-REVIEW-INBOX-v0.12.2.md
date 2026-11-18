# v0.12.2 — Signed multi-run research Evidence review inbox (Neo-only Draft)

## Purpose

Several independently completed v0.12.1 **signed read-only tool executions**
can observe the *same* Evidence under different Passage scopes, metadata
queries or selected-review dossiers. v0.12.2 provides a **local, bounded
offline aggregation** that turns 2–6 complete original signed-run envelopes
into one reproducible Evidence review inbox. It does not connect to a DvirOS
inbox, authenticate end users, publish conclusions, persist agent task state,
fetch licensed text or read Neo4j during assembly/verification.

For each input, the builder performs a complete offline verification of the
v0.12.1 **service-HMAC**, v0.12.0 planned scope/checkpoint, strict nested
operation-specific result and Evidence cards. Duplicate signed-run digests
are refused; the tool never counts the same exact signed run twice as
independent support.

The builder sorts the authenticated run receipts by digest (input file
order is irrelevant) and gives each a deterministic `run_index`. Each
Evidence ID is included **once** in the review inbox, with its original
per-run observations, source-reference metadata, version and rights tags,
recorded review label, exact run digest and operation.

## Review-only metadata warnings

An Evidence may have warnings for multiple exact `source_ref` values,
different edition/version IDs, rights tags, recorded review statuses,
different graph Edge IDs, missing version/rights metadata or observed
`disputed`/`rejected` labels. Warnings are intentionally **not**
automatic approval, scholarly contradiction, graph-change proof or
legal source-license assessment. The same Evidence being observed
across runs is not counted as distinct findings.

Counters distinguish `observed_card_count` from
`distinct_evidence_count`, `repeated_evidence_count` and
`metadata_warning_evidence_count`. Each run summary retains the original
operation, query **hash** (not text), Passage IDs, plan checkpoint,
source signed-receipt SHA256, full original execution SHA256 and scheduled
graph-read bound. All records are metadata; no raw Passage text or prompts
are exported. Stored source references and Evidence IDs remain **private**.

## Private CLI — build and verify

First save two to six **different** complete v0.12.1 signed execution
envelopes as owner-only `0600` JSON files on the same secure machine.
Use the same owner-only local service-token file that signed them.

```sh
python scripts/research_review_inbox_v0122.py build \
  --run /private/signed-run-1.json \
  --run /private/signed-run-2.json \
  --token-path /private/research-api-token \
  --output /private/research-review-inbox.json

python scripts/research_review_inbox_v0122.py verify \
  --run /private/signed-run-1.json \
  --run /private/signed-run-2.json \
  --token-path /private/research-api-token \
  --report /private/research-review-inbox.json
```

Additional `--run` arguments are allowed up to six. Each source input is
read by the existing private file reader, rejecting weak permissions,
symlinks, duplicate JSON keys and oversized inputs. `build` creates a
private output exactly once; it cannot overwrite an existing file.
Both commands print only aggregate counters and verification status, not
source metadata, selected Evidence IDs, query text or the service token.

The result is `inbox`, `inbox_sha256` and
`inbox_hmac_sha256` with a **distinct v0.12.2 HMAC domain**, binding
the exact ordered run manifest, source metadata observations and review
flags. The verifier requires all original v0.12.1 source runs and the
same service secret; it replays every signature and recomputes the inbox
without any database, network or model call.

## Provenance and release boundaries

A service HMAC only establishes **local service-key integrity** for the
supplied observations. It cannot establish who initiated the tools,
whether two graph reads came from the same immutable snapshot, whether
an edition was licensed or a source reference was a correct citation.
Repeated metadata matches can reflect the same graph observation rather
than independent academic support. The inbox explicitly records false
human approval, rights, workspace authorization and immutable-snapshot
claims with `research_release_status=HOLD`.

No public REST endpoint, dynamic tool registration, agent provider, graph
write, durable job/retry state or DvirOS cross-repository change is made
here. The existing v0.12.0/0.12.1 feature flags stay default OFF.

**Release HOLD:** upstream stacked Draft PRs and P0/P1 independent
security, scholarly review, edition rights and operational readiness
remain unresolved. Do not merge to `main` solely on CI success.

Focused check:

```sh
python -m unittest tests.test_research_review_inbox_v0122 -v
```

Contract: `docs/integrations/RESEARCH-REVIEW-INBOX-v0.12.2.json`.
