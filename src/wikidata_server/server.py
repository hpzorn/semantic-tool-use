"""Wikidata MCP server (4 tools: lookup, query, search_cache, stats)."""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    from knowledge_graph import KnowledgeGraphStore

logger = logging.getLogger(__name__)


def create_wikidata_server(
    kg_store: "KnowledgeGraphStore",
    *,
    name: str = "wikidata-server",
    api_key: str | None = None,
    host: str = "localhost",
    port: int = 8200,
) -> FastMCP:
    """Create the standalone Wikidata MCP server.

    Args:
        kg_store: Knowledge graph store backing the shared Wikidata cache graph.
        name: MCP server name.
        api_key: Optional Bearer token; when set, enables auth.
        host/port: Used only to build issuer/resource URLs for auth settings.
    """
    from knowledge_graph.core.wikidata import WikidataCache

    auth_kwargs: dict[str, Any] = {}
    if api_key:
        from mcp.server.auth.settings import AuthSettings
        from ontology_server.auth import StaticTokenVerifier

        auth_kwargs["token_verifier"] = StaticTokenVerifier(api_key)
        auth_kwargs["auth"] = AuthSettings(
            issuer_url=f"http://{host}:{port}",
            resource_server_url=f"http://{host}:{port}",
            required_scopes=[],
        )
        logger.info("Bearer token authentication enabled (wikidata-server)")

    mcp = FastMCP(name, **auth_kwargs)
    wikidata_cache = WikidataCache(kg_store)

    @mcp.tool()
    def lookup(qid: str, force_refresh: bool = False) -> dict[str, Any]:
        """Look up a Wikidata entity by QID (e.g. "Q42")."""
        if not qid.startswith("Q"):
            qid = f"Q{qid}"
        entity = wikidata_cache.lookup(qid, force_refresh=force_refresh)
        if not entity:
            return {"error": f"Entity not found: {qid}"}
        return {
            "qid": entity.qid,
            "label": entity.label,
            "description": entity.description,
            "aliases": entity.aliases,
            "instance_of": entity.instance_of,
        }

    @mcp.tool()
    def query(sparql: str, cache_entities: bool = True, timeout: int = 30) -> dict[str, Any]:
        """Execute a SPARQL query against the Wikidata endpoint."""
        results = wikidata_cache.query(sparql, cache_entities=cache_entities, timeout=timeout)
        if results and "error" in results[0]:
            return {"error": results[0]["error"], "results": []}
        return {"count": len(results), "results": results, "cached": cache_entities}

    @mcp.tool()
    def search_cache(term: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search the local Wikidata cache by label (case-insensitive)."""
        return wikidata_cache.search(term, limit=limit)

    @mcp.tool()
    def stats() -> dict[str, Any]:
        """Get Wikidata cache statistics."""
        return wikidata_cache.get_stats()

    logger.info("Registered 4 Wikidata tools (lookup, query, search_cache, stats)")
    return mcp
