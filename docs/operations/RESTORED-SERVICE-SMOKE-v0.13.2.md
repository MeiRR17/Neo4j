# v0.13.2 — Isolated authenticated restored-service read smoke (DRAFT)

This increment extends the v0.13.1 offline load/consistency drill with a
**separately started Neo4j DBMS in the same disposable Docker volume** and
fixed read-only `cypher-shell` queries. It is for **Neo operators only**,
not a public service, not a production restore, and not an AI agent.

## What execution actually checks

After confirming the existing v0.13.0 private canonical dump manifest and
SHA256 bytes **before Docker access**, the operator-acknowledged command:

1. Selects two distinct random, unused Docker resource names. Creates one
   new labeled volume (no reuse of the project Compose `neo4j_data`).
2. Loads the source archive via the v0.13.1 fixed admin-image stdin path,
   then runs the offline database consistency check.
3. Starts the locally pinned `neo4j:2026.10.1` container with
   `--network none`, `--pull never`, **no published ports**, no
   host data bind and a randomly generated **per-run password**. It passes
   the temporary `NEO4J_AUTH` value in the Docker client's environment
   rather than in argv; Docker administrators can still inspect the
   ephemeral container environment, so run only on a trusted private host.
4. Calls `cypher-shell` by `docker exec` over **container loopback**
   (`bolt://localhost:7687`) with that temporary password via
   `NEO4J_PASSWORD`. All calls force `--access-mode read`. Only six
   fixed, audited queries are permitted:
   - `RETURN 1 AS result`
   - `MATCH (n) RETURN count(n) AS result`
   - `MATCH ()-[r]->() RETURN count(r) AS result`
   - `MATCH (p:Passage) RETURN count(p) AS result`
   - `MATCH (s:SourceRecord) RETURN count(s) AS result`
   - `SHOW CONSTRAINTS YIELD name RETURN count(*) AS result`
5. Refuses ambiguous output, negative or unexpected counts, and any result
   below explicit operator-supplied minima. Re-verifies the original dump.
   Removes both ephemeral container and volume on success or failure.
   Only after successful cleanup does it write a private 0600
   create-once unsigned SHA256 report.

Queries return **aggregate counts only**. No names, excerpts, source
references, credentials or private paths are placed in the report.
`nodes`, `relationships`, `passages`, `source_records` and
`constraints` each have independently enforceable non-negative minima;
at least one threshold must be positive.

## Commands

Prepare a real, offline Community `neo4j.dump` plus private
v0.13.0 manifest as described in
[the backup runbook](OFFLINE-BACKUP-v0.13.0.md). Pre-pull the repository's
exact `neo4j:2026.10.1` runtime image and
`neo4j/neo4j-admin:2026.10.1` admin image.

First inspect the plan **without any Docker calls**:

```sh
python scripts/restored_service_smoke_v0132.py plan \
  --archive /private/neo-backups/neo4j.dump \
  --manifest /private/neo-backups/neo4j.backup-manifest.json \
  --minimum-nodes 100 --minimum-passages 20 --minimum-constraints 1
```

Then, only with operator authorization and sufficient isolated disk/RAM:

```sh
python scripts/restored_service_smoke_v0132.py execute \
  --archive /private/neo-backups/neo4j.dump \
  --manifest /private/neo-backups/neo4j.backup-manifest.json \
  --minimum-nodes 100 --minimum-passages 20 --minimum-constraints 1 \
  --output /private/neo-backups/service-smoke.restore-drill.json \
  --ack-private-restored-smoke
```

Thresholds above are **illustrative**: the operator must substitute
credible recorded baseline minima. Even matched minima alone cannot prove
that every original record survived; a trusted source baseline snapshot,
IDs/edge provenance equivalence and independent saved data-revision
verification remain unimplemented.

If a query, timeout, checksum or cleanup fails, there is no successful
receipt. The CLI suppresses potentially sensitive Docker errors and prints
only aggregate values. Successful reports explicitly state
`verified_against_trusted_live_baseline=false` and
`rpo_rto_demonstrated=false`. The measured elapsed time is only the
duration of this particular test run, **not a demonstrated RTO**.

## Limitations and blockers

This does not prove original dump creation time, retention/off-site
recovery, schema equality versus a trusted external baseline, RPO <=24h,
RTO <=4h, restored app-layer permissions or licensed source rights.
The result is **unsigned**. No private real dump has been restored during
development; the focused tests are synthetic and mock Docker subprocesses.

The PR remains Draft/HOLD, stacked on v0.13.1. Upstream review/security,
source-rights, actual restore and operational sign-off gates must clear
before `main` merge or production claims.

Focused tests:
`python -m unittest tests.test_restored_service_smoke_v0132 -v`.
Contract:
`docs/integrations/RESTORED-SERVICE-SMOKE-v0.13.2.json`.

Official references:
- https://neo4j.com/docs/operations-manual/current/docker/dump-load/
- https://neo4j.com/docs/operations-manual/current/cypher-shell/
