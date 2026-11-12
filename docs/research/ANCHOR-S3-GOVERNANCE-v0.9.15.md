# v0.9.15 — Signed audit-anchor S3 / STS governance

## Purpose and prerequisites

v0.9.14 verifies a precise AWS S3 object version of a v0.9.13
Ed25519-signed, bounded Neo4j audit ledger anchor. It only checks
HEAD/FULL_OBJECT checksum and object-level COMPLIANCE retention.
v0.9.15 expands this *point-in-time* observation to the caller's
AWS account and four bucket security-control responses. It reuses
the existing v0.8.16 STS/bucket checks without confusing a signed
source-media artifact with this different signed audit-anchor file.

An operator must first independently establish all private inputs:
signed checkpoint JSON bytes, pinned Ed25519 public-key policy,
S3 operator binding with explicit bucket/object/version/account/
region, and a separate protected local observation HMAC token.
Neither S3 account credentials nor private key files are stored
in GitHub.

## Opt-in live inspection

    python scripts/audit_anchor_governance_v0915.py inspect \
      --signed-anchor private/checkpoint.signed.json \
      --trusted-policy private/audit-signers.json \
      --archive-binding private/s3-binding.json \
      --local-key-file private/local-observation-token \
      --aws-profile archive-readonly \
      --ack-live-aws-read-only \
      --output private/anchor-governance.json

The tool validates all local signed-file and exact-VersionId pins
before creating the existing fixed HTTPS AWS SDK session. Successful
inspection issues precisely these seven read-only operations:

1. S3 HeadObject with explicit VersionId, ExpectedBucketOwner,
   ChecksumMode ENABLED and mandatory matching FULL_OBJECT SHA-256.
2. S3 GetObjectRetention with the same explicit object version;
   HEAD and retention responses must agree on COMPLIANCE and future
   retention above the independently pinned minimum.
3. STS GetCallerIdentity; Account must match the pinned owner, ARN
   must describe an IAM user or assumed role of that account.
4. S3 GetBucketVersioning; Status must be Enabled.
5. S3 GetPublicAccessBlock; all four block flags must be True.
6. S3 GetBucketPolicyStatus; IsPublic must explicitly be False.
7. S3 GetObjectLockConfiguration; ObjectLockEnabled must be Enabled.

All bucket-control calls use the same pinned Bucket and
ExpectedBucketOwner. They do not grant permissions, change policies,
upload, delete, download object contents or create/rotate keys.

The sanitized report includes the nested v0.9.14 exact-version
observation, SHA-256 of AWS account/ARN/UserId/request IDs, four
bucket response request-ID digests, asserted observed-control flags
and a domain-separated HMAC. It never includes raw object location,
credentials or source text. Errors are intentionally non-disclosing.

## Offline verification

    python scripts/audit_anchor_governance_v0915.py verify \
      --signed-anchor private/checkpoint.signed.json \
      --trusted-policy private/audit-signers.json \
      --archive-binding private/s3-binding.json \
      --local-key-file private/local-observation-token \
      --observation private/anchor-governance.json

Offline verification rechecks exact fixed report keys, Ed25519
signature, exact local signed file bytes, all nested S3 observations,
scope/time linkage, expected bucket owner, S3 request-ID hashes,
control flags and local HMAC, **without making any AWS request**.
It does not claim that remote state is currently unchanged.

## Tests and unresolved security gates

Sixteen focused unit tests cover all seven read-only calls and
pinned parameters, early signature/key denial without AWS access,
full-object failures before STS, incorrect caller identity or role,
disabled/suspended versioning, incomplete public access blocks,
public bucket policy, disabled Object Lock, sanitized AWS failures,
nested HMAC tampering, unsupported research/immutability claims,
CLI opt-in/negative paths and file symlink rejection.

CI runs only mock AWS SDK responses and retains a seven-day
sanitized report stating real_aws_account_contacted=false.
**No real AWS credential use or bucket existence is verified in CI.**
An authorized operator still has to provide and inspect a real
archive version, then separately review IAM/SCP/Access Point/bucket
policy contents and periodically repeat the retention observation.
Passing these seven point-in-time reads is not proof of continuous
WORM protection, independent organizational identity, immutable
Neo4j source data, source licensing or historical source authenticity.

Public research release remains HOLD pending these controls,
DvirOS SSO/RBAC, legitimate rights/attribution checks and human
scholarly review.
