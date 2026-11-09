// v0.8.3 secondary metadata prefix indexes: no identity change and no text bodies.
CREATE INDEX work_search_key_v1 IF NOT EXISTS FOR (n:Work) ON (n.search_key_v1);
CREATE INDEX person_search_key_v1 IF NOT EXISTS FOR (n:Person) ON (n.search_key_v1);
CREATE INDEX passage_search_key_v1 IF NOT EXISTS FOR (n:Passage) ON (n.search_key_v1);
CREATE INDEX concept_search_key_v1 IF NOT EXISTS FOR (n:Concept) ON (n.search_key_v1);
