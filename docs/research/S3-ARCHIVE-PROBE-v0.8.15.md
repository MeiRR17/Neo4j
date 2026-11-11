# v0.8.15 — Version-scoped AWS S3 checksum and retention probe (DRAFT)

The preceding v0.8.14 verifier authenticates **only** the bytes of an
operator-pinned Ed25519 signature over a supplied S3 report *claim*.
This version adds an explicitly opt-in, read-only AWS S3 API observation,
**only after** the signed claim and v0.8.11–0.8.13 retained-source evidence
have been verified. No real archive data, AWS accounts or keys are committed.

## Exact acceptance boundary

1. Require an explicit 12-digit ExpectedBucketOwner and an AWS region;
   create an AWS SigV4 SDK client with TLS, fixed standard endpoint and
   disabled endpoint overrides from environment or profile.
2. HEAD the claimed **exact** Bucket/Key/VersionId with
   ChecksumMode=ENABLED and ExpectedBucketOwner. Require HTTP 200, matching
   VersionId and ContentLength, and ChecksumType=FULL_OBJECT.
3. Compare the canonical base64 ChecksumSHA256 (the complete **256-bit** SHA-256)
   to both the Ed25519-signed archive report and locally rehashed original
   source-file receipt. Do not substitute ETag or multipart COMPOSITE digest.
4. Require HeadObject ObjectLockMode and ObjectLockRetainUntilDate to match
   the signed report, with unexpired retention at check time.
5. Issue a *separate read-only* GetObjectRetention on the same exact
   object version and ExpectedBucketOwner. Both retention API fields must
   agree exactly with the HEAD response and signed claim.
6. On missing metadata, conflicting version, different bytes, absent Object
   Lock fields, expired retention, access denial, SDK failure, invalid
   timestamp or output collision: fail closed; do not emit a report.
7. On full success, write a private mode-0600 result **without S3 bucket,
   key, source text, object URL, credentials or raw provider response**.

Example, in a trusted operator environment with read-only AWS credentials:

    python -m pip install -r requirements/s3-archive-probe.txt
    umask 077
    python scripts/s3_archive_probe.py \
      --source-file /private/links0.csv \
      --source-record /private/source_record.json \
      --receipt /private/source_receipt_v0812.json \
      --witness /private/source_witness_v0813.json \
      --capture-manifest /private/capture_manifest_v0811.json \
      --trusted-policy /private/pinned_archive_trust.json \
      --archive-report /private/archive_claim.json \
      --signed-statement /private/archive_statement.json \
      --aws-region us-east-1 \
      --expected-bucket-owner 123456789012 \
      --output /private/archival_s3_result.json

The account number in the example is *illustrative*, never a trust root.
`--local-key-file` optionally overrides the local v0.8.11-13 HMAC key
path. Use restrictive IAM rights:
`s3:GetObjectVersion`, `s3:GetObjectRetention`, and (when applicable)
KMS decrypt permission to read object checksums. No PutObject, GetObject
body, retention changes or bucket modifications are performed.

## Important boundaries: observed metadata is not immutable history

A successful result means an authenticated AWS SDK response, **under the
operator's configured credential/endpoint trust assumptions**, was
consistent with the signed claim, local checksum, version ID, and currently
reported retention. It is **not** an independent cryptographic notarization
of the object's prior history or a proof of future custody.
S3 GOVERNANCE retention may be bypassed by privileged parties; even
COMPLIANCE metadata alone is not an independent audit of remote custody,
operator identity, legal redistribution rights or research quality.

`external_archive_immutability_verified`,
`signer_organization_identity_independently_verified`,
`source_rights_verified`, and
`neo4j_snapshot_isolation_verified` remain FALSE. Research release HOLD.
Tests use only in-memory fake responses and ephemeral keys, with no AWS
credential/network requirement. The PR remains draft and stacked on v0.8.14.

AWS contracts:
- https://docs.aws.amazon.com/AmazonS3/latest/API/API_HeadObject.html
- https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/get_object_retention.html
