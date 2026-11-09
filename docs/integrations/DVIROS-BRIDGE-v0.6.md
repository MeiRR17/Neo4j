# DvirOS signed Research API bridge — v0.6.0

**Status:** backend service code implemented, paired with
`MeiRR17/dvir-os` on a separate feature branch. Not public or
available to browser clients, and **not a production deployment**.

The canonical protocol is stored in
[`RESEARCH-BRIDGE-v1.json`](RESEARCH-BRIDGE-v1.json).

## Exact service identity

Neo4j provides `GET /v1/integration/contract`, containing:
- `contract_version: 1.0`, `service_id: dviros.neo4j.philosophy`
- `api_version: 0.6.0`; existing DTO `schema_version: 0.5.0`
- `writes_allowed: false`, `full_text_available: false`,
  `human_approval_required: true`,
  `research_corpus_status: human_review_pending`
- Required source provenance and explicit supported capabilities.

DvirOS rejects mismatched contracts rather than silently interpreting
a new or incompatible backend.

## HMAC request signing

The private DvirOS BFF calls the **local** Neo4j API with its existing
bearer token plus:
- `X-DvirOS-Client: dvir-os/research-bff/v1`
- `X-DvirOS-Timestamp: <Unix seconds>` (clock skew <= 60s)
- `X-DvirOS-Nonce: <32 lower-case hexadecimal chars>`
- `X-DvirOS-Signature: <hex HMAC-SHA256>`

The signature is over the UTF-8 bytes of this newline-delimited string:

```text
dvir-os/research-bff/v1
GET
<exact raw request path and query>
<Unix seconds>
<nonce>
```

Canonical request paths start with `/v1/`. The backend verifies
signature with a locally stored 0600 secret and rejects replayed nonces.
It uses a bounded in-memory nonce cache and preserves legacy unsigned
behavior **only** in explicitly configured unit/CI harnesses. The
production-oriented local runner enforces signed mode unconditionally.

Generate the signing key locally (value never printed):

```bash
python scripts/api_bootstrap.py
python scripts/api_signature_bootstrap.py
python scripts/run_research_api.py
```

Use the same signing key only in the secure DvirOS server-side HMAC
file, not a client bundle. Service bearer and HMAC keys are distinct.
The HMAC key does NOT replace the Neo4j database credential; no DB
password is sent to DvirOS.

DvirOS must also configure a distinct, owner-only authentication secret
for its own BFF. See
`MeiRR17/dvir-os/docs/integrations/NEO4J-RESEARCH-BFF-v0.6.md`.

## Contract check and failure modes

- Missing/malformed service bearer → 401 or 403.
- Signed mode with incorrect signature, nonce replay, old timestamp,
  changed query or identity → 403.
- Missing signing file, misconfiguration, DB offline or schema mismatch
  → 503 with sanitized error code and request ID.
- Bounded research routes preserve existing v0.5 limit/depth constraints;
  arbitrary Cypher remains forbidden.
- No source texts, AI guesses, direct citation assertions or invented
  readiness indicators are exposed.

## Known limitations

- Current `MeiRR17/dvir-os` main has **no active human user auth**.
  The new BFF route is therefore feature-flagged **OFF** by default
  and accepts only an operator bearer token from private server callers.
- HTTP API on the same host binds to `127.0.0.1:8765`; do not expose
  public Next.js routes to clients before TLS, authentication and
  authorization are independently reviewed.
- Replay cache is in-memory and not cluster-safe. Multi-instance auth
  requires shared nonce storage and formal rotation policy.
- A green `/health/ready` means DB and schema are accessible; it does
  **not** mean 12–20 rights clearances or 100+ human-adjudicated links
  have been completed.

## Verification

```bash
python -m pip install -r requirements/research-api-test.txt
python -m unittest discover -s tests -v
```

CI starts disposable Neo4j, authenticates with a signed BFF request,
checks versioned contract and live graph status, rejects replay and
unsigned access, then cleans up. The deterministic HMAC test vector
is shared with DvirOS unit tests:

- key: `S` repeated 48 times (TEST FIXTURE, not a real key)
- target: `/v1/works?limit=2&query=Guide+for+the+Perplexed`
- timestamp: `1794220000`
- nonce: `0123456789abcdef0123456789abcdef`
- signature: `b32409ea6428811e59bec4a7e9f21c17dd2cf22d2852c0eeef0423c74ee87816`

This version adds **no destructive database migration**. Rollback can
disable the DvirOS bridge flag and stop the signed API server; existing
graph metadata remains unchanged.
