"""Combined FastAPI + MCP application.

This module provides HTTP endpoints alongside the MCP server.
Full REST API will be implemented in Phase 3.
"""

from typing import Any
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import Settings
from ..core.store import OntologyStore
from ..core.validation import SHACLValidator
from ..mcp.server import create_mcp_server

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings,
    store: OntologyStore,
    validator: SHACLValidator
) -> FastAPI:
    """Create combined FastAPI application.

    Args:
        settings: Server configuration
        store: Initialized ontology store
        validator: SHACL validator instance

    Returns:
        Configured FastAPI application
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

    # Mount MCP server for SSE transport (enables HTTP-based MCP)
    mcp = create_mcp_server(settings, store, validator)

    # Note: MCP SSE mounting requires mcp library support
    # This will be fully implemented in Phase 3
    # For now, MCP runs in stdio mode separately

    logger.info("Created FastAPI application with basic endpoints")
    return app
