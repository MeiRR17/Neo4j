# v0.13.1 — Isolated Neo4j offline restore load + consistency drill

**Operator-only, explicit opt-in.** This Neo-only tool extends the v0.13.0
offline dump SHA256 manifest to perform an **actual load + offline consistency
check into a newly created, random Docker volume** when its `execute` mode
is invoked on a host with Docker and the matching admin image.

It does not touch the live Compose instance, live `neo4j_data` volume,
`secrets/` files, use host paths for restored data, publish ports, connect to
a network or use a DvirOS API. It does not run in CI against a real archive.
An *offline* consistency check is **not** an authenticated service start,
application-schema/graph provenance review, 24h RPO or 4h RTO demonstration.

## Prerequisites and safe sequence

1. Independently prepare a *valid* Neo4j Community offline `neo4j.dump`
   with the repository's pinned database image `neo4j:2026.10.1`;
   the database must be stopped before dumping. Never use
   `docker compose down -v`. Follow the official
   [Neo4j offline Docker dump/load documentation](https://neo4j.com/docs/operations-manual/current/docker/dump-load/).
2. Store the source dump in an owner-only directory (0700) with a 0600
   file. Use v0.13.0 to create and verify its private SHA256 manifest. A
   SHA256 match only proves the bytes were not changed since the manifest
   was created, not the validity of the archive or provenance of its author.
3. Pre-pull the matching **official admin image** explicitly as a trusted
   operator: `docker pull neo4j/neo4j-admin:2026.10.1`. The tool itself
   uses `--pull never`, never downloads arbitrary images, and requires
   Docker Engine permissions. The tag is pinned, but not digest-pinned.
4. Before any Docker calls, run the default plan stage:

```sh
python scripts/isolated_restore_drill_v0131.py plan \
  --archive /private/neo-backups/neo4j.dump \
  --manifest /private/neo-backups/neo4j.backup-manifest.json
```

5. Only on an authorized host with enough disk capacity and no requirement
   to retain the temporary restored volume, run the explicitly acknowledged
   step below. It can be I/O intensive:

```sh
python scripts/isolated_restore_drill_v0131.py execute \
  --archive /private/neo-backups/neo4j.dump \
  --manifest /private/neo-backups/neo4j.backup-manifest.json \
  --output /private/neo-backups/drill.restore-drill.json \
  --ack-isolated-volume
```

The output is created once with mode 0600, canonical JSON and SHA256 checksum;
it is *unsigned* and kept off GitHub in private backup storage. Real archives,
manifests and reports must not be committed.

## Isolation and recovery behavior

The implementation verifies **the complete v0.13.0 manifest and source file
bytes** before the first Docker call. It selects a randomly named temporary
Docker volume with the `dviros-neo-restore-drill-` prefix and explicit label,
refuses known existing names, and runs two fixed commands using
`neo4j/neo4j-admin:2026.10.1`, `--network none`,
`--pull never`, no published ports, no Compose project and no binds to any
live host database:

1. `neo4j-admin database load neo4j --from-stdin`. The verified `.dump`
   is streamed through the container's stdin in 1 MiB chunks to avoid
   mounting the backup directory as writable.
2. `neo4j-admin database check neo4j`. This checks the restored
   offline volume independently of the application API.

Both operations are bounded by configured timeouts (2h load, 30m check);
the commands are invoked with argument arrays, **never a shell**, and their
possibly sensitive stdout/stderr are suppressed. Afterward the original
archive and private manifest are reverified, and the temporary Docker
volume is removed. The tool attempts cleanup on failures as well. Failure
of load, consistency check or cleanup produces no successful private report.

A successful report records that the *offline load and consistency check*
completed on an isolated newly created volume and that the volume was
removed. It also explicitly sets
`authenticated_restored_service_smoke_passed=false`,
`end_to_end_restore_drill_passed=false`,
`rpo_rto_demonstrated=false`, `research_release_status=HOLD`.

**Critical limitation:** There is no independent authenticated
`RETURN 1` or graph migration/schema/provenance check against a
running restored Neo4j DBMS. This release cannot claim a complete restore
drill or promote an unsigned report to production approval. It does not
record a trusted backup creation timestamp, application/corpus revision,
historical import point, external storage proof or release authorization.

## Follow-up release gates

Later v0.13.x work must start a **separate non-public restored DBMS** from
the isolated volume, authenticate the recovery session, validate
constraint/schema and non-sensitive source counts, measure actual time
to restore service, reconcile committed data age to RPO, and record signed
operator evidence. Only then can the roadmap's pilot RPO <=24 hours and
RTO <=4 hours be considered. The historical P0/P1 scholarly rights and
security gates and upstream Draft PRs remain HOLD.

Focused test (synthetic data + mocked Docker, no real DB restore):
`python -m unittest tests.test_isolated_restore_v0131 -v`.

Contract:
`docs/integrations/ISOLATED-RESTORE-DRILL-v0.13.1.json`.
