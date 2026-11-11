# v0.8.18 — Bounded IAM and SCP policy-document indicators (DRAFT)

This release extends v0.8.17's **signed attachment census** to read the
policy documents associated with that exact same observed role/SCP
attachment inventory. The result is a bounded **risk-indicator report**;
it is not an AWS authorization simulator or an approval to use source data.

## Mechanism

1. Authenticate local 0.8.11–0.8.14 source/capture/receipt/Ed25519 chain.
2. Repeat v0.8.15 versioned S3 and v0.8.16 bucket/STS governance reads,
   then v0.8.17 S3 Access Point, IAM role and Organizations SCP census.
3. Ensure the IAM role ARN, permissions boundary, managed/inline
   attachment set, account/OU/root lineage and SCP attachments match
   exactly the signed census digests and counts.
4. Read **IAM GetPolicy and GetPolicyVersion** for the current default
   managed policy versions and **GetRolePolicy** for each role inline
   policy. Read **Organizations DescribePolicy** for each unique SCP
   attached to the account, any ancestor OU, or the root.
5. Accept JSON objects and IAM URL-encoded JSON; strictly validate
   bounded statement structure, duplicate keys, effect/action/resource
   fields and document size. No policy bodies are placed in output.
6. Repeat the role/SCP inventory reads and fail if any attachment or
   lineage changed during policy-document retrieval.
7. Save only SHA-256 digests/counts and conservative IAM/SCP indicators,
   protected by a local HMAC and exclusive 0600 output.

Indicators include counts of IAM Allow statements combining wildcard
resource and broad actions, IAM Allow statements matching a short
known list of S3 mutations or IAM escalation actions, IAM explicit Deny,
SCP Allow/Deny statements, and statements with Conditions, NotAction or
NotResource. These are **pattern observations**, not permission grants
or denial judgments. Conditions, multiple policy types, exceptions,
NotAction, NotResource, trust policies, resource-based grants and SCP
inheritance semantics must be evaluated by separately approved methods.

## AWS API scope and authorization

GetPolicy, GetPolicyVersion and GetRolePolicy for the identified
caller role, plus Organizations DescribePolicy on SCP attachments
discovered through ListPoliciesForTarget at each ancestor.
All calls use the explicitly named AWS SDK profile from v0.8.17 and
read-only methods. No policy editing, role assumption, Put/Delete
or permission simulation is performed. The tool refuses incomplete
policy listing, missing access, malformed/oversized documents and
identity mismatch. No real AWS credentials exist in CI.

## Run on an authorized operator host

Install optional pinned requirements:

    python -m pip install -r requirements/provenance-attestation.txt
    python -m pip install -r requirements/aws-s3-audit.txt

Provide the authorized private source chain, operator trust policy
and archive claim already required by v0.8.17:

    umask 077
    python scripts/aws_policy_documents.py inspect \
      --source-file /private/links0.csv \
      --source-record /private/source_record.json \
      --receipt /private/source_receipt.json \
      --witness /private/source_witness.json \
      --capture-manifest /private/capture_manifest.json \
      --trusted-policy /private/archive_trusted_keys.json \
      --archive-report /private/archive_claim.json \
      --signed-statement /private/archive_signature.json \
      --aws-profile research-auditor \
      --aws-region il-central-1 \
      --expected-bucket-owner 123456789012 \
      --ack-read-only-policy-documents \
      --output /private/policy_indicators_v0818.json

The offline `verify` subcommand accepts the same private files/region
and owner and `--observation` instead of the AWS profile/ack/output.
It verifies the saved HMAC and full nested source/governance census
without performing AWS requests. It cannot prove current AWS policy
content or recompute every original document from digest-only output.
Reinspect for a fresh, explicitly authorized source snapshot.

## Security and research limitations

This is a limited, fail-closed **visibility** pass, not an exhaustive
enumeration of every policy affecting a user or bucket. It does not
compute AWS effective permissions or SCP allow/deny precedence and
does not evaluate policy JSON conditions, permission boundaries,
resource policies, session policies, other principals/accounts,
VPC endpoint restrictions or external archival guarantees.

Large, unsupported, truncated or partially readable policies fail
rather than being declared safe. Signatures and digest-only reports
are local operator evidence, not independent AWS-signed receipts.
Research release remains HOLD pending actual authorized AWS audit,
source rights, 50 genuine human-reviewed questions and DvirOS
production SSO/RBAC and scholarly signoff.

CI runs on synthetic AWS policy documents and isolated Neo4j only.
