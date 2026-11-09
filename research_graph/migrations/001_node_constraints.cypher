// v0.2.0 canonical entity key constraints (compatible with Neo4j Community).
// Existing legacy :Text nodes are left untouched; no destructive migration.
CREATE CONSTRAINT schema_migration_id IF NOT EXISTS FOR (n:SchemaMigration) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT work_canonical_id IF NOT EXISTS FOR (n:Work) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT passage_canonical_id IF NOT EXISTS FOR (n:Passage) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT person_canonical_id IF NOT EXISTS FOR (n:Person) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT concept_canonical_id IF NOT EXISTS FOR (n:Concept) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT edition_canonical_id IF NOT EXISTS FOR (n:Edition) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT source_record_canonical_id IF NOT EXISTS FOR (n:SourceRecord) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT evidence_canonical_id IF NOT EXISTS FOR (n:Evidence) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT import_run_canonical_id IF NOT EXISTS FOR (n:ImportRun) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT name_alias_canonical_id IF NOT EXISTS FOR (n:NameAlias) REQUIRE n.id IS UNIQUE;
