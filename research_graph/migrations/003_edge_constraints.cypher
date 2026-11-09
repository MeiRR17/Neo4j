// A unique relationship ID is mandatory by the application contract.
// Neo4j Community uniqueness constraints only check relationships with IDs;
// all writers MUST use the ontology edge builder, never unguarded CREATE.
CREATE CONSTRAINT authored_edge_id IF NOT EXISTS FOR ()-[r:AUTHORED]-() REQUIRE r.id IS UNIQUE;
CREATE CONSTRAINT has_passage_edge_id IF NOT EXISTS FOR ()-[r:HAS_PASSAGE]-() REQUIRE r.id IS UNIQUE;
CREATE CONSTRAINT has_edition_edge_id IF NOT EXISTS FOR ()-[r:HAS_EDITION]-() REQUIRE r.id IS UNIQUE;
CREATE CONSTRAINT in_edition_edge_id IF NOT EXISTS FOR ()-[r:IN_EDITION]-() REQUIRE r.id IS UNIQUE;
CREATE CONSTRAINT mentions_concept_edge_id IF NOT EXISTS FOR ()-[r:MENTIONS_CONCEPT]-() REQUIRE r.id IS UNIQUE;
CREATE CONSTRAINT source_link_edge_id IF NOT EXISTS FOR ()-[r:SOURCE_LINK]-() REQUIRE r.id IS UNIQUE;
CREATE CONSTRAINT human_claim_edge_id IF NOT EXISTS FOR ()-[r:HUMAN_CLAIM]-() REQUIRE r.id IS UNIQUE;
CREATE CONSTRAINT suggested_relation_edge_id IF NOT EXISTS FOR ()-[r:SUGGESTED_RELATION]-() REQUIRE r.id IS UNIQUE;
CREATE CONSTRAINT has_alias_edge_id IF NOT EXISTS FOR ()-[r:HAS_ALIAS]-() REQUIRE r.id IS UNIQUE;
CREATE CONSTRAINT has_evidence_edge_id IF NOT EXISTS FOR ()-[r:HAS_EVIDENCE]-() REQUIRE r.id IS UNIQUE;
