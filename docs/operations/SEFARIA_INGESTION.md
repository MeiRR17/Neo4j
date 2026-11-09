# v0.3.0 — Sefaria links metadata ingestion for DvirOS

**Status: implemented as a gated metadata-only pipeline.**
This does not ingest a licensed text edition or prove scholarly influence.
It is separate from Learning_Modules (which remains unchanged).

## Verified upstream contract (2026-11-09)

- Sefaria-Export now indexes texts in GCS and publishes link shards
  `links/links0.csv` etc. The old `links/links.json.gz` is obsolete.
- Export link CSV headers in upstream exporter include **`Conection Type`**
  (historical misspelling), `Citation 1`, `Citation 2`, `Text 1`,
  `Text 2`, `Category 1`, `Category 2`.
- REST `/api/links/{tref}?with_text=0` supports metadata-only responses.
  API shape may vary by endpoint/version; ambiguous mappings are quarantined.

Upstream references:
- https://github.com/Sefaria/Sefaria-Export
- https://github.com/Sefaria/Sefaria-Project/blob/master/sefaria/export.py
- https://developers.sefaria.org/reference/get-links

## Offline workflow (no network, no DB writes)

```sh
python scripts/ingest_sefaria.py plan-csv \
  --input /private/data/links0.csv \
  --source-uri https://storage.googleapis.com/sefaria-export/links/links0.csv \
  --output /private/staging/sefaria-2026-11
```

Only rows touching a title in `config/sefaria-philosophy-titles.json`
are selected. Matching is **exact** against the CSV work field; the list is
a candidate review set, not a guarantee that each title is a current index.
Selection includes the other side of the link but does not equate that
other work with a philosophical source.

Output: `links.jsonl`, `quarantine.jsonl`, `manifest.json`.
Manifest records file checksum, source URI, graph identity, field status,
rights state, counts, and integrity checksums. Input remains untouched.
A nonzero quarantine fails closed by default; use `--max-quarantine N`
only to **inspect** incomplete staging. Such staging CANNOT be applied.

By default all relationships are `OBSERVED_SOURCE_LINK`,
`unreviewed`, `orientation=not_asserted`. These links are not
assumed quotations, agreement, intellectual dependence or proof of influence.
No text bodies, authors or historical dates are invented.

## Opt-in acquisition (network)

```sh
python scripts/ingest_sefaria.py fetch-shard \
  --shard links0.csv --output /private/data/links0.csv --live
python scripts/ingest_sefaria.py plan-api \
  --title "Guide for the Perplexed" --output /private/staging/api-guide --live
```

- GCS shard download is bounded by `--max-bytes` (default 300MB).
  Downloads use a local `.part` and ETag checkpoint. A partial file
  resumes only when the remote ETag and Content-Range match; mismatches
  require manual cleanup rather than silently mixing versions.
- API access sends `with_text=0`, limits size, timeout, retry count
  and follows **no HTTP redirect**. No automatic background scraping.
- If an API response lacks a trustworthy `index_title` or exact anchor,
  the row is quarantined rather than guessing its work from whitespace.
- Never commit acquired CSVs, staging output, checkpoints or source text.

## Metadata-only Neo4j write (explicit approval required)

After checking manifest quality, expected source/checksum, and verifying
license/attribution requirements for your use:

```sh
python scripts/bootstrap.py
docker compose up -d --wait
python scripts/migrate.py apply
python scripts/ingest_sefaria.py apply \
  --input /private/staging/sefaria-2026-11 --ack-unreviewed
```

This is deliberately NOT the default. The writer validates **all rows**
before beginning, requires zero quarantined links, checks applied schema
migrations, uses parameterized batched MERGE and does not create text
content. Any interrupted apply may be safely rerun for the same plan.
No unreviewed link may be promoted to an approved scholarly claim.
The local Neo4j server still binds only to loopback.

## Rollback and known limitations

- Do not use old `02_acquire_sefaria_data.py` for scientific claims:
  it breaks multiword refs and lacks a credible provenance boundary.
- The export links data does **not** supply edition identity. v0.3 stores
  an explicit **UNVERSIONED_LINK_METADATA_ONLY** sentinel; future
  edition linking must be reviewed instead of pretending an edition exists.
- Not all links are directional. Orientation is not inferred.
- This tool does not infer licensing for full text. A per-edition rights
  inventory and reviewed seed corpus remain v0.4.0 release gates.
- To reverse an unreviewed batch safely, restore an isolated tested DB
  backup or use a separately reviewed versioned cleanup procedure;
  NEVER blanket-delete existing graph entities.
- No general import dashboard or DvirOS end-user page exists in v0.3.
  A future API and UI will expose the provenance and quality reports.
