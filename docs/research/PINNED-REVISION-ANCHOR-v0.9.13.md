# v0.9.13 — Separately pinned audit revision-chain anchor

## Why this is needed

The v0.9.12 metadata ledger is a SHA-256 linked sequence of observed,
HMAC-verified Work-pair exports. A privileged database writer could
replace the whole chain and recompute its internal hashes. v0.9.13
introduces a **checkpoint whose digest is signed with a separate
operator-controlled Ed25519 key and verified against a pinned public
key**. It can detect a rewrite of the anchored prefix when compared to
a later database observation. It does not make the database immutable.

## Four local operations

The operator must first have a valid v0.9.12 ledger for one directed
canonical source_work_id and target_work_id pair. The application
does not automatically sign or upload any research data.

1. **capture** (read-only Neo4j): validate all 0..32 metadata
   revisions and save a private checkpoint with scope, sequence,
   last revision ID, chain SHA-256, capture timestamp, and mandatory
   false flags for source immutability, snapshot, licensing and archive
   claims.
2. **sign** (offline): sign the canonical UTF-8 checkpoint with an
   explicitly supplied 32-byte raw Ed25519 key in a regular file mode
   0600, storing only the detached signature and checkpoint, never
   key material. This application neither generates nor commits
   a private signing key.
3. **verify** (offline): verify the signature against an explicitly
   pinned public-key policy. The policy binds a signer ID and its
   Ed25519 public key to the exact directed Work-pair scope.
4. **compare** (read-only Neo4j): verify signature/policy first, then
   validate the full current chain. For a historical checkpoint,
   confirm that its signed sequence/revision/hash still occurs at
   the same position. Additional valid later appends are allowed.
   An anchored rollback, rewrite or hash mismatch is rejected.

CLI examples, with private files managed by the authorized operator:

    python scripts/audit_revision_anchor_v0913.py capture \
      --source-work-id 'work:<canonical-id>' \
      --target-work-id 'work:<canonical-id>' \
      --output private/audit-anchor.json

    python scripts/audit_revision_anchor_v0913.py sign \
      --anchor private/audit-anchor.json \
      --signer-id archiver-primary \
      --private-key private/operator-ed25519.raw \
      --output private/audit-anchor.signed.json

    python scripts/audit_revision_anchor_v0913.py verify \
      --signed private/audit-anchor.signed.json \
      --policy private/trusted-audit-signers.json

    python scripts/audit_revision_anchor_v0913.py compare \
      --signed private/audit-anchor.signed.json \
      --policy private/trusted-audit-signers.json

All output paths must be new files and are created privately, never
overwriting an existing checkpoint. The key must be 32 raw Ed25519
bytes (not an OpenSSH/PEM wrapper). File material and signer trust
policy must be provisioned and managed outside the GitHub repository.
Never log private keys or signed Work metadata.

## Trust policy

The offline pin file has this shape (illustrative **not** a real key):

<escape>{
  "schema_version": "0.9.13",
  "trust_status": "OPERATOR_PINNED_IDENTITY_NOT_ATTESTED",
  "signers": [{
    "signer_id": "archiver-primary",
    "role": "audit_revision_operator",
    "scope_id": "audit-scope:<64 lowercase hex digits>",
    "ed25519_public_key_b64": "<standard base64 of 32 raw public key bytes>"
  }]
}</escape>

Signer identifiers must be unique, and a policy can contain at most
eight signers. The verifier rejects unknown signatures, scope changes,
policy field substitutions, duplicate signer entries and fabricated
verification/release flags. A matching signature proves possession
of the relevant key, **not** that the claimed institution identity
was independently vetted.

## Exact security scope

The checkpoint is limited to an observed **metadata ledger prefix**.
A single valid signed anchor, held outside the database, makes that
prefix *tamper-evident on subsequent comparisons*, subject to
trustworthy handling of the pin file and private signing key. It
does **not** freeze the Work/Passage/Evidence nodes, establish an
end-to-end immutable archival object, prevent changes between
observations or prove a consistent snapshot of the underlying graph.

No AWS S3 write, retention verification, Object Lock claim, IAM/SCP
audit or provider attestation is performed in v0.9.13. The existing
v0.8.14–v0.8.16 independent archive validation modules remain
separate and are not falsely presented as completed for these ledger
checkpoints. The release status is explicitly HOLD.

## Verification and remaining work

Fifteen focused unit/CLI tests cover nonempty/empty signed prefixes,
legitimate later appends, rollback and tamper detection, key and
signer policy denial, scope binding, unsupported release flags and
strict key-file permission checks. CI also generates a temporary
Ed25519 key **only in memory**, signs a synthetic one-record revision
checkpoint, appends another synthetic record in disposable Neo4j,
checks that the anchored prefix survives, refuses a falsified digest,
and cleans the exact generated metadata nodes. It archives only
boolean/count evidence for seven days, never keys or source records.

Required before public research release: independent trust-identity
review, actual durable external anchor storage and retention proofs,
key lifecycle, governed DB write identities, revision-aware Work data
updates, verified source and edition rights, scholarly review,
DvirOS SSO/RBAC, and realistic performance evidence.
