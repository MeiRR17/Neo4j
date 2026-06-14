// =============================================================
// Script 04 - Analytical Queries on the Jewish Philosophy Graph
// Run each query block individually in Neo4j Browser
// =============================================================


// ─────────────────────────────────────────────────────────────
// QUESTION 1: Shortest Path (Pathfinding)
// "What is the shortest conceptual chain linking Saadia Gaon's
//  'Emunot VeDeot' to 'Nefesh HaChaim', and which intermediate
//  thinkers does it pass through?"
//
// Graph algorithm: Breadth-First Search via shortestPath()
// Why non-trivial: Relational DBs cannot express variable-depth
// path queries efficiently. This leverages native graph traversal.
// ─────────────────────────────────────────────────────────────
MATCH p = shortestPath(
  (source:Text {title: "Emunot VeDeot"})-[*..10]-(target:Text {title: "Nefesh HaChaim"})
)
RETURN
  [node IN nodes(p) | node.title]  AS PathNodes,
  [rel  IN rels(p)  | rel.type]    AS RelationshipTypes,
  length(p)                         AS PathLength;


// ─────────────────────────────────────────────────────────────
// QUESTION 2: Authority Hubs (In-Degree Centrality)
// "Which philosophical work is cited most often by others,
//  marking it as the foundational 'authority hub' of the tradition?"
//
// Graph algorithm: In-degree centrality (manual computation)
// Why non-trivial: Ranks nodes by incoming edge count — equivalent
// to a simplified PageRank and impossible to express in SQL without
// self-joins across unknown depth.
// ─────────────────────────────────────────────────────────────
MATCH (t:Text)<-[:CITES]-(citingText:Text)
RETURN
  t.title        AS Authority,
  count(citingText) AS CitationCount
ORDER BY CitationCount DESC
LIMIT 10;


// ─────────────────────────────────────────────────────────────
// QUESTION 3: Echo Chambers (Bi-directional / Mutual Citations)
// "Are there works that only cite and are cited within a closed
//  sub-group — a conceptual echo chamber?"
//
// Graph algorithm: Cycle detection via mutual-edge pattern match
// Why non-trivial: Detects directed cycles in a graph — a pattern
// with no natural SQL equivalent. In Neo4j this is a single MATCH.
// ─────────────────────────────────────────────────────────────
MATCH (a:Text)-[:CITES]->(b:Text)-[:CITES]->(a)
WITH a, b
WHERE a.title < b.title   // deduplicate symmetric pairs
RETURN
  a.title AS TextA,
  b.title AS TextB,
  "Mutual citation (potential echo chamber)" AS Note
ORDER BY TextA
LIMIT 50;


// ─────────────────────────────────────────────────────────────
// QUESTION 4: Dependency Tree (Multi-Hop Traversal)
// "What is the full dependency tree of 'Moreh Nevukhim' —
//  which foundational texts does it rest upon up to 3 hops away?"
//
// Graph algorithm: Fixed-depth BFS with aggregation
// Why non-trivial: Variable-depth reachability (1..3 hops) would
// require 3 separate SQL self-joins; Cypher expresses it in one line.
// ─────────────────────────────────────────────────────────────
MATCH (rambam:Text {title: "Moreh Nevukhim"})-[:CITES*1..3]->(foundational:Text)
RETURN
  foundational.title AS FoundationalText,
  count(*)           AS ReachFrequency
ORDER BY ReachFrequency DESC
LIMIT 30;


// ─────────────────────────────────────────────────────────────
// QUESTION 5: Co-Citation Outliers (Implicit Intellectual Kinship)
// "Which two texts that never cite each other are consistently
//  co-cited by later works? This reveals hidden conceptual kinship
//  recognized only by posterity."
//
// Graph algorithm: Co-citation analysis with negative edge filter
// Why non-trivial: Combines multi-hop traversal with a negative
// structural constraint (NOT exists) — deeply expensive in SQL,
// trivially expressed in Cypher.
// ─────────────────────────────────────────────────────────────
MATCH (laterText:Text)-[:CITES]->(textA:Text),
      (laterText)-[:CITES]->(textB:Text)
WHERE textA.title < textB.title          // deduplicate pairs
  AND NOT (textA)-[:CITES]-(textB)       // no direct link between them
WITH textA, textB, count(DISTINCT laterText) AS CoCitationScore
WHERE CoCitationScore > 1
RETURN
  textA.title      AS TextA,
  textB.title      AS TextB,
  CoCitationScore  AS SharedCitingWorks
ORDER BY CoCitationScore DESC
LIMIT 10;


// =============================================================
// BONUS: Full Graph Statistics Summary
// =============================================================
MATCH (t:Text)
OPTIONAL MATCH (t)<-[in:CITES]-()
OPTIONAL MATCH (t)-[out:CITES]->()
RETURN
  t.title                   AS Text,
  count(DISTINCT in)        AS InDegree,
  count(DISTINCT out)       AS OutDegree,
  count(DISTINCT in) + count(DISTINCT out) AS TotalDegree
ORDER BY TotalDegree DESC
LIMIT 20;
