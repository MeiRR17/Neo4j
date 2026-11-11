# v0.8.19 — Bounded IAM/SCP policy revision consistency (DRAFT)

This version closes an observation gap in v0.8.18. The earlier report
guarded IAM/SCP attachment and organization ancestry changes, but a
policy's default version or inline/SCP content could drift without the
attachment list changing. v0.8.19 performs **two extra complete bounded
policy-document reads** and binds them to the original signed v0.8.18
document projection.

## Exactly what the read-only inspection does

1. Re-verify the original v0.8.11–17 source/provenance/Ed25519/S3/IAM
   chain, then produce a fresh v0.8.18 document report on the same
   explicitly authorized AWS profile, region and owner.
2. Enumerate the same role attachment and account → OU → root SCP list.
   Compare digests, counts and boundary presence to the authenticated
   v0.8.17 access census. Incomplete lists fail closed.
3. For every attached IAM managed policy, read GetPolicy, request the
   exact DefaultVersionId with GetPolicyVersion and confirm its
   IsDefaultVersion flag; read GetPolicy again and reject a default
   version switch or identity change while retrieving the document.
4. Read every IAM role inline policy and every unique attached SCP
   DescribePolicy body. Reject malformed documents and wrong IDs.
5. Re-enumerate IAM/SCP attachment and OU ancestry after each round.
   Verify a complete round's ordered canonical document SHA256 matches
   the original v0.8.18 HMAC report. Repeat the entire round and require
   the document projection, managed default versions and structural
   condition indicators to match exactly.
6. Save **digests, counts and nonapproval flags only** in an exclusive
   private mode-0600 HMAC report. No policy text, principal, source
   document, bucket, account ID, Access Point name or credential is
   exported to the report.

## Condition structure and blind spots

Indicators are counters of statements containing:

- IfExists and ForAnyValue / ForAllValues qualifiers
- Null operators and unrecognized condition operator names
- network-scoping context (`aws:SourceIp`, `aws:SourceVpce`, etc.)
- principal identity or MFA context
- S3 resource account, Access Point or request-tag context
- unconditional wildcard-resource/wildcard-action IAM Allow shapes
- NotAction / NotResource constructs

These are syntactic **review flags**, not interpretations of condition
truth or AWS authorization. In particular, IfExists/Null/negation,
resource policies, IAM permission boundaries, role trust, session
policies, VPC endpoint policies, cross-account grants, Organizations
RCP documents and SCP inheritance interactions remain out of scope.

## Authorized CLI

The operator must separately provision the source files, pinned Ed25519
archive trust policy and read-only AWS profile described in v0.8.18.
Use the existing pinned optional dependencies:

    python -m pip install -r requirements/provenance-attestation.txt
    python -m pip install -r requirements/aws-s3-audit.txt

    umask 077
    python scripts/aws_policy_revision.py inspect \
      --source-file /private/links0.csv \
      --source-record /private/source_record.json \
      --receipt /private/source_receipt.json \
      --witness /private/source_witness.json \
      --capture-manifest /private/capture_manifest.json \
      --trusted-policy /private/archive_trusted_keys.json \
      --archive-report /private/archive_claim.json \
      --signed-statement /private/ed25519_statement.json \
      --aws-profile research-auditor \
      --aws-region il-central-1 \
      --expected-bucket-owner 123456789012 \
      --ack-read-only-policy-revision \
      --output /private/policy_revision_v0819.json

The offline `verify` accepts the same private source-chain files, AWS
region and bucket owner, but takes `--observation` instead of profile,
acknowledgment and output. It validates the source-bound HMAC and
schema/claims; with digest-only evidence, it cannot reconstruct the
original AWS policy documents or prove that their live state has not
changed since inspection. Run another authorized inspect for a fresh
observation and use a different output path.

## Remaining constraints — HOLD

Two matching rounds do not constitute an AWS IAM transactionally
isolated snapshot. ABA changes between reads, hidden principals,
resource policies, context conditions, SCP allow/deny interactions,
role trust and session policies are not proven safe. This utility is
not an AWS IAM Policy Simulator and does not establish a negative
cross-account authorization proof.

Actual operator-authorized AWS observations, licensed/immutable source
receipts, 50 real independent expert-scored research questions and
DvirOS SSO/RBAC production approval are separate gates. The CI uses
synthetic mocked AWS responses and isolated Neo4j only. **Release HOLD.**
