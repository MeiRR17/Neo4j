# v0.9.16 — Time-separated audit-anchor governance comparisons

## Scope and guarantee

The v0.9.15 workflow can produce one point-in-time observation of an
Ed25519-pinned audit ledger anchor's exact S3 object version, its
FULL_OBJECT checksum, COMPLIANCE retention, caller AWS account and
four bucket-control settings. v0.9.16 compares **two** such previously
saved observations offline. It never contacts AWS or Neo4j itself.

Both inputs are independently revalidated from their exact signed
anchor bytes, operator-pinned Ed25519 public-key policy, fixed
S3 bucket/key/version/account/region binding and local HMAC key.
Every nested v0.9.14 and parent v0.9.15 receipt must pass its complete
strict verification and continue to report research HOLD.

The verifier requires the same signed anchor digest, file SHA-256
and length, exact version-id hash, bucket and account hashes, and
the exact operator binding. Each report must contain all seven
unique successful AWS request ID digests (two S3 object metadata
reads, one STS identity, four bucket controls); no ID may repeat
within or between the two observations. The local UTC timestamps
must be in increasing order at least 86,400 seconds apart.
A later COMPLIANCE retention date may be extended but must never
be shorter. Incompatible, forged or tampered reports fail closed.

## Operator commands (offline)

Run only after separately collecting two valid, private v0.9.15
governance JSON files using the existing authorized read-only AWS
inspect workflow:

    python scripts/audit_anchor_governance_v0915.py compare \
      --signed-anchor private/checkpoint.signed.json \
      --trusted-policy private/audit-signers.json \
      --archive-binding private/s3-binding.json \
      --local-key-file private/observation-token \
      --first-observation private/governance-first.json \
      --second-observation private/governance-second.json \
      --output private/governance-pair-v0916.json

Then replay the signed comparison with the original two reports:

    python scripts/audit_anchor_governance_v0915.py verify-comparison \
      --signed-anchor private/checkpoint.signed.json \
      --trusted-policy private/audit-signers.json \
      --archive-binding private/s3-binding.json \
      --local-key-file private/observation-token \
      --first-observation private/governance-first.json \
      --second-observation private/governance-second.json \
      --comparison private/governance-pair-v0916.json

The output is created as a private file, refusing overwrite.
The comparison includes only hashes of source observations and
pinned identities, timestamps, retention dates, interval, mandatory
scope limits, and a domain-separated HMAC. It does not disclose S3
bucket/object/account values, source text or credentials.

## Important limitations

Local timestamps can be forged by an operator controlling the HMAC
key or machine clock. Two independent-looking AWS request IDs do
not certify 24 hours elapsed at AWS or that Object Lock was never
weakened between reads. Passing these two observations does not
prove continuous WORM storage, an external trusted timestamp,
organizational signer identity, complete bucket/IAM/SCP/Access Point
policy evaluation, graph snapshots, source rights or scholarly
attribution. All release flags remain HOLD.

The 15 focused tests include 24h accepted, 23h59m refused, reversed
times, reused AWS IDs, wrong version, retention shortening versus
extension, bucket policy failure, tampered HMAC and offline CLI
checks. CI uses synthetic S3/STS mocks and a 25-hour virtual gap;
the seven-day artifact explicitly records that no real AWS account
was contacted. Existing Neo4j regression gates are retained.
