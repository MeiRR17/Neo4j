# v0.8.17 — Bounded AWS IAM, SCP and S3 Access Point visibility (DRAFT)

Layered on v0.8.11–0.8.16, this optional audit enumerates the IAM,
Organizations and S3 access-control *metadata* visible to an authorized
read-only AWS operator. It does not simulate policies, grant/revoke
access, inspect source text or approve production release.

## What the opt-in inspect checks

1. Revalidates the complete signed local SourceRecord and retained-byte
   provenance chain, then the versioned S3 HEAD, retention and bucket
   governance observations from v0.8.16. No client exists before local
   chain verification. All requests use named AWS SDK profile and fixed
   commercial-partition HTTPS endpoints.
2. **S3Control** GetPublicAccessBlock(AccountId): all four account-level
   switches must be on. ListAccessPoints(AccountId,Bucket): bounded,
   complete pagination (<=100 objects); per point, GetAccessPoint and
   GetAccessPointPolicyStatus must establish matching bucket, VPC-only
   access, valid VPC ID, four point-level public-access blocks and a
   nonpublic point policy. Internet-exposed or unknown points fail closed.
   Directory buckets, Multi-Region Access Points, Object Lambda and
   paths outside the scoped bucket are *not* enumerated.
3. **IAM** STS GetCallerIdentity must identify a same-account assumed
   role (not a root user or arbitrary cross-account caller). IAM GetRole
   checks its canonical ARN and the presence/type of a permission
   boundary; ListAttachedRolePolicies and ListRolePolicies enumerate
   bounded policy identifiers and names (max 100 total). Role policy
   JSON bodies, permissions, condition keys and trust semantics are
   deliberately **not evaluated**.
4. **AWS Organizations** ListParents traces the account up through its
   OU ancestors to one root (max six levels). At each account, OU and
   root node, ListPoliciesForTarget(Filter=SERVICE_CONTROL_POLICY)
   enumerates attached SCP identifiers (max 100 total), including
   inherited-attachment locations. SCP JSON content and combined
   effective permissions are **not evaluated**.

Lists must complete within bounded pages, with unique entries and
no unsafe or ambiguous identifiers. Unavailable Organizations delegated
administrator privileges, access denied, empty/malformed pagination,
unbounded OU ancestry or unsafe Access Points fail closed; they are
not misreported as an empty/nonexistent policy set.

## Run on an authorized AWS audit host

Install the existing optional pinned dependencies:

    python -m pip install -r requirements/provenance-attestation.txt
    python -m pip install -r requirements/aws-s3-audit.txt

The operator must already possess the private files issued by earlier
versions. Replace the bucket owner and AWS profile below with the actual
authorized identifiers; no credentials may be stored in the repository.

    umask 077
    python scripts/aws_access_surface.py inspect \
      --source-file /private/links0.csv \
      --source-record /private/source_record.json \
      --receipt /private/source_receipt.json \
      --witness /private/source_witness.json \
      --capture-manifest /private/capture_manifest.json \
      --trusted-policy /private/ed25519_trusted_archive_keys.json \
      --archive-report /private/archive_claim.json \
      --signed-statement /private/ed25519_statement.json \
      --aws-profile research-auditor \
      --aws-region il-central-1 \
      --expected-bucket-owner 123456789012 \
      --ack-read-only-aws-policy-inventory \
      --output /private/access_surface_v0817.json

Offline re-verification uses the same source-chain, region and owner
flags and `verify --observation /private/access_surface_v0817.json`.
The verifier does not contact AWS. A fresh AWS audit requires a new
inspect operation and a new exclusive output path.

Auditing usually needs explicit read-only permissions for STS identity,
s3control:GetPublicAccessBlock, s3control:ListAccessPoints,
s3control:GetAccessPoint, s3control:GetAccessPointPolicyStatus,
iam:GetRole, iam:ListAttachedRolePolicies, iam:ListRolePolicies,
organizations:ListParents, organizations:ListPoliciesForTarget,
plus the existing S3 controls used by v0.8.16. Organizations may
require management-account or delegated-administrator authority.
Do not grant any mutation, policy editing, storage deletion or bypass
permission to perform this audit.

## Private output and explicit nonclaims

The HMAC receipt stores the prior governance observation, SHA256
fingerprints of enumerated scope and identifiers, counts and
boolean control observations. It does not store role names, principal
ARNs, policy bodies, Access Point names, buckets, source text or AWS
credential values. It is written once, 0600, without overwriting.

All of the following MUST remain false:

- effective_iam_permissions_verified
- scp_policy_semantics_verified
- cross_account_resource_policy_verified
- all_s3_access_routes_verified
- external_immutability_certified
- license_and_scholarly_release_approved

The audit does not reconstruct the AWS authorization decision,
evaluate IAM policy JSON or SCP conditions, discover grants to every
external principal, verify every access mechanism or certify continuous
Object Lock. A locally HMAC-protected census is not an independent
security review or AWS-signed immutable receipt. The exact source
archive must still be accessed only when expressly authorized.

Tests only mock AWS and use disposable real Neo4j source fixtures.
No live AWS, source copyright clearance or 50 real expert-scored
questions have been performed. **Research release: HOLD**.
