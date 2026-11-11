# v0.9.10 — Signed Work-link audit checkpoint (DRAFT)

The earlier audit endpoint reads successive directed SOURCE_LINK pages.
This version adds a new, private GET endpoint:

    /v1/analysis/works/links/audit/checked

It accepts required canonical source_work_id and target_work_id,
optional checkpoint, and bounded limit (1 to 20, default 10). The
authenticated initial call returns the original evidence-linked page
and a signed continuation checkpoint only if has_more is true.

Checkpoint payload: fixed v0.9.10 schema, source/target Work IDs,
previous and last Edge IDs, fixed page limit, full visible prior-page
metadata SHA-256, fixed query-template SHA-256, issued and expiration
epoch seconds. It is canonical JSON encoded as URL-safe base64,
authenticated with HMAC-SHA256 using a domain-separated key operation
over the existing protected Research API bearer secret. It is NOT
encrypted; no source text, licenses, titles or service secrets enter
the checkpoint. Rotating the service token also invalidates it.
Tokens expire after ten minutes. Never log a checkpoint or bearer.

On continuation, signature, scope, exact query version, key order,
limit and expiry are checked before the DB is accessed. The server
then re-reads the immediately preceding 1–20-link metadata window
using the fixed, read-only Neo4j operation, validates all graph rows,
and recomputes a hash over source/target anchors, Edge/Evidence IDs,
review statuses, counts, continuation flag and all returned metadata.
A mismatch returns HTTP 409 AUDIT_DRIFT with a generic error message.
If it matches, the server advances from the prior last Edge ID and
issues a new checkpoint only when more rows remain.

This does NOT provide a coherent multi-request graph snapshot.
Changes to earlier pages, unseen positions, non-adjacent records or
between re-observation and next-page read may go undetected. No corpus
completeness, immutable revision, historical author/rights verification,
scholarly quality, source authenticity or transitive influence is
certified. Responses explicitly say previous_page_reverified,
drift_detection_scope=immediately_previous_bounded_page_only,
snapshot_consistency_verified=false,
entire_audit_chain_reverified=false,
source_rights_verified=false and research_release_status=HOLD.

Verification includes 13 targeted tests: unchanged page chaining,
changed Evidence review state, deleted/inserted prior rows, tampered
MAC, wrong Work direction and limit, token expiry, secret rotation,
invalid/duplicated keys, missing Works, read projection and
non-snapshot flags. The live disposable Neo4j integration smoke seeds
two cross-Work links, mutates one observed Evidence status, verifies
HTTP 409 and confirms recovery after restoration. Fixture cleanup
uses exact synthetic IDs. Existing 32/128, 256/512 and unrelated-Work
performance guards are not relaxed.

Remaining approval: signed full-chain revision/export, source and
edition rights, scholarly human review, DvirOS SSO/RBAC, production
reliability and representative benchmark measurements.
