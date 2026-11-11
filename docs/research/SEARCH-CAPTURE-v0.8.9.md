# v0.8.9: signed private metadata capture (DRAFT)

The v0.8.8 review workflow requires a frozen v0.8.7 search response file.
This version provides a controlled **local operator command** to capture
authenticated metadata-only results; it does not add a public endpoint,
background service or graph write operation.

## Usage on an authorized research host

Provision the existing API token and DvirOS HMAC secret in local mode-0600
files. Run the Research API at 127.0.0.1:8000 and configure its signed-call
enforcement (DVIROS_REQUIRE_SIGNED_CALLS=1). Choose one fixed mode for all
catalog questions: scan (v0.8.2) or indexed (v0.8.3). The indexed option
requires the physical range index to be ONLINE and the metadata backfill
complete. This script never performs the backfill or changes schema.

    umask 077
    python scripts/search_capture.py capture \
      --questions /private/review_questions.json \
      --search scan \
      --url http://127.0.0.1:8000 \
      --ack-authorized-metadata-only \
      --output /private/search_responses.json \
      --manifest /private/search_manifest.json

    python scripts/search_capture.py verify \
      --questions /private/review_questions.json \
      --responses /private/search_responses.json \
      --manifest /private/search_manifest.json

Question catalogs use exactly the existing v0.8.8 schema. Snapshot outputs
retain the v0.8.7 schema and can feed v0.8.8 packet preparation, two
independent human-review forms and the v0.8.7 quality evaluator.
The data and private credentials must never be uploaded to GitHub.

## Request and memory budgets

- Only literal http://127.0.0.1:PORT is permitted, without credentials,
  remote addresses, URL paths, fragments, redirects or proxy use.
- Only server-owned GET /v1/search/metadata and
  /v1/search/metadata/indexed are called; query values are parameters, not
  Cypher fragments. A fresh nonce/timestamp and HMAC cover every raw target.
- Fixed limit 20 items, at most 12 pages per question, 200 hits per
  question, 150 GET requests overall, 64 KB per HTTP response, and 512 KB
  per finalized frozen snapshot. Each read has an 8-second socket timeout.
  Incomplete scans, exhausted budgets and unavailable indexes fail closed.
- No text excerpts, unknown hit fields, unverified rights promotion,
  mislabeled schema, non-increasing canonical IDs, duplicate results,
  mismatched cursors or mixed indexed/scan semantics are accepted.
- All output files are created at mode 0600 with exclusive-create and no
  overwriting. An unsuccessful capture does not produce frozen evidence.
- No query text, bearer, HMAC key, title, source ID or server response
  body appears in stdout.

## Local provenance manifest

The versioned 0.8.9 manifest includes catalog and snapshot SHA256 hashes,
a reproducible per-page request-target/input-cursor/output-cursor/response
fingerprint chain, and an HMAC over the complete manifest body with explicit
domain separation. An offline verify command checks those invariants using
the protected DvirOS HMAC key; this detects unexpected edits after capture,
**not** an independently verifiable server assertion. A compromised local
HMAC key can be used to forge a local manifest.

The manifest always records independent_server_attestation=false,
source_rights_verified=false, independent_human_review_verified=false
and release_status=HOLD. The tool cannot establish source licensing, corpus
revision stability, a complete real gold set or the expertise of reviewers.
The existing 50-question, 0.80 Precision@5 and human-signoff release gates
remain pending. Synthetic tests exercise code, not real scholar evaluations.

## Isolated integration validation

CI also runs scripts/capture_smoke.py **after** the signed DvirOS bridge
and indexed metadata backfill. It uses the actual disposable Neo4j database
and the real signed HTTP request handler, routed through an in-process local
FastAPI TestClient, to capture and verify both scan and indexed-prefix pages.
No production network address is contacted and no review records are created.
