# v0.8.15 — Exact AWS S3 object-version and retention verification (DRAFT)

This adds a **live, opt-in, read-only S3 metadata audit** to v0.8.14's
operator-signed archive claim. It requires the complete v0.8.11–v0.8.14
research source chain to verify locally BEFORE making AWS requests.

## AWS read contract

The CLI uses a named AWS SDK profile, a region on a fixed AWS HTTPS
endpoint, and an explicit 12-digit ExpectedBucketOwner account ID.
No alternate endpoint URL is accepted from CLI options. Credentials are
resolved by the named SDK profile and are never logged or written to Git.

Exactly two S3 read-only requests are made for the **same** claimed
Bucket/Key/VersionId and ExpectedBucketOwner:

1. `head_object(ChecksumMode='ENABLED')`: requires HTTP 200, returned
   VersionId match, no delete-marker, matching ContentLength,
   ChecksumType=FULL_OBJECT and ChecksumSHA256. The base64 checksum must
   decode to the exact raw SHA256 of the locally rechecked source file.
   We do NOT treat ETag as SHA256; multipart composite checksums are
   incompatible with direct full-file SHA256 and fail closed.
2. `get_object_retention`: requires HTTP 200, Mode=COMPLIANCE,
   RetainUntilDate matching both the HEAD response and the signed archive
   claim. The retention expiry must be later than the inspection time.
   Governance mode is deliberately rejected because retention can
   be bypassed by appropriately authorized principals.

These calls use only exact object version reads, never list/download,
upload, delete, lock modification or full source-text retrieval.
Both requests need S3 version/retention permissions; checksum reads
on KMS-encrypted versions may also require KMS decrypt permissions.

## Operator setup and CLI

Provision and authorize a named AWS profile through your normal IAM/SSO
process. Recommended least privileges are s3:GetObjectVersion and
s3:GetObjectRetention, restricted to the specific versioned metadata
object(s) and a known account ID; allow kms:Decrypt only if required.
Do not give PutObject, DeleteObject, BypassGovernanceRetention or
unscoped listing permissions. Install the pinned optional SDK:

    python -m pip install -r requirements/provenance-attestation.txt
    python -m pip install -r requirements/aws-s3-audit.txt

Run the audit on an authorized operator host with separately provided
source record, v0.8.12 receipt, v0.8.13 witness, v0.8.11 capture
manifest, v0.8.14 signed statement, and the archive metadata claim.

    umask 077
    python scripts/live_s3_version_verify.py inspect \
      --source-file /private/links0.csv \
      --source-record /private/source_record.json \
      --receipt /private/source_receipt.json \
      --witness /private/source_witness.json \
      --capture-manifest /private/capture_manifest.json \
      --trusted-policy /private/archives_trusted_keys.json \
      --archive-report /private/signed_object_report.json \
      --signed-statement /private/ed25519_statement.json \
      --aws-profile research-archive-readonly \
      --aws-region il-central-1 \
      --expected-bucket-owner 123456789012 \
      --ack-live-aws-read-only \
      --output /private/s3_version_observation.json

The tool writes a local mode-0600 observation containing SHA256
fingerprints of the exact source chain, request IDs, region, expected
owner, object version, content and observed retention, plus an HMAC.
No bucket name, object key, credentials, source text or raw account ID
is put into that observation.

The `verify` subcommand accepts the same local file arguments, region
and bucket owner, replacing `--aws-profile`, acknowledgment and output
with `--observation /private/s3_version_observation.json`. This is
**offline tamper verification only**, not a fresh AWS recheck. For
current storage state, rerun `inspect` with a NEW output path.

## Conditions and limits

- The existing pinned-key signature (v0.8.14) validates a separately
  operator-provided object report. It does NOT authenticate the real
  signer organization. The new S3 requests test whether AWS reports
  an exact matching version/checksum/retention at inspection time.
- `ChecksumType=FULL_OBJECT` is mandatory; if S3 omitted a full-file
  SHA256 or the account disallows checksum metadata, fail closed.
- Retention must be `COMPLIANCE`, not `GOVERNANCE`; HEAD and retention
  responses must agree. This supports an observed lock, not proof
  that the entire archive is permanently immutable or independently
  audited. S3 configuration, policy, AWS trust and time remain external.
- Exact VersionId is required for all calls; changing the current
  latest version does not silently switch the object being inspected.
- The AWS SDK observation report is authenticated only by a **local
  HMAC**, not an independently signed AWS receipt or trusted timestamp.
  An attacker with the HMAC key can forge it.
- The underlying research graph remains a bounded API observation,
  not a snapshot-isolated corpus. Provider authenticity and legal
  redistribution rights remain unverified. The scholarly 50-question
  Precision@5 gate and production DvirOS SSO/RBAC remain open.

## CI isolation

Unit tests inject synthetic S3 objects and exercise strict SDK method
names/parameters, expiration, COMPOSITE checksums, wrong versions,
mismatched size, inconsistent lock mode and forged evidence. The
isolated real-Neo4j integration smoke uses a **fake S3 client**; there
are no AWS credentials, live AWS requests or actual Object Lock attestations.

Research release: **HOLD**. PR remains draft; no main merge.
