# DvirOS · Jewish Philosophy Research Engine (Neo4j)

**Canonical service repository** for the philosophy and Jewish thought
knowledge graph inside [DvirOS](https://github.com/MeiRR17/dvir-os).
This is a **research platform component**, not a teaching demonstration
or a Learning_Modules feature.

- [Full production roadmap](docs/ROADMAP.md)
- [DvirOS integration architecture](docs/architecture/0001-DVIROS-INTEGRATION.md)
- [Safe local operations](docs/operations/LOCAL_DEV.md)
- [Release history](CHANGELOG.md)

## Current implementation: v0.1.0 engineering foundation

The local graph database has a pinned Neo4j Community image, loopback-only
ports, Docker Secret authentication, persistent named volumes, an offline
test suite and a credential-checked smoke test. This is **not a deployed
production product**. User-facing research in DvirOS is still on the roadmap.

**Requirements:** Python 3.10+, Docker Compose v2, Docker Engine/Desktop.

```sh
python scripts/bootstrap.py
docker compose up -d
python scripts/smoke.py
python -m unittest discover -s tests -v
```

This generates a unique local password into ignored file
`secrets/neo4j_auth.txt`; it does not print the credential.
On POSIX systems, the enclosing directory is owner-only (0700) and its
file is read-only (0444) for Docker's non-root secret mount. Do not move
the file into any shared/public folder.
The database is accessible **only from this host** at
`http://127.0.0.1:7474` (Neo4j Browser) and
`bolt://127.0.0.1:7687` (developer driver).
Never expose the Browser or Bolt port publicly or to end users. Never
commit/share the secret file. Use `docker compose down` to stop without
deleting data. See [local operations](docs/operations/LOCAL_DEV.md)
for Windows, recovery restrictions and upgrades.

## Research scope and epistemic boundaries

Target entities: Work, Passage, Thinker, Concept, Source, Evidence,
Edition and reviewed claims. Human-reviewed interpretations and model
suggestions must remain separate from observed source links. Similarity,
co-citation and graph centrality are **hypotheses/structural measures**,
not automatically historical influence, scholarly authority or agreement.

The legacy files `scripts/02_acquire_sefaria_data.py`,
`cypher/03_import_to_neo4j.cypher` and
`cypher/04_analytics_queries.cypher` remain available as historical
prototypes. They contain known title-normalization, link semantics and
provenance limitations. Do **not** use their output as validated evidence.
New data acquisition and canonical graph migrations are v0.2–v0.4 work.

## Separation from Learning_Modules

An old script snapshot exists in Learning_Modules. It is not relevant to
this product and is **not** the target for new code, tests or deployment.
This repository owns research data models, ingestion and query services.
The research workspace and authentication will be integrated **inside**
DvirOS, not as a competing independent user-facing application.
