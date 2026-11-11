# v0.8.11 — Source, edition and evidence provenance (DRAFT)

This version extends private signed research capture with three strictly
allowlisted metadata projections. It does not download source texts, establish
copyright clearance, audit human reviewer credentials, or supply a database
snapshot. The earlier search results and their audit remain intact.

## Private read-only API

The signed bearer-protected route is:

    GET /v1/provenance/metadata?kind=sources&limit=20
    GET /v1/provenance/metadata?kind=editions&limit=20
    GET /v1/provenance/metadata?kind=evidence&limit=20

The kinds are fixed (sources, editions, evidence); page size is 1–20.
The optional cursor is a canonical ID of the matching type. Unknown or
duplicated request parameters fail with 422; missing bearer returns 401.
In an authorized deployment, set DVIROS_REQUIRE_SIGNED_CALLS=1 to require
DvirOS HMAC service identity for all of these requests.

Each kind invokes precisely one static read-only query:
- SourceRecord: ID, provider, URI, version ID, rights tag and *stored,
  provider-supplied* checksum_sha256.
- Edition: ID, canonical work ID, version ID, language, rights tag, metadata
  review status and explicit non-redistribution status.
- Evidence: ID, source-record ID, version ID, rights tag, claim kind and
  review status (as reported by the database, not certified externally).

Any extra field, source body/excerpt, broken canonical ID, decreasing result
order, invalid source checksum format, unknown evidence claim, or an
unexpected text-redistribution status causes a sanitized error. The API
always reports source_bytes_verified=false,
rights_independently_verified=false, source_text_available=false and
corpus_snapshot_isolation=false. No write operation is introduced.

## Capture and verify on an explicitly authorized local host

Use the existing, already-provisioned private bearer and HMAC key files
with the local-only Research API. Select scan or indexed search explicitly.

    umask 077
    python scripts/search_capture.py capture \
      --questions /private/review_questions.json \
      --search indexed --url http://127.0.0.1:8000 \
      --ack-authorized-metadata-only \
      --pin-observed-projection \
      --pin-source-provenance \
      --output /private/frozen_results.json \
      --manifest /private/frozen_manifest.json

    python scripts/search_capture.py verify \
      --questions /private/review_questions.json \
      --responses /private/frozen_results.json \
      --manifest /private/frozen_manifest.json \
      --require-observed-projection \
      --require-source-provenance

The new source-provenance pin requires the v0.8.10 search projection pin.
Both the visible search metadata and these three source/edition/evidence
projections are observed before and after the collection. If the records or
their visible metadata change, capture is rejected before saving evidence.

The new v0.8.11 manifest HMAC covers:
- SHA256 hashes of exact catalog and frozen search-response bytes;
- all signed GET request/cursor/response digests (v0.8.9);
- the bounded search and index revision observation (v0.8.10);
- count and SHA256 of observed source, edition and evidence fields per kind,
  plus missing checksum/version counts (v0.8.11).

The observer reads no more than 25 pages or 500 records per kind, with
fixed 20-record pages. Limits apply to each before/after pass. The
source-provenance records themselves are hashed but never printed in the
manifest. Normal private output files are created with exclusive-create
mode 0600, and existing files cannot be overwritten. The existing
v0.8.9 and v0.8.10 manifests remain verifiable.

## Fundamental limits

This is *observed metadata stability*, not immutable source identity.
Stored source checksums may be provider assertions and are **not** checked
against the original bytes. Source URIs, rights tags or reviewed_metadata
status do **not** prove rights to quote or redistribute any text.

Unexposed graph edges, alias relations, hidden source content, reviewer
identities and edition links can change without detection. Multiple GETs
cannot guarantee one Neo4j read transaction. Equal before/after values
cannot detect intermediate changes (ABA). The HMAC protects integrity only
while the local client key is protected; it is not an independent server
signature or a trusted third-party timestamp.

All resulting research_release flags are HOLD. Full corpus provenance
requires immutable source receipts, independent rights review, a real
snapshot/write-freeze boundary, and 50 genuinely human-judged questions
with the stated Precision@5 threshold before v0.8 can be approved.
