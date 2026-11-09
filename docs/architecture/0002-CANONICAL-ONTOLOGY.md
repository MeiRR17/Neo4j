# ADR 0002 — Canonical Jewish-philosophy ontology and evidence governance

**Status:** Implemented graph schema baseline in v0.2.0; populated production corpus is NOT available.
**Parent:** [ADR 0001](0001-DVIROS-INTEGRATION.md).
**No changes in Learning_Modules.** Legacy `:Text` remains untouched.

## 1. Research entities

| Neo4j node label | ID prefix | Mandatory keys for future writers | Purpose |
| --- | --- | --- | --- |
| Work | `work:` | `id`, `provider`, `provider_ref`, `title` | Intellectual work, independent of title translations |
| Edition | `edition:` | `id`, `work_id`, `version_id`, `rights_tag` | Licensed edition / translation identity |
| Passage | `passage:` | `id`, `work_id`, `edition_id`, `source_ref` | Exact anchored passage; do not truncate chapters |
| Person | `person:` | `id`, `display_name`, `date_from_year?`, `date_to_year?` | Researcher-author with uncertain dates allowed |
| Concept | `concept:` | `id`, `preferred_label`, `language` | Controlled vocabulary (not LLM-generated assertions) |
| SourceRecord | `source:` | `id`, `provider`, `source_uri`, `version_id`, `rights_tag`, `checksum_sha256` | Data-lineage source snapshot reference |
| Evidence | `evidence:` | `id`, `source_record_id`, `source_ref`, `source_uri`, `version_id`, `rights_tag`, `claim_kind`, `review_status` | Exact evidence and interpretation boundary |
| ImportRun | `import:` | `id`, `source_snapshot_id`, `status` | Auditable ingestion attempts / checkpoints |
| NameAlias | `alias:` | `id`, `entity_id`, `language`, `display`, `normalized_key` | Hebrew/English aliases; never identity |
| SchemaMigration | raw `001` etc. | `id`, `checksum`, `schema_version`, `applied_at` | Versioned migration ledger |

IDs are SHA-256 of a JSON-framed tuple of normalized immutable provider identifiers.
For `Work` use `(provider, provider_work_id)`, **not** a readable title.
For `Edition` use `(work_id, provider_edition_id)`.
For `Passage` use `(edition_id, exact full canonical_ref)`.
Internal whitespace and chapter syntax are **not** split or collapsed.
NFC Unicode normalization is only a representation normalization.
`alias_search_key` uses accent/niqqud stripping and whitespace folding for **search only**.

Language is a tag (`he`, `en`, `ar`, `yi`, `other`), separate from entity identity.
Historical dates are explicit optional integer ranges, not implied chronology.
Edition text is **not** embedded by default; retrieval respects per-edition rights.

## 2. Relationships and evidence

| Relationship | Source -> target | Interpretation |
| --- | --- | --- |
| AUTHORED | Person -> Work | Authorship attributed by evidence |
| HAS_EDITION | Work -> Edition | Version lineage |
| HAS_PASSAGE | Work -> Passage | Passage membership |
| IN_EDITION | Passage -> Edition | Passage version reference |
| MENTIONS_CONCEPT | Passage -> Concept | Curated concept annotation |
| SOURCE_LINK | Passage -> Passage | Observed external cross-reference, not necessarily a citation |
| HUMAN_CLAIM | Passage -> Concept | Human interpretation, requires review |
| SUGGESTED_RELATION | Passage -> Concept | AI hypothesis; unverified |
| HAS_ALIAS | Work -> NameAlias | Search/display variant |
| HAS_EVIDENCE | SourceRecord -> Evidence | Evidence provenance lineage |

**All edges created by the application must carry** `id`, `evidence_id`,
`claim_kind` and `review_status`. Neo4j Community uniqueness constraints
guarantee ID uniqueness **when supplied**, not mandatory property existence.
Consequently the edge writer validates IDs/type/kind and requires an existing
Evidence node with matching kind before creating a relation. Do not directly
use ad-hoc `CREATE` to bypass this contract.

`SOURCE_LINK` = `OBSERVED_SOURCE_LINK` — observed provider relationship only.
`HUMAN_CLAIM` = `HUMAN_INTERPRETATION`.
`SUGGESTED_RELATION` = `MODEL_SUGGESTION` — never automatically approved.

Evidence statuses: `unreviewed`, `approved`, `rejected`, `disputed`.
Approval requires an identified human reviewer; **v0.2 is not the approval UI**.
Only human review in DvirOS may promote knowledge. Research analysis may
expose graph connectivity, but must not claim causal influence, authority,
agreement or chronology without independent evidence.

## 3. Migration and safety model

- Three **append-only** schema files in `research_graph/migrations`; manifest is
  complete and order-sensitive. The runner accepts only `CREATE CONSTRAINT`
  and `CREATE INDEX` statements with `IF NOT EXISTS`.
- A `:SchemaMigration` ledger records migration ID, SHA256 of the original
  source file, schema version and execution timestamp.
- The runner checks every existing checksum and rejects changed migration
  source, out-of-order markers, unexpected files, symlinks and nonlocal URLs.
- Safe repeated `apply`: no schema changes once the version is recorded.
  If execution stops midway, already-created DDL can be run again safely
  before the version marker is recorded. **Run exactly one migrator at a time**.
- No automatic down-migrations. Removing a uniqueness constraint may allow
  duplicates; deleting graph objects may destroy research evidence.
- **Rollback:** restore tested offline database backup into an isolated
  instance; only then switch traffic after compatible readers verified.
  v0.13.0 will automate restore drills and backup policy.
- Existing `:Text` legacy labels and demo source scripts are not migrated.
  A reviewed adapter will be built in v0.3–v0.4 after source provenance
  correction. No synthetic fixtures persist in the database after CI checks.

### Developer commands

```sh
python scripts/bootstrap.py
docker compose up -d --wait
python scripts/migrate.py dry-run
python scripts/migrate.py apply
python scripts/migrate.py apply
python scripts/migrate.py check
python -m unittest discover -s tests -v
```

Only run `scripts/ontology_smoke.py --allow-synthetic` on a disposable
test database (CI enabled) to prevent fixture pollution.

## 4. Release-gate limitations

These are schema + contract tests, **not** proof the real Sefaria data is
correct or license-cleared. v0.3 adds source adapters, checkpoints and
quarantine; v0.4 provides reviewed examples and data-quality gates.
The v0.5 API will expose read-only operations with bounded graph traversals.
No independent user-facing Neo4j app will be built.
