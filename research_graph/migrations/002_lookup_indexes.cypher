// Secondary indexes never determine canonical identity. Preserve raw exact refs.
CREATE INDEX passage_work_lookup IF NOT EXISTS FOR (n:Passage) ON (n.work_id);
CREATE INDEX passage_edition_lookup IF NOT EXISTS FOR (n:Passage) ON (n.edition_id);
CREATE INDEX passage_source_ref_lookup IF NOT EXISTS FOR (n:Passage) ON (n.source_ref);
CREATE INDEX work_provider_ref_lookup IF NOT EXISTS FOR (n:Work) ON (n.provider_ref);
CREATE INDEX alias_normalized_lookup IF NOT EXISTS FOR (n:NameAlias) ON (n.normalized_key);
CREATE INDEX source_provider_lookup IF NOT EXISTS FOR (n:SourceRecord) ON (n.provider);
CREATE INDEX evidence_review_lookup IF NOT EXISTS FOR (n:Evidence) ON (n.review_status);
CREATE INDEX evidence_kind_lookup IF NOT EXISTS FOR (n:Evidence) ON (n.claim_kind);
CREATE INDEX import_run_status_lookup IF NOT EXISTS FOR (n:ImportRun) ON (n.status);
