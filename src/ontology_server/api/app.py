"""Combined FastAPI + MCP application.

This module provides HTTP endpoints alongside the MCP server.
MCP is served via SSE at /sse for multi-client access.
"""

from typing import Any, TYPE_CHECKING
import hashlib
import hmac
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..auth import StaticTokenVerifier
from ..config import Settings
from ..core.store import OntologyStore
from ..core.validation import SHACLValidator
from ..mcp.server import create_mcp_server

if TYPE_CHECKING:
    from knowledge_graph import KnowledgeGraphStore

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger(f"{__name__}.audit")


def create_app(
    settings: Settings,
    store: OntologyStore,
    validator: SHACLValidator,
    kg_store: "KnowledgeGraphStore | None" = None
) -> FastAPI:
    """Create combined FastAPI application with MCP SSE support.

    Args:
        settings: Server configuration
        store: Initialized ontology store
        validator: SHACL validator instance
        kg_store: Optional knowledge graph store for A-Box functionality

    Returns:
        Configured FastAPI application with MCP mounted at /sse
    """
    app = FastAPI(
        title="Ontology Server",
        description="Unified MCP and REST API for ontology management",
        version="0.1.0",
    )

    # Store references for route handlers
    app.state.store = store
    app.state.validator = validator
    app.state.settings = settings

    # CORS middleware for web clients
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Bearer token authentication middleware (only when api_key is configured)
    if settings.api_key:
        verifier = StaticTokenVerifier(settings.api_key)

        # Pre-compute the expected cookie value for dashboard session auth
        _session_cookie = hmac.new(
            settings.api_key.encode(), b"ontology-dashboard-session", hashlib.sha256
        ).hexdigest()

        class BearerAuthMiddleware(BaseHTTPMiddleware):
            AUTH_EXEMPT_PATHS = {"/health", "/dashboard/login"}
            AUTH_EXEMPT_PREFIXES = ("/dashboard/static/",)

            async def dispatch(self, request: Request, call_next):
                path = request.url.path
                if path in self.AUTH_EXEMPT_PATHS or path.startswith(
                    self.AUTH_EXEMPT_PREFIXES
                ):
                    return await call_next(request)

                # 1. Bearer token (API clients, MCP)
                auth_header = request.headers.get("authorization", "")
                if auth_header.startswith("Bearer "):
                    token = auth_header[7:]
                    access_token = await verifier.verify_token(token)
                    if access_token is not None:
                        audit_logger.info(
                            "Authenticated request: %s %s client=%s",
                            request.method, path, access_token.client_id,
                        )
                        return await call_next(request)

                # 2. Session cookie (browser dashboard)
                cookie = request.cookies.get("dashboard_session", "")
                if cookie and hmac.compare_digest(cookie, _session_cookie):
                    return await call_next(request)

                # 3. Unauthenticated — redirect browsers to login, 401 for API
                if path.startswith("/dashboard"):
                    return RedirectResponse(url="/dashboard/login", status_code=302)
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Missing or invalid Authorization header"},
                    headers={"WWW-Authenticate": "Bearer"},
                )

        app.add_middleware(BearerAuthMiddleware)
        app.state.session_cookie_value = _session_cookie
        app.state.token_verifier = verifier
        logger.info("Bearer token authentication enabled")

    # Health check endpoint
    @app.get("/health")
    async def health_check() -> dict[str, Any]:
        """Health check endpoint."""
        ontologies = store.list_ontologies()
        return {
            "status": "healthy",
            "ontology_count": len(ontologies),
            "total_triples": len(store),
        }

    # Basic ontology listing (Phase 3 will add full REST CRUD)
    @app.get("/ontologies")
    async def list_ontologies() -> list[dict[str, Any]]:
        """List all loaded ontologies."""
        return store.list_ontologies()

    @app.get("/ontologies/{uri:path}")
    async def get_ontology(uri: str) -> dict[str, Any]:
        """Get ontology by URI."""
        full_uri = f"ontology://{uri}"
        ttl = store.get_ontology_ttl(full_uri)
        if not ttl:
            return {"error": f"Ontology not found: {full_uri}"}
        return {"uri": full_uri, "content": ttl}

    # Basic SPARQL endpoint
    @app.post("/sparql")
    async def sparql_query(query: str, ontology_uri: str | None = None) -> dict[str, Any]:
        """Execute SPARQL query."""
        try:
            results = store.query(query, ontology_uri)
            output = []
            for row in results:
                row_dict = {}
                for var in row.labels:
                    value = row[var]
                    row_dict[str(var)] = str(value) if value else None
                output.append(row_dict)
            return {"results": output, "count": len(output)}
        except Exception as e:
            return {"error": str(e)}

    # SHACL validation endpoint
    @app.post("/validate")
    async def validate_instance(request: Request) -> dict[str, Any]:
        """Validate an RDF instance against a SHACL shape.

        Accepts JSON body with:
            instance_uri: URI of the instance to validate
            shape_uri: URI of the SHACL shape to validate against
            ontology: Optional ontology URI to scope the lookup

        Looks for the instance in KG phases graph first (A-Box),
        then falls back to OntologyStore (T-Box/legacy).
        """
        from rdflib import URIRef as _URIRef, Graph as _Graph

        try:
            body = await request.json()
            instance_uri = body.get("instance_uri")
            shape_uri = body.get("shape_uri")
            ontology_uri = body.get("ontology")

            if not instance_uri or not shape_uri:
                return {"error": "instance_uri and shape_uri are required"}

            instance_ttl = None

            # Step 1: Try KG phases graph first (A-Box)
            if kg_store is not None:
                from knowledge_graph.core.store import GRAPH_PHASES
                # Semantic existence check via SPARQL ASK (not substring match)
                exists = kg_store.ask(
                    f"ASK {{ GRAPH <{GRAPH_PHASES}> {{ <{instance_uri}> ?p ?o }} }}"
                )
                if exists:
                    instance_ttl = kg_store.export_turtle(GRAPH_PHASES)

            # Step 2: Fall back to OntologyStore (legacy)
            if instance_ttl is None:
                instance_ref = _URIRef(instance_uri)
                source_graph = None
                if ontology_uri:
                    source_graph = store._graphs.get(ontology_uri)
                else:
                    for uri, graph in store._graphs.items():
                        if (instance_ref, None, None) in graph:
                            source_graph = graph
                            break

                if source_graph is not None and (instance_ref, None, None) in source_graph:
                    instance_ttl = source_graph.serialize(format="turtle")

            if instance_ttl is None:
                return {
                    "conforms": False,
                    "violation_count": 1,
                    "violations": [{"message": f"No triples found for instance: {instance_uri}"}],
                    "report": f"Instance {instance_uri} not found in store",
                }

            # Step 3: Find shapes graph (always from OntologyStore T-Box)
            shape_ref = _URIRef(shape_uri)
            shapes_ttl = None
            for uri, graph in store._graphs.items():
                if (shape_ref, None, None) in graph:
                    shapes_ttl = graph.serialize(format="turtle")
                    break

            # Step 4: Validate
            if shapes_ttl:
                result = validator.validate(instance_ttl, shapes_ttl=shapes_ttl)
            else:
                result = validator.validate(instance_ttl, shapes_uri=shape_uri)

            return result.to_dict()
        except Exception as e:
            return {"error": str(e)}

    # Direct triple manipulation endpoints (T-Box / ontology graphs)
    @app.post("/ontologies/{uri:path}/triples")
    async def add_triple(uri: str, request: Request) -> dict[str, Any]:
        """Add a single SPO triple to an ontology graph."""
        body = await request.json()
        full_uri = f"ontology://{uri}"
        ok = store.add_triple(
            full_uri,
            body["subject"],
            body["predicate"],
            body["object"],
            is_literal=body.get("is_literal", False),
        )
        if ok and body.get("save", True):
            store.save_ontology(full_uri)
        return {"status": "added" if ok else "not_found"}

    @app.post("/ontologies/{uri:path}/triples/remove")
    async def remove_triples(uri: str, request: Request) -> dict[str, Any]:
        """Remove triples matching the given pattern from an ontology graph."""
        body = await request.json()
        full_uri = f"ontology://{uri}"
        count = store.remove_triple(
            full_uri,
            subject=body.get("subject"),
            predicate=body.get("predicate"),
            obj=body.get("object"),
        )
        if count > 0:
            store.save_ontology(full_uri)
        return {"removed": count}

    # A-Box facts endpoint (exposes memory store for the dashboard)
    if kg_store is not None:
        from knowledge_graph.core.memory import AgentMemory
        agent_memory = AgentMemory(kg_store)
        app.state.kg_store = kg_store
        app.state.agent_memory = agent_memory

        @app.get("/facts")
        async def list_facts(
            context: str | None = None,
            subject: str | None = None,
            predicate: str | None = None,
            limit: int = 200,
        ) -> dict[str, Any]:
            """Query facts from the A-Box memory store."""
            try:
                facts = agent_memory.recall(
                    subject=subject,
                    predicate=predicate,
                    context=context,
                    limit=limit,
                )
                return {"facts": facts, "count": len(facts)}
            except Exception as e:
                return {"error": str(e)}

        @app.post("/facts")
        async def store_fact(request: Request) -> dict[str, Any]:
            """Store a fact in the A-Box memory store."""
            from knowledge_graph.core.memory import MemoryFact

            try:
                body = await request.json()
                fact = MemoryFact(
                    subject=body["subject"],
                    predicate=body["predicate"],
                    object=body["object"],
                    context=body.get("context"),
                    confidence=body.get("confidence", 1.0),
                )
                fact_id = agent_memory.store_fact(fact)
                return {"status": "stored", "fact_id": fact_id}
            except Exception as e:
                return {"error": str(e)}

        @app.delete("/facts/{fact_id}")
        async def delete_fact(fact_id: str) -> dict[str, Any]:
            """Remove a fact from the A-Box memory store."""
            try:
                success = agent_memory.forget(fact_id)
                return {"status": "forgotten" if success else "not_found", "fact_id": fact_id}
            except Exception as e:
                return {"error": str(e)}

        @app.get("/facts/stats")
        async def facts_stats() -> dict[str, Any]:
            """Get A-Box memory store statistics."""
            try:
                return {
                    "fact_count": agent_memory.count_facts(),
                    "contexts": agent_memory.get_all_contexts(),
                    "unique_subjects": agent_memory.get_subjects(),
                }
            except Exception as e:
                return {"error": str(e)}

        # -- A-Box triple endpoints (phase output triples in KG) -----------

        from knowledge_graph.core.store import GRAPH_PHASES

        @app.post("/abox/triples")
        async def abox_add_triple(request: Request) -> dict[str, Any]:
            """Add a triple to the A-Box (KnowledgeGraphStore).

            Accepts JSON body with:
                subject: Subject URI
                predicate: Predicate URI
                object: Object value (URI or literal)
                is_literal: Whether the object is a literal (default False)
                graph: Named graph URI (default: phases graph)
            """
            try:
                body = await request.json()
                graph = body.get("graph", GRAPH_PHASES)
                kg_store.add_triple(
                    body["subject"],
                    body["predicate"],
                    body["object"],
                    is_literal=body.get("is_literal", False),
                    graph=graph,
                )
                kg_store.flush()
                return {"status": "added"}
            except Exception as e:
                return {"error": str(e)}

        @app.post("/abox/triples/remove")
        async def abox_remove_triples(request: Request) -> dict[str, Any]:
            """Remove triples matching the pattern from the A-Box.

            Accepts JSON body with:
                subject: Optional subject URI pattern
                predicate: Optional predicate URI pattern
                object: Optional object pattern
                graph: Named graph URI (default: phases graph)
            """
            try:
                body = await request.json()
                graph = body.get("graph", GRAPH_PHASES)
                count = kg_store.remove_triple(
                    subject=body.get("subject"),
                    predicate=body.get("predicate"),
                    obj=body.get("object"),
                    graph=graph,
                )
                kg_store.flush()
                return {"removed": count}
            except Exception as e:
                return {"error": str(e)}

        # -- Ideas endpoints (SKOS+DC in default graph) --------------------

        from knowledge_graph.core.ideas import IdeasStore
        ideas_store = IdeasStore(kg_store)
        app.state.ideas_store = ideas_store

        @app.get("/ideas")
        async def list_ideas(
            lifecycle: str | None = None,
            author: str | None = None,
            tag: str | None = None,
            search: str | None = None,
            limit: int = 100,
            offset: int = 0,
        ) -> dict[str, Any]:
            """List ideas with optional filters."""
            try:
                if search:
                    ideas = ideas_store.search_ideas(search, limit=limit)
                else:
                    ideas = ideas_store.list_ideas(
                        lifecycle=lifecycle,
                        author=author,
                        tag=tag,
                        limit=limit,
                        offset=offset,
                    )
                return {"ideas": ideas, "count": len(ideas)}
            except Exception as e:
                return {"error": str(e)}

        @app.get("/ideas/tags")
        async def list_idea_tags() -> dict[str, Any]:
            """List all idea tags with counts."""
            try:
                tags = ideas_store.get_all_tags()
                return {"tags": tags, "count": len(tags)}
            except Exception as e:
                return {"error": str(e)}

        @app.get("/ideas/{idea_id}")
        async def get_idea(idea_id: str) -> dict[str, Any]:
            """Get full idea detail by ID."""
            try:
                idea = ideas_store.get_idea(idea_id)
                if idea is None:
                    return {"error": f"Idea not found: {idea_id}"}
                from dataclasses import asdict
                data = asdict(idea)
                # Convert datetime fields to ISO strings
                for key in ("created", "lifecycle_updated", "captured_at"):
                    if data.get(key) is not None:
                        data[key] = data[key].isoformat()
                # Drop embedding (large, not useful for display)
                data.pop("embedding", None)
                return data
            except Exception as e:
                return {"error": str(e)}

        # -- Knowledge Graph SPARQL endpoint -------------------------------

        @app.post("/kg/sparql")
        async def kg_sparql_query(query: str) -> dict[str, Any]:
            """Execute SPARQL query against the knowledge graph.

            Queries across all KG graphs:
            - Default graph: Ideas (SKOS:Concept)
            - Named graph memory: Agent facts
            - Named graph wikidata: Wikidata cache
            """
            try:
                results = kg_store.query(query)
                return {
                    "variables": results.variables,
                    "bindings": results.bindings,
                    "results": results.bindings,  # compat alias for tulla phase_facts
                    "count": len(results.bindings),
                }
            except Exception as e:
                return {"error": str(e)}

        @app.post("/kg/update")
        async def kg_sparql_update(request: Request) -> dict[str, Any]:
            """Execute SPARQL UPDATE against the knowledge graph."""
            try:
                body = await request.json()
                query = body.get("query", "")
                kg_store.update(query)
                return {"success": True, "query": query}
            except Exception as e:
                return {"error": str(e)}

        # -- Dashboard sub-application ------------------------------------
        # Mount BEFORE the MCP catch-all so /dashboard/* routes resolve
        # before the Starlette "/" mount swallows them.
        from ..dashboard import create_dashboard_app

        dashboard_app = create_dashboard_app(
            ontology_store=store,
            kg_store=kg_store,
            agent_memory=agent_memory,
            ideas_store=ideas_store,
        )
        # Pass auth state so login route can verify tokens and set cookies
        if settings.api_key:
            dashboard_app.state.token_verifier = verifier
            dashboard_app.state.session_cookie_value = _session_cookie
        app.mount("/dashboard", dashboard_app)
        logger.info("Dashboard sub-application mounted at /dashboard")

    # Create MCP server with optional A-Box support
    mcp = create_mcp_server(settings, store, validator, kg_store)

    # Mount MCP SSE app for multi-client access
    # This enables Claude Code and other MCP clients to connect via HTTP
    app.mount("/", mcp.sse_app())

    logger.info("Created FastAPI application with MCP SSE at /sse")
    return app
