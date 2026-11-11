# v0.8.14 — Pinned Ed25519 archive-claim verification (DRAFT)

Version 0.8.13 proved a particular locally rechecked SourceRecord was
present in a bounded HMAC-protected metadata projection. A local HMAC
alone does NOT independently authenticate an external source provider.

Version 0.8.14 adds verification of a separately supplied **Ed25519**
signature from an archive-operator key which the deployer has already
pinned in a local trust policy. Cryptographic signature validity verifies
the signed bytes for that key, NOT who controls the key in the real world.

## Data formats

1. Trusted-policy JSON: schema_version 0.8.14,
   trust_status OPERATOR_PINNED_IDENTITY_NOT_ATTESTED,
   signers (1..8), each with signer_id, role archive_operator,
   archive_namespace and ed25519_public_key_b64 (32-byte raw key).
   Policy must be created and validated separately by the operator;
   never accept a trust policy from the untrusted signed statement.
2. S3 report JSON: schema_version 0.8.14, provider s3_object_lock,
   bucket, object_key, version_id, content_sha256, content_length,
   object_lock_mode COMPLIANCE or GOVERNANCE, retain_until_utc, and
   evidence_origin operator_supplied_unverified. This is an operator
   **claim**, NOT an actual AWS API response or independent WORM proof.
3. Signed-envelope JSON: statement plus signature_b64. Statement binds
   exact source_record_id, SHA256 hashes of source receipt, source
   witness, capture manifest, archive report, issue time, pinned signer
   ID/namespace, purpose archival_operator_attests_report_claim, and
   explicit source/provider non-approval/HOLD flags. Signature input is
   domain-separated ASCII prefix neo4j-external-archive-attestation-v0.8.14
   followed by newline and canonical UTF-8 indented JSON ending newline
   (the scripts.search_capture.encode function).

No signing key, example trusted root, fake provider certificate or
production attestation has been committed. Synthetic tests create fresh
ephemeral Ed25519 keys and destroy them when the test exits.

## Offline verification example

First install the pinned offline dependency using
`pip install -r requirements/provenance-attestation.txt`.

Supply private, independently sourced files (not example approvals):

    umask 077
    python scripts/external_archive_attestation.py \
      --source-file /private/links0.csv \
      --source-record /private/source_record.json \
      --receipt /private/source_receipt_v0812.json \
      --witness /private/source_witness_v0813.json \
      --capture-manifest /private/capture_manifest_v0811.json \
      --trusted-policy /private/pinned_archive_trust.json \
      --archive-report /private/archive_claim.json \
      --signed-statement /private/archive_statement.json \
      --output /private/archival_attestation_result.json

Optional --local-key-file supplies the existing 0600 local DvirOS HMAC
secret. The verifier does not perform HTTP requests, browse S3, sign
anything or create a new trusted identity. Its verification report is
created once at mode 0600, without including bucket/key names,
source text, credentials, public/private signing keys or source URIs.

## Exactly what is and is not proven

- Proven by successful verification: the configured public key validates
  the signature over the exact statement and its SHA256-linked source,
  receipt, witness, local source bytes and archive-report *claim*.
- NOT proven: that the pinned key belongs to the named organization;
  that S3 object/version actually exists, is encrypted or is locked;
  that AWS retained it for the claimed term; that the remote source was
  authentic; that a publisher authorized redistribution; or that
  Neo4j graph data was transactionally immutable. No third-party
  timestamp or independent revocation check is available.
- A local policy compromised by an attacker can authorize their key.
  Even an authentic archive-operator signature cannot substitute for
  verified provider delivery, rights review, a write-frozen corpus
  snapshot, DvirOS SSO/RBAC or 50 real scholarly reviewed queries.

All production/research approval flags remain false and the release
continues to be HOLD. The PR is stacked, draft and not merged to main.
