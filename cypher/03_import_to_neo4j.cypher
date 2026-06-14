// =============================================================
// Script 03 - Neo4j Data Import
// Run each block sequentially in Neo4j Browser (http://localhost:7474)
// Prerequisites: sefaria_links.csv must be in C:\neo4j\import\
// =============================================================

// --- Step 1: Create constraint + index for fast lookups ---
CREATE CONSTRAINT unique_text_title IF NOT EXISTS
FOR (t:Text) REQUIRE t.title IS UNIQUE;

CREATE INDEX text_title_index IF NOT EXISTS
FOR (t:Text) ON (t.title);


// --- Step 2: Import CSV and build the knowledge graph ---
// Use periodic commit for large files (>100k rows)
:auto LOAD CSV WITH HEADERS FROM 'file:///sefaria_links.csv' AS row
CALL {
  WITH row
  MERGE (source:Text {title: row.Source_Text})
  MERGE (target:Text {title: row.Target_Text})
  MERGE (source)-[r:CITES {type: row.Connection_Type}]->(target)
} IN TRANSACTIONS OF 1000 ROWS;


// --- Step 3: Verify import ---
MATCH (t:Text) RETURN count(t) AS TotalTextNodes;
MATCH ()-[r:CITES]->() RETURN count(r) AS TotalCitationEdges;
