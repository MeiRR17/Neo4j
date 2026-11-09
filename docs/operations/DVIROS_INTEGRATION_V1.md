# v0.6.0 — DvirOS philosophy research service contract

**Status: contract implemented, end-to-end live integration pending.**
This repository is the canonical research engine. The UI and BFF belong in
[`MeiRR17/dvir-os`](https://github.com/MeiRR17/dvir-os).
The other Learning_Modules snapshot is untouched.

## Versioning and paths

- Integration contract: `contracts/dviros-research/v1/contract.json` (**1.0.0**).
- Existing research API: **0.5.0**, unchanged; BFF must reject an unexpected
  `schema_version` rather than silently treating a breaking response as valid.
- DvirOS origin: `/api/research/philosophy/*` (GET only).
- Upstream origin: private `/v1/*`. Never use browser-direct Bolt, and do
  not expose the research service bearer token or Neo4j URI to the client.
- An entirely synthetic fixture is maintained in
  `contracts/dviros-research/v1/synthetic-fixture.json`.
  It is **not** Sefaria evidence or rights-cleared scholarly data.

## Authorization boundary

The DvirOS gateway starts **disabled**. A local explicit demo mode can serve
the synthetic fixture without upstream access. Live mode requires a
short-lived, signed DvirOS session with `research:read` scope and
a separately provisioned server-side bearer credential. The cookie issuer
and human RBAC/session lifecycle must come from future DvirOS identity work;
this repository neither issues sessions nor creates human accounts.

The upstream API currently uses a single service token. This is not
production-grade mTLS/service identity or Neo4j Enterprise RBAC. Configure
TLS, rate limiting, principal separation, session revocation and audited
access before enabling live access outside trusted local development.

## Explicit state policy

- Disabled/offline: show "Not connected"; no fabricated graph counts.
- Mock: show "Synthetic demonstration" in the UI and never approve links.
- Empty: valid authenticated API response with zero works.
- Unavailable: fail closed with a traceable request ID, no internal URLs.
- Upstream credential/contract mismatch: unavailable; no mock fallback.
- Observed Sefaria links are **not** proven direct quotation, causality or
  historical influence. Excerpts remain null pending edition rights review.

## Acceptance/limitations

This commit provides an inspectable, versioned contract and offline test.
The companion DvirOS implementation is reviewed in its own PR. Neither
contract presence nor synthetic tests satisfy live integration, real identity,
data licensing, rate-limit or scholarly-review production gates.
