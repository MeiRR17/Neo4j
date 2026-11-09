# v0.5.0 — Private typed Research API for DvirOS

**Status:** API implemented and exercised with synthetic fixtures. Public
deployment, real rights-cleared research corpus, full RBAC and DvirOS BFF
integration are **not** implemented. Keep all development services on localhost.

## Quickstart

Requires Python 3.10+, Neo4j v0.2 migrations and v0.1 Docker baseline.

```bash
python -m pip install -r requirements/research-api.txt
python scripts/bootstrap.py
python scripts/api_bootstrap.py
docker compose up -d --wait
python scripts/migrate.py apply
python scripts/run_research_api.py
```

The runner checks the actual Neo4j migrations and token before starting,
binds to **127.0.0.1:8765 only**, disables access logs and never prints
credentials. It uses `secrets/neo4j_auth.txt` for Neo4j and independently
bootstraps `secrets/research_api_token.txt` (owner-only file mode 0600).
Both are gitignored. Neither token nor Neo4j password goes in source code,
logs, browser or a static frontend.

The local OpenAPI contract is available at:
- `http://127.0.0.1:8765/openapi.json`
- `http://127.0.0.1:8765/docs` for local development.
- Protected requests use `Authorization: Bearer <token-file-value>`.
  Do not copy the token to a public screenshot, log or GitHub issue.

Only `/health/live`, `/health/ready` and the local OpenAPI documentation
are accessible without a bearer token. All `/v1/*` endpoints reject missing
or invalid tokens. Readiness checks actual DB access **and migration checksums**,
rather than returning success simply because the process started. Readiness
includes `research_corpus_status=human_review_pending`; this is not research
GA readiness.

## Endpoint contract (schema version 0.5.0)

| Endpoint | Query bounds | Data |
| --- | --- | --- |
| `GET /health/live` | no auth | process only |
| `GET /health/ready` | no auth; checks token+DB+migrations | DB read/schema |
| `GET /v1/works` | query <=100 chars, language he/en/ar/yi, limit 1–50, id cursor | safe work metadata |
| `GET /v1/works/{work_id}` | stable ID | work, edition count |
| `GET /v1/persons` and `/{person_id}` | query <=100, limit 1–50 | person metadata |
| `GET /v1/passages` and `/{passage_id}` | query <=100, limit 1–50 | exact refs/edition metadata |
| `GET /v1/concepts` and `/{concept_id}` | query <=100, limit 1–50 | controlled concept names |
| `GET /v1/links` | passage ID, claim kind, review status, limit 1–50 | links matched to actual Evidence nodes |
| `GET /v1/graph/neighborhood` | entity ID, **depth 1–2**, allowlisted edge types, paths <=20 | nodes/edges/provenance |
| `GET /v1/sources/{source_id}` | stable ID | rights/lineage metadata |
| `GET /v1/data/status` | no arbitrary filters | counts and human-review status |

All list responses include `schema_version`, `items`, `next_cursor`,
`corpus_status`. A cursor is a **stable canonical ID** of the last entry,
not a source-text fragment or offset. Sorting by ID produces consistent
keyset pagination for a given graph snapshot. Changing data between requests
may change page contents; snapshot pinning comes in later research workflows.

Every error returns a stable `error.code`, sanitized `message` and
`request_id`. HTTP response header `X-Request-Id` permits correlation
without logging credentials. Errors: 400 invalid identity, 401 missing token,
403 invalid token, 404 no entity, 422 invalid parameters, 503 missing
DB/secret/schema or query failure. No false fallback to fabricated records.

**No /cypher, /query, write routes, arbitrary path queries, unbounded
graph traversals or unrestricted SQL/Cypher execution**. The Python query
registry consists only of reviewed, parameterized MATCH/RETURN operations.
Neo4j replies are projected to allowlisted metadata keys. In particular,
Passage.excerpt is always null: NO full text is served before rights clearance.
A Sefaria SOURCE_LINK is *not* scholarly proof of direct citation or influence.

## Explicit security limitations

- This is a local-only development API, not a network SSO system. The
  token is a single service-level secret, not multi-user authentication.
  DvirOS user-level authorization and contract integration are v0.6+ work.
- **Neo4j Community lacks Enterprise role-based database read grants**.
  The database uses the protected local v0.1 admin credential; application
  read-only safety comes from its closed query registry. Query API
  `accessMode=Read` is routing, NOT a security role.
- Request timeout 8 seconds and server maxExecutionTime 5 seconds for each
  backend query, 2 MB max response body, 51-row absolute maximum and
  strict typed query parameters.
- Use private server-side communication. Do not connect a public browser
  directly to Bolt, Neo4j Query API or this local dev service. Production
  still needs service identity, TLS, least privilege and threat modeling.
- A human-cleared edition/100+ reviewed links/rights signoff are pending
  v0.4 acceptance gates. An API response is not a peer-reviewed study.
- No rate limiting yet: keep interface loopback-only; edge proxy/gateway
  policy comes with production hardening.
- No external APIs, AI models or remote telemetry are called by this API.

## Testing

```bash
python -m pip install -r requirements/research-api-test.txt
python -m unittest discover -s tests -v
```

GitHub CI also starts an isolated Neo4j, applies v0.2 migrations, then
executes `python scripts/api_smoke.py`. This script constructs a few
**invented** work/passage/edition/evidence nodes, tests real FastAPI
HTTP requests, unauthorized access, bounded graph paths and read-only
projection, then removes the fixtures.

## Rollback

Stop the local server, revert the API Git commit or deploy the prior verified
app build, and keep the database unchanged; this milestone adds **no new
graph schema migration** or real corpus ingestion. Data changes are owned by
the preexisting ingestion flows and require their own restore procedures.
