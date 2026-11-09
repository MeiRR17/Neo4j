# Local development operations — Neo4j research graph for DvirOS

This runs **only** the backing development database. It is **not** a public
production system and must not be reachable from a browser across the LAN.
The authenticated DvirOS Research API/BFF will arrive in v0.5–v0.7.

## Prerequisites

- Python 3.10+ (standard library only for setup/smoke)
- Docker Engine/Desktop and Docker Compose v2
- Enough free disk for graph volumes; keep this project's storage separate.
- Run from repository root, not from the copied Learning_Modules snapshot.

## Bootstrap

1. `python scripts/bootstrap.py` (Windows: `py -3 scripts/bootstrap.py`)
2. Optionally copy `.env.example` to `.env` for memory settings.
3. `docker compose up -d`
4. `docker compose ps`
5. `python scripts/smoke.py` (Windows: `py -3 scripts/smoke.py`)

Open Neo4j Browser at `http://127.0.0.1:7474` for **local development
administration only**. The user is `neo4j`; retrieve the unique password
privately from `secrets/neo4j_auth.txt` (after the slash). Never paste that
file or password into tickets, prompts, screenshots, commits, or logs.

`docker compose down` stops the service but retains named volumes.
**Never use `docker compose down -v` unless you intend to delete data.**

## Data and security

- Ports 7474/7687 bind only to `127.0.0.1`, not `0.0.0.0`.
- Credentials are generated locally with O_EXCL; the **parent directory** is
  owner-only mode 0700. The file itself is read-only 0444 so Neo4j's non-root
  container user can read the Compose file-backed secret (Compose cannot chown
  file-backed secrets). Other host users cannot traverse the 0700 directory.
  The credential is passed as a Docker Compose secret via
  `NEO4J_AUTH_FILE`, never a password environment variable.
  On Windows, apply owner-only directory ACLs; POSIX bits do not enforce ACLs.
- Password initialization runs only on a *new* Neo4j data volume. Recreating
  the secret does **not** rotate the password on existing data. Preserve and
  back up your credential securely; rotation and restore drills are scheduled
  for v0.13/0.14. Do not delete a missing secret and regenerate blindly.
- Keep this machine's local firewall active; localhost binding alone is not
  a remote deployment security design. No external forwarding/tunnel.
- The `/import` volume is empty until curated ingestion is implemented.
  The old `scripts/02_acquire_sefaria_data.py` and old Cypher CSV import
  remain **legacy only**: they have known reference/provenance defects and
  must not be treated as trustworthy research data.
- No APOC plugins or unrestricted procedures are installed.

## Minimal verification

`python -m unittest discover -s tests -v` runs offline, fast tests.
`docker compose config --quiet` validates the Compose model.
`python scripts/smoke.py` calls Neo4j's Query API on localhost,
verifies the anonymous request returns 401, then verifies an authenticated
`RETURN 1` succeeds. It performs no graph mutations or data imports.

The Docker healthcheck is a **local Bolt TCP socket probe**, not a full
authenticated readiness test. Use smoke.py for authenticated readiness.

## Troubleshooting

- Docker not found: start Docker Desktop/Engine and install Compose v2.
- Auth error after migration: an existing named volume has its own password.
  Recover its original credential; do not delete volumes to force reinit.
- Secret file unreadable inside the container: on Linux/macOS verify the
  directory is mode 0700 and the file is mode 0444
  (`chmod 700 secrets && chmod 444 secrets/neo4j_auth.txt`).
  Do **not** put this file in a shared directory; if your filesystem cannot
  enforce directory permissions, do not use this configuration.
- Browser opens but smoke fails: check `docker compose logs neo4j` (scrub
  logs before sharing) and rerun the smoke after health reports healthy.
- Query endpoint must remain local; smoke refuses non-loopback destination.

## Upgrades

The image tag is intentionally pinned to a patch release. Upgrades are a
separate PR with a database compatibility check and verified backup/restore;
a floating `latest` tag is forbidden. Future deployment into DvirOS will
use private service connectivity, TLS and scoped principals, not these
developer-facing ports.

References:
- https://neo4j.com/docs/operations-manual/current/docker/docker-compose-standalone/
- https://neo4j.com/docs/query-api/current/query/
