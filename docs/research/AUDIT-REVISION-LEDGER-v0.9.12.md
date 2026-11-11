# v0.9.12 — Audit observation revision ledger (DRAFT)

## What changed

The v0.9.11 export attests two equal bounded reads of metadata for one
directed Work pair. v0.9.12 lets a *separately approved local operator*
record that validated receipt in a monotonically numbered metadata
revision ledger. It does **not** copy source text or modify scholarly
Work/Passage/Evidence data.

Neo4j schema migration 005 adds:
- unique AuditRevisionHead.id (one head per directed Work pair)
- unique AuditRevision.id (a digest-bound observation record)
- a scope_id/sequence lookup index to bound verification

All DDL is CREATE ... IF NOT EXISTS, and the existing migration checksum
logic continues to reject marker drift. Production authorization
continues to require a separately governed writable DB principal.

## Single-statement CAS append

The Work scope ID is a SHA-256 of the ordered canonical Work pair;
reversing source and target creates a different history. Before each
write, the service verifies the entire v0.9.11 export digest and HMAC
using the existing local protected bearer token. Forged documents,
wrong scope, unexpected fields or false rights/snapshot claims fail
before any Neo4j write.

Bootstrap uses MERGE and can return an existing head without clearing
its history. An append first checks the expected sequence and full
64-digit chain digest. The one fixed parameterized Cypher statement
locks the head with a no-op SET, rechecks expected sequence, digest,
previous revision ID and Work scope, creates one new AuditRevision
node and advances the single head. The uniqueness constraints and
per-head lock provide *cooperating-writer* stale-head rejection.
There is no user-supplied Cypher.

Each persisted record contains only work scope, sequence, previous
revision/digest, v0.9.11 export manifest digest, query-template
digest, captured/recorded timestamps and observed link count.
Its SHA-256 over canonical record fields and domain prefix becomes
both the chain digest and content-derived revision ID. The head
points to the last revision. No passage text, evidence excerpts,
bearer tokens or graph query results are stored in this ledger.

A local verifier reads at most 33 history rows and refuses scopes with
more than 32 revisions, missing/duplicated sequence numbers, digest
drift or a mismatched head. This is a deliberately bounded early
revision protocol; it is not a full archival storage service.

## Local workflow

Validate the private downloaded v0.9.11 JSON export without a DB write:

    python scripts/audit_revision_ledger_v0912.py plan \
      --input private-audit-export.json

Use only on a separately authorized local research database. The
explicit production-mode guard is disabled by default. An authorized
operator must intentionally set DVIROS_AUDIT_REVISION_WRITE_ENABLE=1
and pass --ack-metadata-write. Example after approval:

    DVIROS_AUDIT_REVISION_WRITE_ENABLE=1 \
      python scripts/audit_revision_ledger_v0912.py bootstrap \
      --input private-audit-export.json --ack-metadata-write

The bootstrap output gives the current sequence and chain digest.
Append only with those *exact* expected values, for example for an
empty head (sequence 0 and 64 zeroes):

    DVIROS_AUDIT_REVISION_WRITE_ENABLE=1 \
      python scripts/audit_revision_ledger_v0912.py append \
      --input private-audit-export.json --ack-metadata-write \
      --expected-sequence 0 \
      --expected-chain "$(printf '0%.0s' {1..64})"

After append, use the reported new sequence and digest for the next
revision. A stale expected head aborts the append. Verify the stored
chain with the same private export:

    python scripts/audit_revision_ledger_v0912.py verify \
      --input private-audit-export.json

This CLI defaults to loopback Neo4j and local secret files; it has no
remote public endpoint. The CI fixture path separately requires
CI=true, --ack-metadata-write and --ack-disposable-fixture. Missing
approval returns a blocked status before credentials or DB writes.

## Security and research limitations

- No complete source graph is frozen: another ingest job may edit the
  actual Work, Passage or Evidence nodes after an observed export.
- Privileged database accounts can rewrite/delete ledger nodes and
  recompute hashes; neither UNIQUE constraints nor CAS make storage
  WORM. A separately trusted external archive/anchoring mechanism
  and DB permissions would be needed for stronger immutability.
- v0.9.11's two consecutive reads were not one transaction snapshot;
  this ledger does not upgrade that guarantee.
- The bearer-key HMAC attests local-key possession only. Key rotation
  and independent public verification remain future work.
- Stored rights tags and review statuses are not legal rights approval
  or scholarly verification. DvirOS RBAC/SSO, representative performance,
  genuine sources, 100+ expert-reviewed links and 20 independently
  audited analyses remain required.
- No production release or research approval is authorized. HOLD.

Twelve targeted tests cover signed-export and scope validation,
idempotent bootstrap, multiple append/verify, stale CAS, tampering,
32-record capacity and CLI denial paths. Disposable CI runs real
Neo4j migration and ledger write/cleanup smoke without real-source
mutations, and archives an aggregate synthetic result for seven days.
