# v0.9.17 — Pinned time signatures over S3 governance receipts

## Scope

v0.9.16 compares two locally timestamped, HMAC-protected observations
of the **same exact S3 object version** and Ed25519-signed Neo4j
audit-revision anchor. The two timestamps in those observations are
locally recorded and can be falsified by the holder of the local HMAC
key. This increment accepts **separately supplied** time attestations
cryptographically signed by an independently pinned public key.

It verifies the signatures but DOES NOT issue them. No production
timestamp signing key, RFC3161 response or configured external time
service is present in the repository or CI. These custom statements
are **not RFC3161 tokens**. A pinned key is not proof that an external
provider is genuine, accredited, honest or has an accurate clock.

## Exact signed statement and pinning policy

Each timestamp token is a JSON object with exactly:

- statement: canonical object containing schema_version="0.9.17",
  scope="signed_governance_receipt_sha256", authority_id,
  signed_anchor_sha256, binding_sha256,
  subject_observation_sha256 (SHA-256 of the entire canonical
  v0.9.15 receipt), issued_at_utc (strict UTC, e.g.
  2030-01-02T03:04:05Z), request_nonce_sha256 (64 lowercase hex)
- signature_b64: standard padded base64 of 64 Ed25519 signature bytes

The Ed25519 message is the UTF-8 ASCII domain prefix
"dviros/third-party-audit-observation-time/v0.9.17\n"
followed by the complete canonical JSON statement bytes (sorted keys,
no extra whitespace). The nonce digest must be unique to each
attestation; it is not a trusted timestamp or provenance claim.

The separately provisioned trust file has schema_version="0.9.17",
trust_status="OPERATOR_PINNED_EXTERNAL_TIME_ISSUER_NOT_ACCREDITED",
and authorities (1–4 entries) with exactly authority_id, role set
to external_receipt_timestamp_signer, and standard padded base64
ed25519_public_key_b64 of the 32 raw Ed25519 public-key bytes.

Time-authority keys must be unique and **must not** match any
v0.9.13 archive signer public key. Both timestamp statements must
use the *same* pinned authority ID for the signed interval. The
pinned policy and original external statements must be obtained
and checked independently by a trusted operator; their presence
alone does not establish an accredited provider.

## Conditions before a timestamp comparison may pass

- Verify the original Ed25519 signed archive checkpoint, exact S3
  file bytes and VersionId, *both* complete v0.9.15 receipts and the
  complete HMAC-sealed v0.9.16 pair. All 14 S3/STS request-ID digests
  must be unique and the second COMPLIANCE retention must not shorten.
- Cryptographically verify both time-attestation signatures against
  a separately pinned time issuer and exact SHA-256 of the individual
  receipt. Receipt substitution or binding changes are rejected.
- Each issuer-signed UTC time must follow the corresponding locally
  recorded observation by 0–900 seconds. This is a consistency bound,
  not a clock-accuracy certification.
- The *signed* time interval must be between 86,400 seconds (24h)
  and 31 days, and must be in increasing order; a same nonce or
  changed authority is refused.
- HMAC-seal the complete resulting 0.9.17 report under the existing
  local observation key, and reject false rights/immutability/
  RFC3161/accreditation flags. The report contains only SHA-256
  digests, signed timestamps, checks and issuer ID.

## Offline CLI (no network)

Prepare two independently provisioned and signed timestamp tokens,
the original v0.9.15 observations and their saved v0.9.16 comparison.
Then run:

    python scripts/verify_anchor_pinned_times_v0917.py compare \
      --signed-anchor private/checkpoint.signed.json \
      --trusted-policy private/audit-signers.json \
      --archive-binding private/s3-binding.json \
      --local-key-file private/observation-token \
      --first-observation private/governance-first.json \
      --second-observation private/governance-second.json \
      --paired-comparison private/governance-pair-v0916.json \
      --first-timestamp private/time-first.json \
      --second-timestamp private/time-second.json \
      --time-authority-policy private/time-issuer-pins.json \
      --output private/time-comparison-v0917.json

To replay the complete verification with the *same* original inputs,
replace "compare" with "verify", and replace --output with --report
pointing to the saved time-comparison-v0917.json. Both actions are
strictly local; private output is create-only and refuses overwrite.
This project never creates, signs or schedules external timestamp
statements on the user's behalf.

## Explicit nonclaims and tests

The report always says that no timestamp service was contacted,
issuer identity/accreditation was not independently verified,
RFC3161 validation was not performed, and continuous Object Lock,
source legal rights, Neo4j snapshot and research release remain false
or HOLD. This is signed chronology relative to a *pinned key*,
not a trusted RFC3161 TSA or a certified independent clock.

Sixteen focused tests use transient synthetic Ed25519 issuer keys,
mock S3/STS responses and fabricated times. They cover 24-hour
boundary, too-short interval, promptness ±15m, signer substitution,
duplicate nonce, mismatched observation digest, forged source
scope, anchor key reuse, wrong authority, tampered comparison,
missing files and offline CLI. CI retains sanitized boolean results
only for seven days; it never contacts real AWS or a timestamp
issuer. Future production qualification requires actual, operator-
approved archival reads, independently vetted time issuer identity
and key lifecycle, external retention evidence, rights/attribution
review and DvirOS SSO/RBAC.
