# v0.10.0 — DvirOS research study packet, phase 1

This milestone implements the private read-only Neo4j side of a
future DvirOS research-notebook workflow. It is not a saved notebook.

## API

Authenticated server-to-server GET
/v1/research/study-packets/preview
with exactly three query keys:
- source_work_id = canonical source Work ID
- target_work_id = distinct canonical target Work ID
- evidence_ids = comma-separated, sorted unique 1–12 canonical Evidence IDs

No public-browser access or arbitrary Cypher is permitted. The
existing bearer / optional signed-call requirements apply. A full
v0.9.11 two-pass audit scans up to 100 directed SOURCE_LINK
metadata rows and verifies selected Evidence membership. A missing
Evidence returns 404; invalid selection or query keys return 422;
between-pass drift returns 409; an unsafe/oversized graph returns 503.

The response contains the entire signed v0.9.11 audit_export,
a packet with exact selected Evidence IDs, original Edge/Passage/
Work identities, source refs, version/rights tags and independent
edge/evidence review states, and a new packet_sha256 and domain-
separated packet_hmac_sha256. The packet includes blank annotation
slots and a deterministic hash-derived packet_id. The complete
original audit allows subsequent offline verification of the selected
references without asking a mutable Neo4j graph again.

The service does not persist researcher notes or approve
interpretations. Graph edge status "approved" is NOT an approval of
a new research claim. Rights tags are metadata and NOT a license
or publication permission. A two-pass observation is NOT a database
transaction snapshot or an immutable corpus revision. Every packet
reports dviros_postgres_record_created=false,
licensed_source_rights_verified=false,
graph_snapshot_verified=false, and research_release_status=HOLD.

## Offline local verification

On a trusted host, write the private JSON response to a 0600 file.
With access to the protected service key, run:

    python scripts/verify_study_packet_v0100.py verify \
      --input private/study.json \
      --token-path private/research_api_token.txt

A private metadata-only CSV for a personal spreadsheet (not an
approved publication-ready citation format) can be created with:

    python scripts/verify_study_packet_v0100.py csv \
      --input private/study.json \
      --token-path private/research_api_token.txt \
      --output private/study-citations.csv

The CLI rejects duplicate JSON keys, symlinks, non-private input,
oversized payloads and overwriting existing output. Any potentially
executable spreadsheet field prefix is quoted with an apostrophe;
no user/reviewer notes, secrets or source text appear.

## DvirOS next steps and acceptance boundary

Only DvirOS (the application owning user identity and Postgres) may
persist user research questions, projects, note bodies, reviewer
identities and immutable review decisions. Its BFF must enforce
per-user access, verify the entire audit and packet HMAC before
storage, preserve provenance/version and denial flags, and expose
review decisions only to authorized humans. The Neo4j Research API
must remain read-only. A linked JSON contract is under docs/integrations.

Fourteen tests and isolated Neo4j CI smoke cover selected evidence,
missing IDs, unsorted/duplicate input, auth, wrong reviewer flags,
wrong HMAC, source rights tampering, real graph drift, CSV formula
injection and private file handling. The CI artifact contains
synthetic booleans and counts only, with no user data. BibTeX/other
publication output and stored notes are out of scope.

All research release and source rights acceptance gates remain HOLD.
