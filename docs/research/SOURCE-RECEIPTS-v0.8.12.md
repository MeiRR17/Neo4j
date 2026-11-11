# v0.8.12 — Local, tamper-evident source-byte receipts (DRAFT)

The v0.8.11 observation hashes *stored* SourceRecord metadata, not retained
source file bytes. This release recomputes a digest from a local source
snapshot and checks it against a separately exported SourceRecord DTO.

## Two explicit checksum modes

1. sefaria_links_csv_raw_sha256: SHA256 of original raw CSV bytes.
   Enforces the exact seven-column historical Sefaria metadata header,
   known Sefaria links export HTTPS URI and LINK_METADATA_UNREVIEWED tag.
2. sefaria_versions_json_canonical_sha256: canonical JSON SHA256 as
   defined in ingestion.seed_catalog.checksum, not raw file SHA256.
   Enforces a canonical Sefaria version-metadata URI, JSON array format,
   and EDITION_METADATA_ONLY tag. Rejects source-text-shaped JSON.

Both modes check canonical source ID, stored checksum, version ID,
provider, and rights tag. The receipt also records raw-file SHA256 and
size. It never stores full source URL, original file path or source text.

## Operator commands — authorized private host only

    umask 077
    python scripts/source_receipts.py issue \
      --source-file /private/links0.csv \
      --source-record /private/source_record.json \
      --mode sefaria_links_csv_raw_sha256 \
      --output /private/links0.receipt.json

    python scripts/source_receipts.py verify \
      --source-file /private/links0.csv \
      --source-record /private/source_record.json \
      --receipt /private/links0.receipt.json

The exported SourceRecord should be retrieved separately from the
authenticated research API. The CLI accepts only local files, and uses
the existing local DvirOS HMAC key (or a specified --key-file).

Optional --capture-manifest accepts an HMAC-authenticated v0.8.11
capture manifest. This binds the receipt to that capture event's
aggregate provenance observation, but does NOT prove that this specific
SourceRecord was contained in that capture's graph.

Receipts are created once, mode 0600, and verification rehashes source
content, record projection and local HMAC. Existing paths and symlinks
cannot be overwritten. CSV may be streamed up to 512 MiB, while version
metadata JSON is limited to 2 MB. Filesystem change detection is
best-effort and not a write-freeze or external archive.

## Strict limitations

This only shows that retained local bytes match a stored source claim.
It does not attest independent Sefaria TLS delivery, external immutable
retention, original content authorship, edition redistribution license,
scholarly reviewer identity or rights to quote/reproduce copyrighted
text. A compromised local HMAC key can forge receipts. Research release
remains HOLD until human legal/scholarly signoff, the 50 real question
Precision@5 threshold and DvirOS production security gates are satisfied.

CI exercises only synthetic source metadata, not live provider content.
