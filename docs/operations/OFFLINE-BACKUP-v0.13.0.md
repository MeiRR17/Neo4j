# v0.13.0 — Offline Community database dump integrity (Neo-only; DRAFT)

## First operational milestone: integrity, not a restore certificate

Neo uses local Docker Compose with a **pinned** `neo4j:2026.10.1`
Community image and a persistent named `neo4j_data` volume. The v0.13
roadmap requires recoverable backups and an isolated restore drill before GA.
This increment adds a **real integrity-manifest producer and verifier** for
one existing, private, operator-generated `neo4j` database `.dump`
archive. It requires no Neo4j credentials and performs **no database read,
stop, dump, load, data deletion, container execution or restore**.

The tool cannot inspect whether a supplied blob is a valid Neo4j archive.
A green SHA256 check establishes only that the *same bytes* are present.
It does **not** establish database consistency, source authenticity, proper
offline database stop, recoverability, RPO/RTO, corpus completeness, or
scholarly source/edition rights. These distinctions are explicit in both
the manifest and result. Never call this a verified restore.

Neo4j officially documents `neo4j-admin database dump` and
`neo4j-admin database load` for offline Community databases. See
https://neo4j.com/docs/operations-manual/current/docker/dump-load/ .
Unlike Enterprise online backup, Community offline dump requires a
stopped database; never run dump against the live Compose volume.

## Safe operator sequence

1. Schedule downtime; record the planned stop and the time of the most recent
   committed import. Privately confirm that the correct `neo4j` database
   has fully stopped and that no other container/process is using the
   persistent data volume. Running `docker compose stop neo4j` alone
   is not independently validated by this script.
2. Use the official **offline dump** procedure and the **matching pinned
   Neo4j admin image version** with the correct named data volume.
   The `.dump` must be written to a separate owner-only private backup
   directory, **not** to the live `/data` volume. Check available disk space,
   volume identity, actual file ownership and successful admin exit status.
   Do **not** use `docker compose down -v`; it deletes named volumes.
3. Copy the finished dump to a host directory that is owner-only
   (`chmod 700 /private/neo_backups`). The `.dump` file must be an ordinary
   single-link file with mode `0600`, not a symlink/hardlink, and must have
   a bounded basename such as `neo4j-2026-11-18.dump`.
4. With the database stopped and archive already fully closed, execute
   `manifest` **once** with explicit operator attestation:

```sh
python scripts/offline_backup_v0130.py manifest \
  --archive /private/neo_backups/neo4j-2026-11-18.dump \
  --output /private/neo_backups/neo4j-2026-11-18.backup-manifest.json \
  --operator-stopped-db
```

5. Before copying the archive to offline storage and again before attempting
   a restore, independently verify the exact private bytes:

```sh
python scripts/offline_backup_v0130.py verify \
  --archive /private/neo_backups/neo4j-2026-11-18.dump \
  --manifest /private/neo_backups/neo4j-2026-11-18.backup-manifest.json \
  --expected-image neo4j:2026.10.1
```

Both commands print only bounded results and **do not print the private
backup path, credentials, graph records, source text or local usernames**.
The manifest is canonical JSON, created once using exclusive owner-only
file creation; existing files are never overwritten. The reader rejects
noncanonical JSON, duplicate keys, weak POSIX file/parent permissions,
symlinks, hardlinks and unsupported image tags. Archive hashing is chunked
(1 MiB), bounded to 512 GiB, and verifies descriptor identity/size/change
timestamps against the on-disk path before accepting a digest.

`--operator-stopped-db` means the **operator states** the database was
stopped; the software cannot prove it. The tool does not enforce host
firewalls/ACLs on Windows; those require explicit review.

## Restore drill — still pending

An independent operator must load the checked dump with
`neo4j-admin database load` into a **separate, empty, isolated data
volume/container**, with the matching Neo4j version. Never allow a
verification exercise to overwrite the original `neo4j_data` volume,
existing `secrets/` or active database. Use the official Neo4j Docker
offline load procedure above and run the existing authenticated smoke,
migration/schema check and read-only count/provenance audit **against the
isolated restored instance**. Capture start/end, data version, source
count/constraints, auth isolation and recovery metrics as private evidence.

Only after a successful, independently recorded isolated restore can
operations evaluate the roadmap's pilot targets of **RPO <=24 h** and
**RTO <=4 h**. This v0.13.0 checksum phase sets
`isolated_restore_drill_passed=false`,
`database_stop_independently_verified=false`,
`dump_format_verified=false`, `rpo_rto_demonstrated=false`, and
`research_release_status=HOLD` without exception.

The SHA256 manifest is **not HMAC-signed**, not a trusted timestamp, not
a backup of the existing private service/Neo4j credentials, and not a
durable off-machine copy. Both archive and manifest should be protected
from unauthorized edits and stored off-host under an approved retention
policy, to be implemented in v0.13.x. Do not commit real dumps or
private manifests to GitHub; the ignore rules cover the dedicated
`private_backups/` directory and common dump/manifest suffixes.

Focused check, using synthetic bytes rather than pretending to test a
valid Neo4j dump:

```sh
python -m unittest tests.test_offline_backup_v0130 -v
```

Machine-readable contract:
`docs/integrations/OFFLINE-BACKUP-INTEGRITY-v0.13.0.json`.
