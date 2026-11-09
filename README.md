# DvirOS · Jewish Philosophy Research Engine (Neo4j)

**Canonical service repository** for the Jewish philosophy knowledge graph in
[DvirOS](https://github.com/MeiRR17/dvir-os).
This is a **research platform component**, not a teaching demonstration
or a Learning_Modules feature.

- [Full production roadmap](docs/ROADMAP.md)
- [System integration architecture](docs/architecture/0001-DVIROS-INTEGRATION.md)
- [Canonical ontology / evidence contract](docs/architecture/0002-CANONICAL-ONTOLOGY.md)
- [Safe local operations](docs/operations/LOCAL_DEV.md)
- [Sefaria link metadata ingestion](docs/operations/SEFARIA_INGESTION.md)
- [Scholarly seed corpus and human review](docs/operations/SEED_CORPUS.md)
- [Private Research API quickstart and contract](docs/operations/RESEARCH_API.md)
- [Signed DvirOS integration contract](docs/integrations/RESEARCH-BRIDGE-v1.json)
- [v0.6 cross-repository bridge setup](docs/integrations/DVIROS-BRIDGE-v0.6.md)
- [Research API architecture illustration](docs/architecture/v0.5-research-api.svg)
- [v0.4 scholarly quality diagram](docs/architecture/v0.4-scholarly-pilot.svg)
- [v0.3 pipeline diagram](docs/architecture/v0.3-pipeline.svg)
- [Changelog](CHANGELOG.md)

## Current implementation: v0.6.0 signed DvirOS service bridge

The foundation has a pinned Neo4j Community image, loopback-only ports,
Docker Secrets, persistent named volumes and verified CI startup/restart.
v0.2 added canonical identities, evidence-bound edges and versioned schema
migrations. v0.3 adds an **opt-in**, bounded Sefaria link metadata pipeline,
quality quarantine, resumable GCS downloads, API fallback, immutable input
checksums, provenance manifests and idempotent Neo4j metadata writes.
v0.4 adds 18 scholarly candidate works, Sefaria edition metadata discovery,
per-version rights-review contracts, a deterministic 100+ source-link review
queue, quality gates and reviewed-edition *metadata-only* upserts.
v0.5 adds a loopback-only FastAPI read service, OpenAPI, bearer-token
authentication, bounded evidence-grounded graph queries, safe typed responses,
cursor pagination, correlation IDs, readiness based on real schema validation,
and true empty-state reporting while the corpus remains under review.
v0.6 adds a versioned, signed server-to-server contract for an opt-in DvirOS
BFF adapter, using a separate HMAC key, timestamp, nonce and anti-replay
check on top of the existing backend bearer. A local runner requires
both credentials; no browser client can directly access Neo4j.

**No candidate edition or scholarly link has been automatically approved.**
The human rights and scholarly review acceptance gates are **not yet complete**,
and this is not a deployed production product or a licensed text corpus.

**Requirements:** Python 3.10+, Docker Compose v2, Docker Engine/Desktop.
Install the API runtime with `python -m pip install -r requirements/research-api.txt`
before running the API.

```sh
python scripts/bootstrap.py
docker compose up -d --wait
python scripts/smoke.py
python scripts/migrate.py dry-run
python scripts/migrate.py apply
python scripts/migrate.py check
python scripts/ingest_sefaria.py --help
python scripts/seed_corpus.py --help
python scripts/api_bootstrap.py
python scripts/api_signature_bootstrap.py
python scripts/run_research_api.py
python -m unittest discover -s tests -v
```

The unique password lives in ignored file `secrets/neo4j_auth.txt`.
The host `secrets/` directory is owner-only (0700) and the secret
file is read-only (0444) to permit Docker's non-root secret mount.
No password is printed or put in the repository. See the local operations
guide for Windows ACLs, stop/restart, security and upgrade details.

## Scholarly correctness and privacy

- `:Work` is keyed by immutable provider ID, **not** translated title.
- `:Passage` is keyed by edition ID + exact full reference; no string split.
- `:Evidence` preserves exact provider reference, version and rights tag.
- `:SOURCE_LINK` means an observed cross-reference, **not** proven citation.
- `:HUMAN_CLAIM` and `:SUGGESTED_RELATION` remain explicitly distinct.
- Graph relations require evidence and review metadata; suggestions cannot
  silently promote themselves to approved knowledge.
- Sefaria link metadata is **unreviewed**, orientation is not inferred and
  edition IDs use an explicit no-edition sentinel; no source text is imported.
- Import requires an explicit `apply --ack-unreviewed` after an inspected plan
  with zero quarantined records and a checked migration schema.
- v0.4 stores rights/edition metadata, not book text. Edition rights
  require a separate human decision tied to the exact inventory hash.
- The quality report requires 12–20 approved works and 100+ separately
  inspected links; a technical CI pass **does not** mean those gates passed.
- All `/v1/*` Research API operations require a private bearer token.
  No arbitrary Cypher endpoint exists, traversal depth <=2, no excerpts
  are returned without rights clearance, and the DB remains local-only.

The legacy `scripts/02_acquire_sefaria_data.py` and original Cypher demos
are **historical prototypes**, not validated research pipelines. Do not
import their output as trustworthy source evidence. The new
`scripts/ingest_sefaria.py` replaces link **metadata** ingestion; v0.4 now supplies edition discovery and a human-reviewed seed-pilot
workflow. Actual edition clearance and scholarly signoff remain pending.

An unrelated utility snapshot in Learning_Modules is left unchanged and
is not developed here. The eventual research UI belongs **inside DvirOS**,
not in an independent application. See the roadmap for the API and UI phases.
