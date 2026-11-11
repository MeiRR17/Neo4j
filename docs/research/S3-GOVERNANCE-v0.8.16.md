# v0.8.16 — AWS STS / S3 bucket governance and separated retention samples (DRAFT)

The v0.8.15 tool validates one exact object version with HEAD/full-object
SHA256 and GetObjectRetention. v0.8.16 independently queries bucket
configuration with the same explicit owner/account and SDK credentials.

## Exact AWS API calls; no graph or object mutation

The operator must explicitly acknowledge live AWS *read-only* access.
One named boto3 profile, pinned region and 12-digit ExpectedBucketOwner
are required. The SDK receives fixed HTTPS S3 and regional STS endpoints.
After rechecking the complete HMAC/Ed25519/source-file chain, the tool
performs the two existing v0.8.15 object-version reads, plus:

- STS GetCallerIdentity, confirming the invoking IAM user/assumed-role
  account matches the pinned expected bucket-owner account. The resulting
  ARN/UserId are SHA256-hashed, not recorded in plaintext. This is only
  an AWS caller identity, not third-party organization certification.
- S3 GetBucketVersioning: Status must be Enabled, not Suspended or absent.
- S3 GetPublicAccessBlock: all four bucket-level controls must be true:
  BlockPublicAcls, IgnorePublicAcls, BlockPublicPolicy and
  RestrictPublicBuckets. These are bucket-level observations only.
- S3 GetBucketPolicyStatus: S3 must report PolicyStatus.IsPublic=false.
  This does NOT evaluate every IAM/SCP/Access Point grant.
- S3 GetObjectLockConfiguration: bucket ObjectLockEnabled=Enabled.
  The exact object-version retention is still checked separately in
  v0.8.15 and must use COMPLIANCE, not GOVERNANCE.

Each bucket request includes Bucket and ExpectedBucketOwner. A missing
permission, unexpected status, unknown field contract, disabled safeguard
or conflicting identity aborts before any receipt file is emitted.
No GetObject, PutObject, DeleteObject, policy modification or ListObjects
calls are made. Request IDs and identity/account/object references
are stored as hashes in a private mode-0600 HMAC record.

## Least privilege and operational boundaries

Authorize only required read-only operations for the expected account
and relevant metadata archive bucket / object versions:

  s3:GetObjectVersion
  s3:GetObjectRetention
  s3:GetBucketVersioning
  s3:GetBucketPublicAccessBlock
  s3:GetBucketPolicyStatus
  s3:GetBucketObjectLockConfiguration

STS GetCallerIdentity is used to check the caller's account. Depending
on object encryption, KMS read permissions may also be necessary for
HEAD with ChecksumMode ENABLED; do not grant write or bypass permissions.
Use the profile's normal IAM/SSO chain; no credentials are saved to Git.
The conservative caller-account check rejects cross-account auditor
credentials even if AWS might otherwise permit reads.

Bucket-level public-access checks do not cover account-wide Block
Public Access, IAM, SCP, object ACLs, Access Points or bucket-policy
content semantics. These are explicit pending governance gates.

## Operator inspect / verify / compare

First install the optional pinned AWS SDK and cryptographic verifier:

    python -m pip install -r requirements/aws-s3-audit.txt
    python -m pip install -r requirements/provenance-attestation.txt

On an authorized host, issue the first private observation:

    umask 077
    python scripts/s3_governance.py inspect \
      --source-file /private/links0.csv \
      --source-record /private/source_record.json \
      --receipt /private/source_receipt.json \
      --witness /private/source_witness.json \
      --capture-manifest /private/capture_manifest.json \
      --trusted-policy /private/trusted_archive_keys.json \
      --archive-report /private/archive_claim.json \
      --signed-statement /private/signed_ed25519_statement.json \
      --aws-profile research-archive-readonly \
      --aws-region il-central-1 \
      --expected-bucket-owner 123456789012 \
      --ack-live-aws-read-only \
      --output /private/s3_control_observation_1.json

To verify a saved report without any AWS call, run `verify` with the
same source file, record, receipt, witness, capture, policy, report,
signed statement, region and owner, replacing `--aws-profile`, ack,
and output with `--observation /private/s3_control_observation_1.json`.

At least 24 hours later, rerun `inspect` into a NEW, different private
output file. The offline `compare` command takes the same private
source-chain, region and owner flags, with:

    --previous /private/s3_control_observation_1.json
    --current /private/s3_control_observation_2.json
    --output /private/s3_two_observations.json

`compare` checks the HMAC of both reports, the exact source/witness
and object-version identity, a minimum 86,400-second separation in
their locally asserted timestamps, and distinct AWS HEAD/retention/STS
request-ID hashes. It records both sample hashes and a separate HMAC.
Comparisons of the same sample, short intervals or different sources
fail closed. It does **not** access AWS and cannot assert the current
state, continuous uninterrupted retention, or externally trusted time.

## Threat model / release gates

A successful audit supports: the local signing key verified the
source chain, the pinned Ed25519 archive claim was cryptographically
valid, and authenticated AWS SDK responses reported matching controls
at one or two times. The result deliberately records
`archive_continuously_immutable_verified=false`,
`full_iam_scp_access_points_policy_verified=false`,
`signer_organization_independently_verified=false` and
`legal_source_rights_verified=false`.

The archive may change between samples or be externally misconfigured;
even AWS policy-status false does not establish all effective grants.
Your local HMAC clock/credential/profile are not a third-party secure
timestamp, durable external evidence log or certification of the archive
operator's organization. No production AWS accesses are made in CI;
all S3/STS results are synthetic mocks integrated with a real isolated
Neo4j test environment.

Research release remains HOLD. Source rights, immutable licensed corpus
revisions, 50 genuine scholarly review questions and DvirOS production
SSO/RBAC approval are separate gates. This remains a stacked draft PR.
