// v0.9.12 metadata-only audit-observation ledger, not immutable Work data.
// The unique scope and revision IDs support a single-head CAS write protocol.
// Other Neo4j principals can still change data; production DB roles pending.
CREATE CONSTRAINT audit_revision_head_id IF NOT EXISTS FOR (n:AuditRevisionHead) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT audit_revision_id IF NOT EXISTS FOR (n:AuditRevision) REQUIRE n.id IS UNIQUE;
CREATE INDEX audit_revision_scope_sequence IF NOT EXISTS FOR (n:AuditRevision) ON (n.scope_id, n.sequence);
