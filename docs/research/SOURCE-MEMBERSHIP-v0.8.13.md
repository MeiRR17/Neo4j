# v0.8.13 — Bounded SourceRecord membership witness (DRAFT)

The v0.8.12 local receipt checks retained source file bytes against a
separately exported SourceRecord. Until now, there was no proof that this
record appeared in the complete source *metadata projection* observed in
the v0.8.11 signed search capture. This version supplies that narrow proof.

## Mechanism

1. Require an HMAC-valid v0.8.11 private capture and a v0.8.12 source
   receipt already bound to that exact capture.
2. Read the complete, <=500-row / <=25-page SourceRecord metadata
   projection over the existing local bearer + DvirOS HMAC API.
3. Validate source-only DTOs, canonical IDs, sorted unique cursors,
   pagination completion and refusal of source text/unexpected fields.
4. Recreate exactly the v0.8.11 SHA256 stream: four-byte big-endian length
   and the canonical JSON of every SourceRecord row in strict ID order.
   Require the full digest, record count and missing-checksum count to
   match the source observation in the HMAC-validated capture manifest.
5. Require the submitted v0.8.12 receipt's SourceRecord projection to
   match exactly one row in that complete observed source set.
6. Save one exclusive mode-0600 witness, HMAC-signed using a distinct
   domain from v0.8.11 captures and v0.8.12 receipts.

The witness retains ONLY the strictly bounded source metadata rows,
not document texts, quotes or license clearances. The offline verifier
recomputes the complete framed projection and HMAC, rechecks the source
file bytes and record, and verifies the original capture binding.

## Local-only CLI

Use the existing authorized 127.0.0.1 private Research API with
DVIROS_REQUIRE_SIGNED_CALLS=1. Provide a private, source-record JSON
file, a v0.8.12 receipt issued WITH --capture-manifest, the retained
original local source snapshot, and the same HMAC capture manifest.

    umask 077
    python scripts/source_membership.py issue \
      --source-file /private/links0.csv \
      --source-record /private/source_record.json \
      --receipt /private/links0.receipt.json \
      --capture-manifest /private/capture_manifest_v0811.json \
      --url http://127.0.0.1:8000 \
      --output /private/source_membership_witness.json

    python scripts/source_membership.py verify \
      --source-file /private/links0.csv \
      --source-record /private/source_record.json \
      --receipt /private/links0.receipt.json \
      --capture-manifest /private/capture_manifest_v0811.json \
      --witness /private/source_membership_witness.json

An optional --key-file chooses an already provisioned 0600 HMAC secret.
issue may also select --token-file. The verify command is entirely offline.
Never upload the witness: it includes private metadata-only source URIs.

## What this does NOT prove

The witness is tied to an HMAC-protected **observed source projection**.
It does NOT prove a Neo4j write freeze, graph-edge membership, edition
version identities, alias relationships, source text or full corpus
completeness outside the explicit pilot bounds. Multiple signed API GETs
are not a single database transaction; ABA changes can be missed.

The source/provider supplied checksum and operator HMAC are not an
independently authenticated provider signature or publicly verifiable
timestamp. No external signer or immutable storage has been configured.
Neither source licensing nor permission to redistribute texts follows.
No real provider data is used by CI, and research release remains HOLD.

An independent public-key attestation tied to an immutable source archive,
licensed edition receipts, source rights review and the 50-question
human-judged Precision@5 acceptance are separate pending milestones.
