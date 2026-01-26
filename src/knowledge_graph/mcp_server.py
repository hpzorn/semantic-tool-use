"""
MCP Server for Knowledge Graph Backend.

Exposes the unified knowledge graph via MCP tools:
- Ideas: CRUD operations, SPARQL queries
- Agent Memory: store/recall/forget facts
- Wikidata: entity lookup and caching
- Unified SPARQL: queries across all named graphs
"""

import logging
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from .core.store import KnowledgeGraphStore, NAMESPACES, GRAPH_MEMORY, GRAPH_WIKIDATA
from .core.ideas import IdeasStore, Idea
from .core.memory import AgentMemory, MemoryFact
from .core.wikidata import WikidataCache

logger = logging.getLogger(__name__)


def create_mcp_server(
    store: KnowledgeGraphStore | None = None,
    persist_path: str | Path | None = None,
    name: str = "knowledge-graph"
) -> FastMCP:
    """
    Create MCP server with knowledge graph tools.

    Args:
        store: Existing KnowledgeGraphStore (if None, creates new one)
        persist_path: Path for persistence (used if store is None)
        name: MCP server name

    Returns:
        Configured FastMCP server instance
    """
    # Initialize store if not provided
    if store is None:
        store = KnowledgeGraphStore(persist_path)

    # Initialize subsystems
    ideas_store = IdeasStore(store)
    agent_memory = AgentMemory(store)
    wikidata_cache = WikidataCache(store)

    mcp = FastMCP(name)

    # =========================================================================
    # IDEAS TOOLS
    # =========================================================================

    @mcp.tool()
    def query_ideas(
        sparql: str | None = None,
        lifecycle: str | None = None,
        author: str | None = None,
        tag: str | None = None,
        search: str | None = None,
        limit: int = 50
    ) -> list[dict[str, Any]]:
        """
        Query ideas from the knowledge graph.

        Supports multiple query modes:
        - SPARQL query: Provide a SPARQL query string
        - Filter query: Use lifecycle, author, or tag parameters
        - Text search: Use the search parameter

        Args:
            sparql: Optional SPARQL query (takes precedence if provided)
            lifecycle: Filter by lifecycle state (seed, backlog, researching, etc.)
            author: Filter by author name
            tag: Filter by tag
            search: Text search in title and description
            limit: Maximum results (default 50)

        Returns:
            List of idea dictionaries with id, title, lifecycle, author, etc.

        Examples:
            # Get all ideas in backlog
            query_ideas(lifecycle="backlog")

            # Search for ideas about "ontology"
            query_ideas(search="ontology")

            # Custom SPARQL query
            query_ideas(sparql="SELECT ?id ?title WHERE { ?id skos:prefLabel ?title }")
        """
        if sparql:
            # Execute custom SPARQL
            try:
                results = store.query(sparql)
                return results.bindings
            except Exception as e:
                return [{"error": str(e)}]

        if search:
            return ideas_store.search_ideas(search, limit=limit)

        return ideas_store.list_ideas(
            lifecycle=lifecycle,
            author=author,
            tag=tag,
            limit=limit
        )

    @mcp.tool()
    def get_idea(idea_id: str) -> dict[str, Any]:
        """
        Get a single idea by ID.

        Args:
            idea_id: The idea ID (e.g., "idea-1" or just "1")

        Returns:
            Idea details including title, description, tags, related ideas, etc.
        """
        # Normalize ID
        if not idea_id.startswith("idea-"):
            idea_id = f"idea-{idea_id}"

        idea = ideas_store.get_idea(idea_id)
        if not idea:
            return {"error": f"Idea not found: {idea_id}"}

        return {
            "id": idea.id,
            "title": idea.title,
            "description": idea.description,
            "author": idea.author,
            "agent": idea.agent,
            "created": idea.created.isoformat(),
            "lifecycle": idea.lifecycle,
            "tags": idea.tags,
            "related": idea.related,
            "wikidata_refs": idea.wikidata_refs,
            "parent": idea.parent,
            "children": idea.children,
        }

    @mcp.tool()
    def create_idea_rdf(
        title: str,
        description: str = "",
        author: str = "AI",
        agent: str | None = None,
        lifecycle: str = "seed",
        tags: list[str] | None = None,
        related: list[str] | None = None,
        wikidata_refs: list[str] | None = None,
        parent: str | None = None
    ) -> dict[str, Any]:
        """
        Create a new idea in the knowledge graph.

        Args:
            title: Idea title
            description: Idea description
            author: Author name (default "AI")
            agent: AI agent name (if created by an agent)
            lifecycle: Initial lifecycle state (default "seed")
            tags: List of tags
            related: List of related idea IDs
            wikidata_refs: List of Wikidata Q-numbers
            parent: Parent idea ID (for sub-ideas)

        Returns:
            Created idea details including assigned ID
        """
        # Generate next ID
        existing = ideas_store.list_ideas(limit=1000)
        max_num = 0
        for idea in existing:
            match = idea["id"].replace("idea-", "")
            if match.isdigit():
                max_num = max(max_num, int(match))
        new_id = f"idea-{max_num + 1}"

        idea = Idea(
            id=new_id,
            title=title,
            description=description,
            author=author,
            agent=agent,
            lifecycle=lifecycle,
            tags=tags or [],
            related=related or [],
            wikidata_refs=wikidata_refs or [],
            parent=parent,
        )

        try:
            uri = ideas_store.create_idea(idea)
            return {
                "status": "created",
                "id": new_id,
                "uri": uri,
                "title": title,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @mcp.tool()
    def update_idea_rdf(
        idea_id: str,
        title: str | None = None,
        description: str | None = None,
        lifecycle: str | None = None,
        tags: list[str] | None = None,
        related: list[str] | None = None,
        wikidata_refs: list[str] | None = None
    ) -> dict[str, Any]:
        """
        Update an existing idea in the knowledge graph.

        Args:
            idea_id: The idea ID to update
            title: New title (optional)
            description: New description (optional)
            lifecycle: New lifecycle state (optional)
            tags: New tags list (replaces existing)
            related: New related ideas list (replaces existing)
            wikidata_refs: New Wikidata refs list (replaces existing)

        Returns:
            Updated idea details
        """
        if not idea_id.startswith("idea-"):
            idea_id = f"idea-{idea_id}"

        idea = ideas_store.get_idea(idea_id)
        if not idea:
            return {"error": f"Idea not found: {idea_id}"}

        # Apply updates
        if title is not None:
            idea.title = title
        if description is not None:
            idea.description = description
        if lifecycle is not None:
            idea.lifecycle = lifecycle
        if tags is not None:
            idea.tags = tags
        if related is not None:
            idea.related = related
        if wikidata_refs is not None:
            idea.wikidata_refs = wikidata_refs

        try:
            ideas_store.update_idea(idea)
            return {
                "status": "updated",
                "id": idea_id,
                "title": idea.title,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @mcp.tool()
    def get_related_ideas(idea_id: str) -> list[dict[str, Any]]:
        """
        Get ideas related to a given idea.

        Args:
            idea_id: The idea ID

        Returns:
            List of related ideas
        """
        if not idea_id.startswith("idea-"):
            idea_id = f"idea-{idea_id}"

        return ideas_store.get_related_ideas(idea_id)

    @mcp.tool()
    def get_ideas_by_wikidata(qid: str) -> list[dict[str, Any]]:
        """
        Get ideas that reference a Wikidata entity.

        Args:
            qid: Wikidata QID (e.g., "Q42" or "42")

        Returns:
            List of ideas referencing this entity
        """
        if not qid.startswith("Q"):
            qid = f"Q{qid}"

        return ideas_store.get_ideas_by_wikidata(qid)

    @mcp.tool()
    def get_all_tags() -> list[dict[str, Any]]:
        """
        Get all tags used across ideas with usage counts.

        Returns:
            List of tags with count of ideas using each
        """
        return ideas_store.get_all_tags()

    # =========================================================================
    # AGENT MEMORY TOOLS
    # =========================================================================

    @mcp.tool()
    def store_fact(
        subject: str,
        predicate: str,
        object: str,
        context: str | None = None,
        confidence: float = 1.0
    ) -> dict[str, Any]:
        """
        Store a fact in agent memory.

        Facts are stored as reified statements with metadata for later retrieval.

        Args:
            subject: The subject of the fact (e.g., "user", "project-X")
            predicate: The relationship (e.g., "prefers", "works_on")
            object: The object/value (e.g., "dark mode", "idea-20")
            context: Optional context tag (e.g., "session-123", "ui-settings")
            confidence: Confidence score 0.0-1.0 (default 1.0)

        Returns:
            Stored fact details including fact_id

        Example:
            store_fact("user", "prefers", "dark mode", context="ui-settings")
        """
        fact = MemoryFact(
            subject=subject,
            predicate=predicate,
            object=object,
            context=context,
            confidence=confidence,
        )

        fact_id = agent_memory.store_fact(fact)
        return {
            "status": "stored",
            "fact_id": fact_id,
            "subject": subject,
            "predicate": predicate,
            "object": object,
        }

    @mcp.tool()
    def recall_facts(
        subject: str | None = None,
        predicate: str | None = None,
        context: str | None = None,
        min_confidence: float | None = None,
        limit: int = 100
    ) -> list[dict[str, Any]]:
        """
        Recall facts from agent memory.

        Args:
            subject: Filter by subject
            predicate: Filter by predicate
            context: Filter by context
            min_confidence: Minimum confidence threshold
            limit: Maximum results

        Returns:
            List of matching facts

        Example:
            recall_facts(subject="user")
            recall_facts(context="session-123")
        """
        return agent_memory.recall(
            subject=subject,
            predicate=predicate,
            context=context,
            min_confidence=min_confidence,
            limit=limit
        )

    @mcp.tool()
    def recall_recent_facts(hours: int = 24, limit: int = 100) -> list[dict[str, Any]]:
        """
        Recall facts from the last N hours.

        Args:
            hours: Number of hours to look back (default 24)
            limit: Maximum results

        Returns:
            List of recent facts
        """
        return agent_memory.recall_recent(hours=hours, limit=limit)

    @mcp.tool()
    def forget_fact(fact_id: str) -> dict[str, Any]:
        """
        Remove a fact from agent memory.

        Args:
            fact_id: The fact ID to forget

        Returns:
            Status indicating success or failure
        """
        success = agent_memory.forget(fact_id)
        return {
            "status": "forgotten" if success else "not_found",
            "fact_id": fact_id,
        }

    @mcp.tool()
    def forget_by_context(context: str) -> dict[str, Any]:
        """
        Remove all facts with a given context.

        Useful for cleaning up session-specific data.

        Args:
            context: The context to forget

        Returns:
            Status with count of forgotten facts
        """
        count = agent_memory.forget_by_context(context)
        return {
            "status": "forgotten",
            "context": context,
            "count": count,
        }

    @mcp.tool()
    def get_memory_stats() -> dict[str, Any]:
        """
        Get agent memory statistics.

        Returns:
            Statistics including fact count and all contexts
        """
        return {
            "fact_count": agent_memory.count_facts(),
            "contexts": agent_memory.get_all_contexts(),
            "subjects": agent_memory.get_subjects(),
        }

    # =========================================================================
    # WIKIDATA TOOLS
    # =========================================================================

    @mcp.tool()
    def lookup_wikidata(
        qid: str,
        force_refresh: bool = False
    ) -> dict[str, Any]:
        """
        Look up a Wikidata entity.

        Fetches entity data from Wikidata and caches it locally.
        Subsequent lookups use the cache unless force_refresh is True.

        Args:
            qid: Wikidata QID (e.g., "Q42" or just "42")
            force_refresh: If True, bypass cache and fetch fresh data

        Returns:
            Entity data including label, description, and instance_of types
        """
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
            "cached_at": entity.cached_at.isoformat(),
        }

    @mcp.tool()
    def search_wikidata_cache(term: str, limit: int = 10) -> list[dict[str, Any]]:
        """
        Search cached Wikidata entities by label.

        Only searches entities already in the local cache.

        Args:
            term: Search term
            limit: Maximum results

        Returns:
            List of matching cached entities
        """
        return wikidata_cache.search(term, limit=limit)

    @mcp.tool()
    def get_wikidata_stats() -> dict[str, Any]:
        """
        Get Wikidata cache statistics.

        Returns:
            Statistics including cached count, stale count, and TTL
        """
        return wikidata_cache.get_stats()

    # =========================================================================
    # UNIFIED SPARQL
    # =========================================================================

    @mcp.tool()
    def sparql_query(query: str) -> list[dict[str, Any]]:
        """
        Execute a SPARQL query across the entire knowledge graph.

        Can query across all named graphs including ideas, memory, and wikidata cache.

        Args:
            query: SPARQL query string (prefixes are auto-added if needed)

        Returns:
            Query results as list of bindings

        Available prefixes:
        - skos: SKOS vocabulary
        - dcterms: Dublin Core Terms
        - idea: Custom idea properties
        - ideas: Idea instances
        - memory: Agent memory
        - wd: Wikidata entities

        Available graphs:
        - Default graph: Ideas
        - <http://ideasralph.org/graphs/memory>: Agent memory
        - <http://ideasralph.org/graphs/wikidata>: Wikidata cache

        Example:
            # Find ideas related to a Wikidata entity
            sparql_query('''
                SELECT ?idea ?title WHERE {
                    ?idea idea:wikidataRef wd:Q324254 ;
                          skos:prefLabel ?title .
                }
            ''')
        """
        try:
            results = store.query(query)
            return results.bindings
        except Exception as e:
            return [{"error": str(e)}]

    # =========================================================================
    # GRAPH STATISTICS
    # =========================================================================

    @mcp.tool()
    def get_graph_stats() -> dict[str, Any]:
        """
        Get overall knowledge graph statistics.

        Returns:
            Statistics for all graphs including triple counts
        """
        stats = store.get_stats()
        stats["idea_count"] = ideas_store.count_ideas()
        stats["memory_fact_count"] = agent_memory.count_facts()
        stats["wikidata_cached_count"] = wikidata_cache.count_cached()
        return stats

    logger.info(f"Created MCP server '{name}' with knowledge graph tools")
    return mcp


# =========================================================================
# MAIN ENTRY POINT
# =========================================================================

def main():
    """Run the MCP server."""
    import argparse

    parser = argparse.ArgumentParser(description="Knowledge Graph MCP Server")
    parser.add_argument(
        "--persist",
        type=str,
        default=None,
        help="Path for persistent storage (default: in-memory)"
    )
    parser.add_argument(
        "--ideas-dir",
        type=str,
        default=None,
        help="Directory to migrate ideas from on startup"
    )
    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Create store
    store = KnowledgeGraphStore(args.persist)

    # Optionally migrate ideas
    if args.ideas_dir:
        from .migration import migrate_ideas
        ideas_dir = Path(args.ideas_dir)
        if ideas_dir.exists():
            logger.info(f"Migrating ideas from {ideas_dir}")
            stats = migrate_ideas(ideas_dir, store)
            logger.info(f"Migration complete: {stats}")

    # Create and run server
    mcp = create_mcp_server(store)
    mcp.run()


if __name__ == "__main__":
    main()
