"""Private DvirOS Research API v0.5.0: fixed read-only operations.

Only a local server-to-server bearer token is supported in v0.5.
DvirOS identity/roles, reverse proxy TLS, rate limiting and service auth
will be implemented at the cross-repo integration boundary (v0.6/0.14).
"""
from __future__ import annotations

from pathlib import Path
import os
import uuid

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from research_graph.ontology import CLAIM_KINDS, REVIEW_STATUSES, require_canonical_id
from scripts.migrate import load_migrations
from services.research_api.config import check_bearer
from services.research_api.contract import RESEARCH_CONTRACT
from services.research_api.signature import ReplayGuard, verify_signed_request
from services.research_api.db import DatabaseUnavailable, ReadOnlyQueryClient
from services.research_api.models import (
    Concept, ErrorResponse, EvidenceLink, Neighborhood, Page, Passage, Person, Readiness,
    SourceRecord, Work, MetadataSearchPage,
)
from services.research_api.queries import (
    DETAIL_KINDS, LIST_KINDS, VALID_EDGE_TYPES,
)
from services.research_api.metadata_search import search_metadata, validate_search


security = HTTPBearer(auto_error=False)
SCHEMA_VERSION = "0.5.0"

ERROR_MESSAGES = {
    400: ("BAD_REQUEST", "Invalid query or canonical identifier."),
    401: ("UNAUTHENTICATED", "Bearer authentication required."),
    403: ("FORBIDDEN", "Access forbidden."),
    404: ("NOT_FOUND", "Research record not found."),
    405: ("METHOD_NOT_ALLOWED", "Method is not permitted."),
    422: ("VALIDATION_ERROR", "Invalid or out-of-bounds request."),
    503: ("UNAVAILABLE", "Research storage or configuration unavailable."),
}

DETAIL_CLASSES = {
    "work": Work,
    "person": Person,
    "passage": Passage,
    "concept": Concept,
    "source": SourceRecord,
}
PAGE_CLASSES = {
    "works": Work,
    "persons": Person,
    "passages": Passage,
    "concepts": Concept,
    "links": EvidenceLink,
}
PREFIXES = {
    "work": "work", "person": "person", "passage": "passage",
    "concept": "concept", "source": "source", "edge": "edge",
}
DEFAULT_EDGES = "SOURCE_LINK,HAS_EDITION,HAS_PASSAGE,AUTHORED,MENTIONS_CONCEPT"


def raise_http(status: int) -> None:
    raise HTTPException(status_code=status)


def checked_id(raw: str, expected_prefix: str) -> str:
    try:
        normalized = require_canonical_id(raw)
    except ValueError:
        raise_http(400)
    if not normalized.startswith(expected_prefix + ":"):
        raise_http(400)
    return normalized


def checked_cursor(value: str | None, prefix: str) -> str:
    if not value:
        return ""
    return checked_id(value, prefix)


def checked_search(value: str) -> str:
    if len(value) > 100 or any(ord(char) < 32 for char in value):
        raise_http(422)
    return value.strip()


def checked_edges(value: str) -> list[str]:
    edges = value.split(",")
    if not edges or len(edges) > 10 or len(set(edges)) != len(edges):
        raise_http(422)
    if any(edge not in VALID_EDGE_TYPES for edge in edges):
        raise_http(422)
    return edges


def page_from_rows(rows: list[dict], model: type, limit: int) -> dict:
    subset = rows[:limit]
    return {
        "schema_version": SCHEMA_VERSION,
        "items": [model.model_validate(row).model_dump() for row in subset],
        "next_cursor": subset[-1]["id"] if len(rows) > limit and subset else None,
        "corpus_status": "unreviewed_metadata_only",
    }


def create_app(*, backend=None, token_path: Path | None = None,
               signature_path: Path | None = None) -> FastAPI:
    """Construction accepts a backend injection for tests only, never web clients."""
    app = FastAPI(
        title="DvirOS Jewish Philosophy Research API",
        version=SCHEMA_VERSION,
        description="Private, evidence-first, metadata-only bounded graph read API.",
        docs_url="/docs", redoc_url=None,
        openapi_url="/openapi.json",
        responses={code: {"model": ErrorResponse} for code in (400, 401, 403, 404, 422, 503)},
    )
    store = backend if backend is not None else ReadOnlyQueryClient()
    replay_guard = ReplayGuard()

    @app.middleware("http")
    async def request_metadata(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def error_payload(request: Request, status_code: int) -> dict:
        code, message = ERROR_MESSAGES.get(
            status_code, ("REQUEST_FAILED", "Request could not be completed.")
        )
        return {
            "error": {
                "code": code, "message": message,
                "request_id": getattr(request.state, "request_id", ""),
            }
        }

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        status = exc.status_code
        return JSONResponse(status_code=status, content=error_payload(request, status))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content=error_payload(request, 422))

    @app.exception_handler(DatabaseUnavailable)
    async def database_error(request: Request, exc: DatabaseUnavailable):
        return JSONResponse(status_code=503, content=error_payload(request, 503))

    @app.exception_handler(ValueError)
    async def configuration_error(request: Request, exc: ValueError):
        # Internal configuration errors are not client validation errors.
        return JSONResponse(status_code=503, content=error_payload(request, 503))

    async def require_service_token(
        request: Request,
        authorization: HTTPAuthorizationCredentials | None = Depends(security),
    ) -> None:
        if authorization is None:
            raise_http(401)
        try:
            if not check_bearer(authorization.credentials, path=token_path):
                raise_http(403)
        except ValueError:
            raise_http(503)
        mode = os.getenv("DVIROS_REQUIRE_SIGNED_CALLS", "0")
        if mode not in ("0", "1"):
            raise_http(503)
        if mode == "1":
            raw_path = request.scope.get("raw_path", b"")
            query_bytes = request.scope.get("query_string", b"")
            try:
                target = raw_path.decode("ascii")
                if query_bytes:
                    target += "?" + query_bytes.decode("ascii")
                verified = verify_signed_request(
                    request.headers, target, path=signature_path,
                    guard=replay_guard,
                )
            except (ValueError, OSError, UnicodeError):
                raise_http(503)
            if not verified:
                raise_http(403)

    def fetch(operation: str, params: dict | None = None) -> list[dict]:
        return store.query(operation, params or {})

    def schema_ready() -> None:
        expected = {m.id: m.checksum for m in load_migrations()}
        found = {row["id"]: row["checksum"] for row in fetch("ready")}
        if not expected or any(found.get(m) != digest for m, digest in expected.items()):
            raise DatabaseUnavailable("Schema is missing or incompatible.")

    @app.get("/health/live", tags=["Health"])
    def live():
        return {"status": "alive", "api_version": SCHEMA_VERSION}

    @app.get("/health/ready", response_model=Readiness, tags=["Health"])
    def ready():
        # The API token must be provisioned even for a public readiness check.
        from services.research_api.config import load_token
        load_token(token_path)
        schema_ready()
        return Readiness()

    def list_entities(kind: str, query: str, cursor: str | None,
                      limit: int, language: str = "", passage_id: str = "",
                      claim_kind: str = "", review_status: str = "") -> dict:
        prefix, operation = LIST_KINDS[kind]
        params = {
            "query": checked_search(query), "cursor": checked_cursor(cursor, prefix),
            "fetch_limit": limit + 1, "language": language,
            "passage_id": passage_id, "claim_kind": claim_kind,
            "review_status": review_status,
        }
        return page_from_rows(fetch(operation, params), PAGE_CLASSES[kind], limit)

    @app.get("/v1/integration/contract", tags=["Integration"],
             dependencies=[Depends(require_service_token)])
    def integration_contract():
        return dict(RESEARCH_CONTRACT)

    @app.get("/v1/works", response_model=Page[Work], tags=["Research"],
             dependencies=[Depends(require_service_token)])
    def works(query: str = Query(default="", max_length=100),
              language: str = Query(default="", pattern="^(|he|en|ar|yi)$"),
              cursor: str | None = None,
              limit: int = Query(default=20, ge=1, le=50)):
        return list_entities("works", query, cursor, limit, language=language)

    @app.get("/v1/persons", response_model=Page[Person], tags=["Research"],
             dependencies=[Depends(require_service_token)])
    def persons(query: str = Query(default="", max_length=100),
                cursor: str | None = None,
                limit: int = Query(default=20, ge=1, le=50)):
        return list_entities("persons", query, cursor, limit)

    @app.get("/v1/passages", response_model=Page[Passage], tags=["Research"],
             dependencies=[Depends(require_service_token)])
    def passages(query: str = Query(default="", max_length=100),
                 cursor: str | None = None,
                 limit: int = Query(default=20, ge=1, le=50)):
        return list_entities("passages", query, cursor, limit)

    @app.get("/v1/concepts", response_model=Page[Concept], tags=["Research"],
             dependencies=[Depends(require_service_token)])
    def concepts(query: str = Query(default="", max_length=100),
                 cursor: str | None = None,
                 limit: int = Query(default=20, ge=1, le=50)):
        return list_entities("concepts", query, cursor, limit)

    @app.get("/v1/search/metadata", response_model=MetadataSearchPage,
             tags=["Research"], dependencies=[Depends(require_service_token)])
    def metadata_search(request: Request,
                        kind: str = Query(...),
                        query: str = Query(default="", max_length=100),
                        cursor: str | None = None,
                        limit: int = Query(default=10, ge=1, le=20),
                        language: str = ""):
        # FastAPI normally ignores unknown query keys. Fail closed instead:
        # unsupportable rights/author/facet filters must NEVER be silently dropped.
        provided = [key for key, _ in request.query_params.multi_items()]
        allowed = {"kind", "query", "cursor", "limit", "language"}
        if (len(provided) > len(allowed) or len(set(provided)) != len(provided)
                or any(key not in allowed for key in provided)):
            raise_http(422)
        try:
            validate_search(kind, query, cursor, limit, language)
        except (ValueError, TypeError):
            raise_http(422)
        return search_metadata(store, kind=kind, query=query, cursor=cursor,
                               limit=limit, language=language)

    @app.get("/v1/links", response_model=Page[EvidenceLink], tags=["Research"],
             dependencies=[Depends(require_service_token)])
    def links(passage_id: str = "", claim_kind: str = "",
              review_status: str = "", cursor: str | None = None,
              limit: int = Query(default=20, ge=1, le=50)):
        if passage_id:
            checked_id(passage_id, "passage")
        if claim_kind and claim_kind not in CLAIM_KINDS:
            raise_http(422)
        if review_status and review_status not in REVIEW_STATUSES:
            raise_http(422)
        return list_entities("links", "", cursor, limit,
                             passage_id=passage_id, claim_kind=claim_kind,
                             review_status=review_status)

    def lookup(kind: str, id_value: str, model: type) -> dict:
        checked_id(id_value, DETAIL_KINDS[kind])
        rows = fetch(kind, {"id": id_value})
        if not rows:
            raise_http(404)
        if len(rows) != 1:
            raise DatabaseUnavailable("Duplicate canonical ID.")
        return model.model_validate(rows[0]).model_dump()

    @app.get("/v1/works/{work_id}", response_model=Work, tags=["Research"],
             dependencies=[Depends(require_service_token)])
    def work(work_id: str):
        return lookup("work", work_id, Work)

    @app.get("/v1/persons/{person_id}", response_model=Person, tags=["Research"],
             dependencies=[Depends(require_service_token)])
    def person(person_id: str):
        return lookup("person", person_id, Person)

    @app.get("/v1/passages/{passage_id}", response_model=Passage, tags=["Research"],
             dependencies=[Depends(require_service_token)])
    def passage(passage_id: str):
        return lookup("passage", passage_id, Passage)

    @app.get("/v1/concepts/{concept_id}", response_model=Concept, tags=["Research"],
             dependencies=[Depends(require_service_token)])
    def concept(concept_id: str):
        return lookup("concept", concept_id, Concept)

    @app.get("/v1/sources/{source_id}", response_model=SourceRecord, tags=["Research"],
             dependencies=[Depends(require_service_token)])
    def source(source_id: str):
        return lookup("source", source_id, SourceRecord)

    @app.get("/v1/graph/neighborhood", response_model=Neighborhood,
             tags=["Graph"], dependencies=[Depends(require_service_token)])
    def neighborhood(entity_id: str, depth: int = Query(default=1, ge=1, le=2),
                     edge_types: str = DEFAULT_EDGES,
                     limit: int = Query(default=20, ge=1, le=20)):
        checked_id(entity_id, entity_id.split(":", 1)[0])
        if not entity_id.startswith(("work:", "person:", "passage:", "concept:")):
            raise_http(422)
        edges = checked_edges(edge_types)
        rows = fetch(f"neighborhood_{depth}", {
            "id": entity_id, "edge_types": edges, "fetch_limit": limit + 1,
        })
        return {
            "schema_version": SCHEMA_VERSION,
            "entity_id": entity_id, "depth": depth,
            "paths": rows[:limit],
            "has_more": len(rows) > limit,
            "note": "Graph connectivity is not evidence of influence or agreement.",
        }

    @app.get("/v1/data/status", tags=["Research"],
             dependencies=[Depends(require_service_token)])
    def status():
        rows = fetch("data_status")
        counts = rows[0] if rows else {}
        return {
            "schema_version": SCHEMA_VERSION,
            "corpus_status": "human_review_pending",
            "human_quality_release_approved": False,
            "texts_available": False,
            "counts": {
                "works": counts.get("works", 0),
                "passages": counts.get("passages", 0),
                "evidence_records": counts.get("evidence_records", 0),
                "editions": counts.get("editions", 0),
            },
        }

    return app


app = create_app()
