# v0.8.20 — Bounded S3 resource-policy and IAM caller-role trust inspection (DRAFT)

Version 0.8.19 checks IAM managed/default policy versions, inline
policies, inherited SCP documents and condition structures. Version
0.8.20 adds the **resource-side and role trust** documents needed to
review potential cross-account sharing signals. The report has no
notion of an authorized/safe access decision.

## Read-only AWS API scope

This CLI extends the full signed 0.8.11–0.8.19 chain, using the same
authorized named AWS profile, regional S3 and S3Control clients,
expected owner account and IAM read-only caller.

1. Obtain the v0.8.19 signed policy revision report and its bound
   S3 Access Point and role census. Unknown or missing source evidence
   must fail before contacting AWS.
2. S3 **GetBucketPolicy** for the exact bucket and ExpectedBucketOwner;
   require HTTP 200 and a bounded, supported JSON policy document.
3. S3Control ListAccessPoints(AccountId,Bucket) and per-point
   **GetAccessPointPolicy(AccountId,Name)**. The previously verified
   VPC-only, nonpublic and public-block checks remain prerequisites.
   Refuse a missing policy or list outside the signed bounded inventory.
4. IAM **GetRole(RoleName)** for the authenticated same-account assumed
   role, verifying its exact ARN and extracting
   AssumeRolePolicyDocument (which may arrive URL-encoded).
5. Read the entire policy set **twice**, cross-check Access Point
   count/metadata digest and IAM caller role both times, and compare
   the ordered SHA256 projection. Reject absent/changed policy texts
   and malformed document schemas; no raw policy is persisted.
6. Write one local exclusive, private mode-0600 HMAC report containing
   the nested prior evidence, policy counts, projected digest and
   structural review indicators.

## Indicators requiring human/security assessment

The counter names deliberately describe *syntactic patterns*:

- Allow statements with wildcard Principal
- Allow statements naming a different 12-digit account in AWS Principal
- Allow statements using service/federated/canonical principals
- Allow statements containing an unclassified principal selector
- Allow statements using NotPrincipal or NotAction/NotResource
- Allow statements bearing a Condition (not semantically evaluated)
- Allow statements containing sts:AssumeRole action patterns
- Explicit Deny statements and total statements inspected

An explicit account principal does not prove a cross-account access
grant. Actual AWS authorization depends on the full identity policy,
resource policy, trust, SCP/RCP, session policy, permission boundary,
VPC endpoint policy and request attributes. Even seemingly nonpublic
policies may delegate access to external accounts. The audit does not
simulate the final effective permission decision.

## Operator command

Install the already pinned optional dependencies:

    python -m pip install -r requirements/provenance-attestation.txt
    python -m pip install -r requirements/aws-s3-audit.txt

On an authorized host, supply the private source and archive files
obtained from earlier versions. Never put their bytes in the repo:

    umask 077
    python scripts/aws_resource_trust.py inspect \
      --source-file /private/links0.csv \
      --source-record /private/source_record.json \
      --receipt /private/source_receipt.json \
      --witness /private/source_witness.json \
      --capture-manifest /private/capture_manifest.json \
      --trusted-policy /private/pinned_archive_keys.json \
      --archive-report /private/claimed_s3_report.json \
      --signed-statement /private/archive_operator_ed25519.json \
      --aws-profile research-archive-readonly \
      --aws-region il-central-1 \
      --expected-bucket-owner 123456789012 \
      --ack-read-only-resource-policy-audit \
      --output /private/aws_resource_trust_v0820.json

Offline `verify` accepts the same source/policy/signed statement/
region/expected owner arguments, replacing the AWS profile/ack/output
with `--observation /private/aws_resource_trust_v0820.json`.
Offline verification only checks the locally signed saved evidence;
it never checks that AWS state is still the same.

## Explicit remaining gaps

This scan is bounded by the original v0.8.17 Access Point list and
only inspects the *caller's* IAM role trust. It does NOT enumerate
all external roles, resource-based grants in other accounts,
Multi-Region Access Points, Object Lambda, S3 Access Grants,
VPC endpoint policies or Organizations RCP policy texts. Nor does
it independently verify provider organization identity or certify
the actual immutable object retention over time.

Two matching policy reads do not create an AWS transactionally
frozen snapshot; ABA races are still possible. Failure to read
a policy, scan the complete bounded list, or validate any signature
must block the audit. The tool never issues AWS mutation requests.

CI uses synthetic bucket/AP/trust policies and isolated real Neo4j
source fixtures only, without an AWS account. No source rights
or real 50-question scholarly evaluations are approved.
Research release remains **HOLD**; do not merge this stacked PR to main.
