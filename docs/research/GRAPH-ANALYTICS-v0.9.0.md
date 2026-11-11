# v0.9.0 - Evidence-linked graph analytics (first slice, DRAFT)

Two read-only analytics endpoints expose exploratory metadata observations,
not historical arguments or research-grade proofs. They use the existing
bearer and DvirOS signed-call policy; clients never supply Cypher.

## Routes

- GET /v1/analysis/source-links?passage_id=passage:CANONICAL_ID&limit=10
  returns observed directed SOURCE_LINK edges attached to a passage. Each
  item includes both canonical endpoints, an Evidence ID, source reference,
  version and rights tag, plus edge and evidence review statuses.
- GET /v1/analysis/shared-targets?passage_id=passage:CANONICAL_ID&limit=10
  returns shared-outgoing-target candidates, including both exact Evidence
  IDs and their separate source references and review statuses. This is
  co-reference, not proof of co-citation or historical influence.

The server requires authenticated private API access, canonical passage IDs,
fixed operation names, and strict request parameter allowlists. Unknown or
duplicate query parameters and unsafe graph projections are rejected.
At most 20 rows plus one lookahead are returned. No source excerpts,
rights promotion, authority ratings or scholarly approval are emitted.

## Nonclaims and release controls

A returned relationship is an observed provider link, not a proven citation.
Shared targets are exploratory research hypotheses, not evidence of agreement,
chronology, causality, intellectual transmission or historical influence.
The requested limit caps output only: it does not cap all database work or
attest a consistent corpus snapshot. The existing database timeout, row and
byte budgets remain in force. has_more=false does not certify completeness.
Responses deny verified rights and influence and retain release HOLD.

Synthetic API tests exercise the real FastAPI contract with fake graph rows.
They are not independent scholarly review. To finish v0.9.0, implement
bounded evidence shortest paths, defined frequency measures, chronology
constraints and author/work comparisons; manually review 100+ links and
20 genuine analytical cases; measure query performance. The 50 genuine
reviewed v0.8 search questions, rights and DvirOS security signoffs
remain outstanding. No production release is authorized.
