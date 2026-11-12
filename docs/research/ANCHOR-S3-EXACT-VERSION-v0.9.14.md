# v0.9.14 — Signed audit-anchor S3 version and retention verification

## What this implements

A v0.9.13 Ed25519-signed checkpoint protects the hash of one bounded
revision-ledger prefix. This version can verify that the **exact
signed JSON file bytes** were retained as one explicitly named AWS S3
object version with a FULL_OBJECT SHA-256 checksum and COMPLIANCE
Object Lock retention. There is **no automatic S3 upload**.

The operator prepares an archive binding with exactly these fields:
schema_version = 0.9.14; provider = aws_s3; bucket; object_key;
version_id (actual non-null VersionId); expected_bucket_owner
(12-digit AWS account); aws_region; content_sha256 (64 lowercase hex);
content_length (signed file byte count); minimum_retain_until_utc
(strict UTC timestamp, e.g. 2030-01-01T00:00:00Z); and
evidence_origin = operator_pinned_unverified.

The binding is supplied privately, not written to the repository.
Pin data must come from an authorized archival operator. A valid
signature for *another* JSON file is explicitly rejected; the same
signed envelope must be parsed from the exact byte stream.

## Live read-only inspection

Provide a separately authorized AWS SDK profile, pinned v0.9.13
public-key policy, local protected HMAC token and a binding file.
Run the following command after provisioning a real archive version:

    python scripts/audit_anchor_s3_v0914.py inspect \
      --signed-anchor private/checkpoint.signed.json \
      --trusted-policy private/audit-signers.json \
      --archive-binding private/s3-anchor-binding.json \
      --local-key-file private/research-observation-key \
      --aws-profile archive-readonly \
      --ack-live-aws-read-only \
      --output private/anchor-s3-observation.json

No remote call begins until signature, scope, raw file bytes, pinned
hash, length, retention and the local key pass validation. The fixed
AWS calls are:
(1) head_object with explicit bucket, object key, VersionId,
ExpectedBucketOwner and ChecksumMode ENABLED;
(2) get_object_retention with the same four pinned parameters.

Require a successful HTTP 200 and request IDs for both. The returned
VersionId and ContentLength must agree exactly with the local file.
HEAD must expose ChecksumType FULL_OBJECT and a matching SHA-256,
ObjectLockMode COMPLIANCE and retention timestamp. The separate
retention response must also be COMPLIANCE with the same UTC expiry,
at or after the operator's future retention minimum. GOVERNANCE,
null versions, composite checksums and missing data are rejected.

No S3 object download, upload, deletion, new endpoint configuration,
policy write or provider admin action is permitted by this tool.

## Offline observation check

The saved output is HMAC-sealed using the separately provided local
protected service token. It contains hashed account/version/binding
identifiers, sanitized AWS request ID digests and result flags;
it does not publish the raw S3 bucket, key, version, credentials or
source excerpts. Revalidate later with no AWS connection:

    python scripts/audit_anchor_s3_v0914.py verify \
      --signed-anchor private/checkpoint.signed.json \
      --trusted-policy private/audit-signers.json \
      --archive-binding private/s3-anchor-binding.json \
      --local-key-file private/research-observation-key \
      --observation private/anchor-s3-observation.json

A valid saved observation records what its original SDK calls
observed at one instant. Offline verification **does not make new
AWS calls** and does not re-attest today's remote retention state.

## CI evidence and missing approvals

Thirteen focused security tests use synthetic signed Ed25519
checkpoints and a mocked S3 client. CI validates the two exact
read-only calls, SHA-256/byte length, retention, signature, pin
binding, denial behavior and local HMAC verification. Its saved
seven-day artifact explicitly states real_aws_account_contacted =
false and s3_object_lock_provider_independently_observed = false.
No real S3 credentials or bucket configuration is assumed.

This does not establish permanent external immutability, provider
account ownership governance (STS/IAM/SCP), organization signer
identity, a Neo4j graph transaction snapshot, lawful source rights,
scholarly review or research/public release. Existing v0.8.16
bucket-governance controls can be applied only after an authorized
real-account read and independent identity assessment. HOLD.
