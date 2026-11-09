# DvirOS · Jewish Philosophy Research Engine (Neo4j)

**Canonical service repository** for the Jewish philosophy knowledge graph in
[DvirOS](https://github.com/MeiRR17/dvir-os).
This is a **research platform component**, not a teaching demonstration
or a Learning_Modules feature.

- [Full production roadmap](docs/ROADMAP.md)
- [System integration architecture](docs/architecture/0001-DVIROS-INTEGRATION.md)
- [Canonical ontology / evidence contract](docs/architecture/0002-CANONICAL-ONTOLOGY.md)
- [Safe local operations](docs/operations/LOCAL_DEV.md)
- [Changelog](CHANGELOG.md)

## Current implementation: v0.2.0 ontology and migrations

The foundation has a pinned Neo4j Community image, loopback-only ports,
Docker Secrets, persistent named volumes and verified CI startup/restart.
v0.2 adds canonical identity rules, an evidence-bound relationship contract
and versioned schema migrations. It is **not** a deployed production product.

**Requirements:** Python 3.10+, Docker Compose v2, Docker Engine/Desktop.

```sh
python scripts/bootstrap.py
docker compose up -d --wait
python scripts/smoke.py
python scripts/migrate.py dry-run
python scripts/migrate.py apply
python scripts/migrate.py check
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
- No real source text is distributed by this schema implementation.

The legacy `scripts/02_acquire_sefaria_data.py` and original Cypher demos
are **historical prototypes**, not validated research pipelines. Do not
import their output as trustworthy source evidence. v0.3–v0.4 replace the
ingestion workflow and add rights-reviewed pilot texts.

An unrelated utility snapshot in Learning_Modules is left unchanged and
is not developed here. The eventual research UI belongs **inside DvirOS**,
not in an independent application. See the roadmap for the API and UI phases.
