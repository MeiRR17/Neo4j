# v0.9.11 — Two-pass, HMAC-sealed Work-link audit export

## Scope and API

This draft adds the authenticated, private read-only endpoint

    GET /v1/analysis/works/links/audit/export
      ?source_work_id=work:...&target_work_id=work:...

The two required parameters must be distinct canonical Work IDs. Unknown
or repeated query keys and all client-supplied limits are denied. The
server fixes page_size=20 and max_pages=5; there can be at most **100**
observed, directed, evidence-backed links. If even one additional
record exists, the export refuses to produce a partial manifest.

No full source text, user-submitted Cypher, arbitrary graph properties,
tokens, or credentials enter the response. Work source and target
direction, canonical Passage/Edge/Evidence IDs, independent review
statuses, source references, version and rights *tags* (not legal
rights clearance) are included. Existing fixed, read-only Cypher
operation and index anchor are reused. Nonexistent Works return 404.

## Two-pass observation contract

The server reads all up to five pages, with strict Edge-ID order and
no duplicate Evidence across pages. It then independently re-reads the
same Work pair from the beginning, validating the same page boundaries.
A different canonical projection or page count returns HTTP 409
AUDIT_DRIFT; an over-budget result or unsafe graph shape returns a
sanitized 503. Reaching the last page is **only** a bounded observation
for one selected directed Work pair. The second pass can miss concurrent
ABA edits, changes that happen after the second pass, changes outside
this Work pair, unobservable data and mutations during one pass.

Two matching scans are NOT a Neo4j transaction snapshot, a durable
corpus revision, a complete full-graph census, or immutable research
source data. The manifest always sets:
- observation_scope=two_sequential_bounded_reads_only
- sequential_passes_matched=true
- graph_snapshot_verified=false
- corpus_revision_immutable=false
- independently_licensed_sources_verified=false
- historical_influence_proven=false
- research_release_status=HOLD

## Content integrity receipt

The response envelope contains only manifest, manifest_sha256 and
receipt_hmac_sha256. Canonicalization uses UTF-8 JSON with sorted
object keys, no spacing and preserved array order, bounded at 250 KB.

HMAC input includes a v0.9.11 domain prefix and the 64-byte ASCII hex
of the entire canonical manifest hash. Its key is the same locally
protected server-to-server bearer secret already provisioned under
mode 0600; the key does not appear in the envelope. This establishes
integrity relative to *knowledge of that local service key*.
It is NOT an independently issued scholarly signature, long-term
archival key-management solution, or legal authenticity certificate.
Rotating the key invalidates old offline receipts unless the prior
key is retained securely through an approved process.

The manifest carries query-template SHA-256, UTC Unix capture seconds,
ordered metadata links, selected pair, observed population and page
count. A verifier validates exact envelope/manifest/row allowlists,
canonical IDs, ordering, review statuses, fixed bounds, research HOLD
flags and constant-time digest/MAC comparison.

## Offline verification

Store the response JSON as a private file on a trusted host with
access to the protected service token file, then run:

    python scripts/verify_work_audit_export_v0911.py \
      --input audit-export.json \
      --token-path secrets/research_api_token.txt

The command never contacts Neo4j; it prints a sanitized verification
summary with the digest and count, not the source references. It
rejects symlink input, missing files and oversized content. Do not
publish the raw export or reuse a bearer token as a public verification
key. The server's bearer remains a local protected secret.

## Tests and remaining gates

Twelve focused tests cover two equal passes, empty and 100-link cases,
101-link denial, Evidence changes between passes, hash and HMAC
tampering, extra source fields, fake rights/release claims, missing
Work, authorization, query key rules and CLI validation. CI's isolated
Neo4j smoke seeds two synthetic cross-Work links and independently
checks the endpoint response and offline HMAC receipt, then cleans
the exact synthetic fixtures.

Existing v0.9.6, v0.9.7, v0.9.8 synthetic cost guardrails remain
unchanged. Independent historical source review, edition rights,
immutable database-backed revision/transaction controls, approved
external signature storage, key rotation, 100+ scholarly checked
relationships, 20 real analyses, and DvirOS SSO/RBAC are not done.
Research release stays HOLD.
