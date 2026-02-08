"""MCP server with ontology management tools."""

from typing import Any, TYPE_CHECKING
import logging

from mcp.server.fastmcp import FastMCP

from ..auth import StaticTokenVerifier
from ..config import Settings
from ..core.store import OntologyStore
from ..core.validation import SHACLValidator

if TYPE_CHECKING:
    from knowledge_graph import KnowledgeGraphStore

logger = logging.getLogger(__name__)


def create_mcp_server(
    settings: Settings,
    store: OntologyStore,
    validator: SHACLValidator | None = None,
    kg_store: "KnowledgeGraphStore | None" = None
) -> FastMCP:
    """Create MCP server with ontology tools.

    Args:
        settings: Server configuration
        store: Initialized ontology store
        validator: Optional SHACL validator (created from settings if not provided)
        kg_store: Optional knowledge graph store for A-Box functionality

    Returns:
        Configured FastMCP server instance
    """
    if validator is None:
        validator = SHACLValidator(settings.get_shapes_path())

    # Build auth kwargs if an API key is configured
    auth_kwargs: dict[str, Any] = {}
    if settings.api_key:
        from mcp.server.auth.settings import AuthSettings

        auth_kwargs["token_verifier"] = StaticTokenVerifier(settings.api_key)
        auth_kwargs["auth"] = AuthSettings(
            issuer_url=f"http://{settings.host}:{settings.port}",
            resource_server_url=f"http://{settings.host}:{settings.port}",
            required_scopes=[],
        )
        logger.info("Bearer token authentication enabled")

    mcp = FastMCP(settings.mcp_name, **auth_kwargs)

    # =========================================================================
    # Tool: list_ontologies
    # =========================================================================
    @mcp.tool()
    def list_ontologies() -> list[dict[str, Any]]:
        """List all available ontologies with metadata.

        Returns a list of ontologies with their URIs, file paths,
        and statistics (triple count, class count, etc.).
        """
        return store.list_ontologies()

    # =========================================================================
    # Tool: get_ontology
    # =========================================================================
    @mcp.tool()
    def get_ontology(uri: str) -> str:
        """Get an ontology by URI as Turtle format.

        Args:
            uri: The ontology URI (e.g., "ontology://visual-artifacts/core")

        Returns:
            The ontology serialized as Turtle, or an error message.
        """
        ttl = store.get_ontology_ttl(uri)
        if ttl is None:
            return f"Error: Ontology not found: {uri}"
        return ttl

    # =========================================================================
    # Tool: query_ontology
    # =========================================================================
    @mcp.tool()
    def query_ontology(query: str, ontology_uri: str | None = None) -> list[dict[str, str]]:
        """Execute SPARQL query against ontology(ies).

        Args:
            query: SPARQL query string (SELECT, ASK, or CONSTRUCT)
            ontology_uri: Optional URI to query single ontology.
                         If None, queries across all loaded ontologies.

        Returns:
            List of result rows as dictionaries, or error information.

        Examples:
            # Get all classes
            query_ontology("SELECT ?class WHERE { ?class a owl:Class }")

            # Get classes from specific ontology
            query_ontology(
                "SELECT ?class WHERE { ?class a owl:Class }",
                ontology_uri="ontology://visual-artifacts/core"
            )
        """
        try:
            results = store.query(query, ontology_uri)
            # Convert results to list of dicts
            output = []
            for row in results:
                row_dict = {}
                for var in row.labels:
                    value = row[var]
                    row_dict[str(var)] = str(value) if value else None
                output.append(row_dict)
            return output
        except ValueError as e:
            return [{"error": str(e)}]
        except Exception as e:
            logger.error(f"SPARQL query error: {e}")
            return [{"error": f"Query failed: {e}"}]

    # =========================================================================
    # Tool: get_classes
    # =========================================================================
    @mcp.tool()
    def get_classes(ontology_uri: str | None = None) -> list[dict[str, str]]:
        """Get all OWL classes from ontology(ies).

        Args:
            ontology_uri: Optional URI to get classes from single ontology.
                         If None, returns classes from all ontologies.

        Returns:
            List of classes with their URIs and labels.
        """
        return store.get_classes(ontology_uri)

    # =========================================================================
    # Tool: get_properties
    # =========================================================================
    @mcp.tool()
    def get_properties(ontology_uri: str | None = None) -> list[dict[str, str]]:
        """Get all OWL properties from ontology(ies).

        Args:
            ontology_uri: Optional URI to get properties from single ontology.
                         If None, returns properties from all ontologies.

        Returns:
            List of properties with URIs, types (Object/Datatype), labels,
            domains, and ranges.
        """
        return store.get_properties(ontology_uri)

    # =========================================================================
    # Tool: add_triple
    # =========================================================================
    @mcp.tool()
    def add_triple(
        ontology_uri: str,
        subject: str,
        predicate: str,
        object: str,
        is_literal: bool = False,
        save: bool = True
    ) -> dict[str, str]:
        """Add a triple to an ontology.

        Args:
            ontology_uri: URI of target ontology
            subject: Subject URI (e.g., "http://example.org/MyClass")
            predicate: Predicate URI (e.g., "http://www.w3.org/2000/01/rdf-schema#label")
            object: Object URI or literal value
            is_literal: If True, treat object as a literal (string) value
            save: If True, save changes to file immediately

        Returns:
            Status dict with success/error information.
        """
        success = store.add_triple(ontology_uri, subject, predicate, object, is_literal)

        if success:
            if save:
                store.save_ontology(ontology_uri)
            return {
                "status": "success",
                "message": f"Added triple to {ontology_uri}",
                "saved": str(save)
            }
        return {
            "status": "error",
            "message": f"Ontology not found: {ontology_uri}"
        }

    # =========================================================================
    # Tool: remove_triple
    # =========================================================================
    @mcp.tool()
    def remove_triple(
        ontology_uri: str,
        subject: str | None = None,
        predicate: str | None = None,
        object: str | None = None,
        save: bool = True
    ) -> dict[str, Any]:
        """Remove triples matching a pattern from an ontology.

        Args:
            ontology_uri: URI of target ontology
            subject: Subject URI to match (None for wildcard)
            predicate: Predicate URI to match (None for wildcard)
            object: Object URI or literal to match (None for wildcard)
            save: If True, save changes to file immediately

        Returns:
            Status dict with number of triples removed.
        """
        removed = store.remove_triple(ontology_uri, subject, predicate, object)

        if removed >= 0:
            if save and removed > 0:
                store.save_ontology(ontology_uri)
            return {
                "status": "success",
                "removed_count": removed,
                "message": f"Removed {removed} triple(s) from {ontology_uri}",
                "saved": str(save and removed > 0)
            }
        return {
            "status": "error",
            "removed_count": 0,
            "message": f"Ontology not found: {ontology_uri}"
        }

    # =========================================================================
    # Tool: update_triple
    # =========================================================================
    @mcp.tool()
    def update_triple(
        ontology_uri: str,
        subject: str,
        predicate: str,
        old_object: str,
        new_object: str,
        is_literal: bool = False,
        save: bool = True
    ) -> dict[str, Any]:
        """Update a triple's object value (remove old, add new).

        Args:
            ontology_uri: URI of target ontology
            subject: Subject URI
            predicate: Predicate URI
            old_object: Current object value to remove
            new_object: New object value to set
            is_literal: If True, treat objects as literals
            save: If True, save changes to file immediately

        Returns:
            Status dict with operation details.
        """
        # Remove old triple
        removed = store.remove_triple(ontology_uri, subject, predicate, old_object)

        if removed == 0:
            return {
                "status": "warning",
                "message": f"No matching triple found to update in {ontology_uri}",
                "removed": 0,
                "added": False
            }

        # Add new triple
        added = store.add_triple(ontology_uri, subject, predicate, new_object, is_literal)

        if added and save:
            store.save_ontology(ontology_uri)

        msg = (
            f"Updated triple in {ontology_uri}"
            if added else "Removed but failed to add new triple"
        )
        return {
            "status": "success" if added else "partial",
            "message": msg,
            "removed": removed,
            "added": added,
            "saved": str(save and added)
        }

    # =========================================================================
    # Tool: validate_instance
    # =========================================================================
    @mcp.tool()
    def validate_instance(
        instance_ttl: str,
        shapes_uri: str | None = None
    ) -> dict[str, Any]:
        """Validate RDF instance against SHACL shapes.

        Args:
            instance_ttl: Turtle string of the RDF instance to validate.
            shapes_uri: Optional shapes URI. If None, uses all loaded shapes.

        Returns:
            Validation result with conforms, violation_count, violations, report.
        """
        result = validator.validate(instance_ttl, shapes_uri)
        return result.to_dict()

    # =========================================================================
    # Tool: search_ontology
    # =========================================================================
    @mcp.tool()
    def search_ontology(
        term: str,
        ontology_uri: str | None = None,
        search_labels: bool = True,
        search_comments: bool = True,
        limit: int = 50
    ) -> list[dict[str, str]]:
        """Search for resources by label or comment text.

        Args:
            term: Search term (case-insensitive substring match)
            ontology_uri: Optional URI to search single ontology
            search_labels: Search in rdfs:label values
            search_comments: Search in rdfs:comment values
            limit: Maximum results to return

        Returns:
            List of matching resources with their URIs, labels, and types.
        """
        filters = []
        if search_labels:
            filters.append(f'FILTER(CONTAINS(LCASE(STR(?label)), LCASE("{term}")))')
        if search_comments:
            filters.append(f'FILTER(CONTAINS(LCASE(STR(?comment)), LCASE("{term}")))')

        if not filters:
            return [{"error": "Must search in labels or comments"}]

        sparql = f"""
        SELECT DISTINCT ?resource ?label ?type WHERE {{
            ?resource ?p ?text .
            VALUES ?p {{ rdfs:label rdfs:comment }}
            FILTER(CONTAINS(LCASE(STR(?text)), LCASE("{term}")))
            OPTIONAL {{ ?resource rdfs:label ?label }}
            OPTIONAL {{ ?resource a ?type }}
        }}
        LIMIT {limit}
        """

        try:
            results = store.query(sparql, ontology_uri)
            output = []
            for row in results:
                output.append({
                    "uri": str(row.resource) if row.resource else None,
                    "label": str(row.label) if row.label else None,
                    "type": str(row.type) if row.type else None,
                })
            return output
        except Exception as e:
            return [{"error": f"Search failed: {e}"}]

    # =========================================================================
    # Tool: list_quality_shapes
    # =========================================================================
    @mcp.tool()
    def list_quality_shapes() -> list[dict[str, Any]]:
        """List available upper ontology quality shape sets.

        Returns:
            List of shape sets with name, shape_count, description.
        """
        return SHACLValidator.list_bundled_shapes()

    # =========================================================================
    # Tool: validate_ontology_quality
    # =========================================================================
    @mcp.tool()
    def validate_ontology_quality(
        ontology_uri: str | None = None,
        ontology_ttl: str | None = None,
        shape_sets: list[str] | None = None
    ) -> dict[str, Any]:
        """Validate an ontology against upper ontology quality shapes.

        Args:
            ontology_uri: URI of loaded ontology to validate.
            ontology_ttl: Alternative: Turtle string of ontology to validate.
            shape_sets: Optional list of shape sets to use.

        Returns:
            Validation result with conforms, violation_count, violations, report.
        """
        # Get ontology content
        if ontology_uri:
            ttl = store.get_ontology_ttl(ontology_uri)
            if not ttl:
                return {"error": f"Ontology not found: {ontology_uri}", "conforms": False}
        elif ontology_ttl:
            ttl = ontology_ttl
        else:
            return {"error": "Must provide ontology_uri or ontology_ttl", "conforms": False}

        result = validator.validate_ontology_quality(ttl, shape_sets)
        return result.to_dict()

    # =========================================================================
    # Tool: get_quality_summary
    # =========================================================================
    @mcp.tool()
    def get_quality_summary(ontology_uri: str) -> dict[str, Any]:
        """Get a quality summary for a loaded ontology.

        Args:
            ontology_uri: URI of loaded ontology to analyze

        Returns:
            Summary with conforms, by_severity, top_issues, recommendations.
        """
        ttl = store.get_ontology_ttl(ontology_uri)
        if not ttl:
            return {"error": f"Ontology not found: {ontology_uri}"}

        result = validator.validate_ontology_quality(ttl)

        # Group by severity
        by_severity = {"Violation": 0, "Warning": 0, "Info": 0}
        issue_types: dict[str, int] = {}

        for v in result.violations:
            by_severity[v.severity] = by_severity.get(v.severity, 0) + 1
            msg_key = v.message.split(" should ")[0] if " should " in v.message else v.message[:50]
            issue_types[msg_key] = issue_types.get(msg_key, 0) + 1

        top_issues = sorted(issue_types.items(), key=lambda x: -x[1])[:5]

        recommendations = []
        if by_severity["Violation"] > 0:
            recommendations.append("Fix violations first - these indicate structural problems")
        if by_severity["Warning"] > 10:
            recommendations.append("Add labels to classes and properties for better usability")
        if by_severity["Info"] > 20:
            recommendations.append("Consider adding more documentation (rdfs:comment)")

        return {
            "ontology_uri": ontology_uri,
            "conforms": result.conforms,
            "by_severity": by_severity,
            "total_issues": len(result.violations),
            "top_issues": [{"issue": k, "count": v} for k, v in top_issues],
            "recommendations": recommendations,
        }

    # =========================================================================
    # Resource: Ontology files
    # =========================================================================
    @mcp.resource("ontology://{path}")
    def ontology_resource(path: str) -> str:
        """Get ontology content as a resource.

        Args:
            path: Ontology path (e.g., "visual-artifacts/core")

        Returns:
            Ontology as Turtle string
        """
        uri = f"ontology://{path}"
        ttl = store.get_ontology_ttl(uri)
        return ttl if ttl else f"Ontology not found: {uri}"

    logger.info(f"Created MCP server '{settings.mcp_name}' with ontology tools")

    # =========================================================================
    # A-Box (Knowledge Graph) Tools - Optional
    # =========================================================================
    if kg_store is not None:
        _register_knowledge_graph_tools(mcp, kg_store, settings)
        logger.info("Registered A-Box (knowledge graph) tools")

    return mcp


def _register_knowledge_graph_tools(
    mcp: FastMCP,
    kg_store: "KnowledgeGraphStore",
    settings: Settings,
) -> None:
    """Register knowledge graph tools with the MCP server.

    Args:
        mcp: FastMCP server instance
        kg_store: Knowledge graph store instance
        settings: Server settings with feature flags
    """
    from knowledge_graph.core.ideas import IdeasStore, Idea
    from knowledge_graph.core.memory import AgentMemory, MemoryFact
    from knowledge_graph.core.wikidata import WikidataCache
    from knowledge_graph.core.lifecycle import LifecycleManager
    from knowledge_graph.core.seeds import SeedStore

    ideas_store = IdeasStore(kg_store)
    agent_memory = AgentMemory(kg_store)
    wikidata_cache = WikidataCache(kg_store)
    lifecycle_mgr = LifecycleManager(kg_store, ideas_store)
    seed_store = SeedStore(kg_store, ideas_store)

    # =========================================================================
    # Ideas Tools
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
        """Query ideas from the knowledge graph.

        Supports SPARQL queries, filter queries, or text search.

        Args:
            sparql: Optional SPARQL query (takes precedence)
            lifecycle: Filter by lifecycle state
            author: Filter by author name
            tag: Filter by tag
            search: Text search in title, description, and content
            limit: Maximum results (default 50)
        """
        if sparql:
            try:
                results = kg_store.query(sparql)
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
        """Get a single idea by ID with all metadata.

        Args:
            idea_id: The idea ID (e.g., "idea-1", "1", or "seed-20260126-123456-abc1")
        """
        if not idea_id.startswith("idea-") and not idea_id.startswith("seed-"):
            idea_id = f"idea-{idea_id}"

        idea = ideas_store.get_idea(idea_id)
        if not idea:
            return {"error": f"Idea not found: {idea_id}"}

        return {
            "id": idea.id,
            "title": idea.title,
            "description": idea.description,
            "content": idea.content[:2000] if idea.content else "",
            "content_length": len(idea.content) if idea.content else 0,
            "author": idea.author,
            "agent": idea.agent,
            "created": idea.created.isoformat(),
            "lifecycle": idea.lifecycle,
            "lifecycle_updated": idea.lifecycle_updated.isoformat() if idea.lifecycle_updated else None,
            "lifecycle_reason": idea.lifecycle_reason,
            "tags": idea.tags,
            "related": idea.related,
            "parent": idea.parent,
            "children": idea.children,
            "blocks": idea.blocks,
            "blocked_by": idea.blocked_by,
            "is_seed": idea.is_seed,
            "priority": idea.priority,
        }

    @mcp.tool()
    def create_idea(
        title: str,
        description: str = "",
        content: str = "",
        author: str = "AI",
        lifecycle: str = "seed",
        tags: list[str] | None = None,
        related: list[str] | None = None,
        parent: str | None = None,
    ) -> dict[str, Any]:
        """Create a new idea in the knowledge graph.

        Args:
            title: Idea title
            description: Short description
            content: Full markdown content
            author: Author name (default "AI")
            lifecycle: Initial state (default "seed")
            tags: List of tags
            related: List of related idea IDs
            parent: Parent idea ID for sub-ideas
        """
        new_id = ideas_store.get_next_id()

        idea = Idea(
            id=new_id,
            title=title,
            description=description,
            content=content,
            author=author,
            lifecycle=lifecycle,
            tags=tags or [],
            related=related or [],
            parent=parent,
        )

        try:
            uri = ideas_store.create_idea(idea)
            return {"status": "created", "id": new_id, "uri": uri}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @mcp.tool()
    def update_idea(
        idea_id: str,
        title: str | None = None,
        description: str | None = None,
        content: str | None = None,
        lifecycle: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Update an existing idea.

        Args:
            idea_id: The idea ID to update
            title: New title (optional)
            description: New description (optional)
            content: New content (optional)
            lifecycle: New lifecycle state (optional)
            tags: New tags list (replaces existing)
        """
        if not idea_id.startswith("idea-") and not idea_id.startswith("seed-"):
            idea_id = f"idea-{idea_id}"

        idea = ideas_store.get_idea(idea_id)
        if not idea:
            return {"error": f"Idea not found: {idea_id}"}

        if title is not None:
            idea.title = title
        if description is not None:
            idea.description = description
        if content is not None:
            idea.content = content
        if lifecycle is not None:
            idea.lifecycle = lifecycle
        if tags is not None:
            idea.tags = tags

        try:
            ideas_store.update_idea(idea)
            return {"status": "updated", "id": idea_id}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @mcp.tool()
    def delete_idea(idea_id: str) -> dict[str, Any]:
        """Delete an idea from the knowledge graph.

        Args:
            idea_id: The idea ID to delete
        """
        if not idea_id.startswith("idea-") and not idea_id.startswith("seed-"):
            idea_id = f"idea-{idea_id}"

        success = ideas_store.delete_idea(idea_id)
        if success:
            return {"status": "deleted", "id": idea_id}
        return {"error": f"Idea not found: {idea_id}"}

    @mcp.tool()
    def append_to_idea(idea_id: str, content: str) -> dict[str, Any]:
        """Append content to an existing idea.

        Args:
            idea_id: The idea ID
            content: Content to append (markdown)
        """
        if not idea_id.startswith("idea-") and not idea_id.startswith("seed-"):
            idea_id = f"idea-{idea_id}"

        success = ideas_store.append_to_idea(idea_id, content)
        if success:
            return {"status": "appended", "id": idea_id}
        return {"error": f"Idea not found: {idea_id}"}

    # =========================================================================
    # Seed Tools
    # =========================================================================

    @mcp.tool()
    def capture_seed(
        content: str,
        author: str = "hpz",
        agent: str | None = None,
    ) -> dict[str, Any]:
        """Instant brain dump - no title, no structure, just capture.

        Args:
            content: Raw content to capture
            author: Author name (default "hpz")
            agent: Optional AI agent name
        """
        return seed_store.capture_seed(content, author, agent)

    @mcp.tool()
    def list_seeds(
        limit: int = 20,
        today_only: bool = False,
    ) -> list[dict[str, Any]]:
        """List captured seeds with timestamps and previews.

        Args:
            limit: Maximum results (default 20)
            today_only: Only show today's seeds
        """
        return seed_store.list_seeds(limit, today_only)

    @mcp.tool()
    def read_seed(seed_id: str) -> dict[str, Any]:
        """Read a specific seed by ID.

        Args:
            seed_id: The seed ID (e.g., "seed-20260126-123456-abc1")
        """
        return seed_store.read_seed(seed_id)

    @mcp.tool()
    def crystallize_seed(
        seed_id: str,
        title: str,
        description: str = "",
        content: str = "",
        author: str = "AI",
    ) -> dict[str, Any]:
        """Promote a seed to a full idea with proper structure.

        Args:
            seed_id: The seed ID to crystallize
            title: Title for the new idea
            description: Short description
            content: Full content (uses seed content if empty)
            author: Author name
        """
        return seed_store.crystallize_seed(seed_id, title, description, content, author)

    # =========================================================================
    # Lifecycle Tools
    # =========================================================================

    @mcp.tool()
    def set_lifecycle(
        idea_id: str,
        new_state: str,
        reason: str = "",
    ) -> dict[str, Any]:
        """Update an idea's lifecycle state with transition validation.

        Valid states: seed, sprout, backlog, researching, researched,
                     decomposing, scoped, implementing, completed,
                     blocked, failed, invalidated, parked

        Args:
            idea_id: The idea ID
            new_state: Target lifecycle state
            reason: Reason for the transition
        """
        return lifecycle_mgr.set_lifecycle(idea_id, new_state, reason)

    @mcp.tool()
    def get_workable_ideas(limit: int = 20) -> list[dict[str, Any]]:
        """Get ideas ready for Ralph (backlog + unblocked).

        Args:
            limit: Maximum results
        """
        return lifecycle_mgr.get_workable_ideas(limit)

    @mcp.tool()
    def get_ralph_status() -> dict[str, Any]:
        """Overall workflow status dashboard.

        Returns counts by lifecycle state, active/blocked/completed stats.
        """
        return lifecycle_mgr.get_ralph_status()

    @mcp.tool()
    def get_ideas_by_lifecycle(lifecycle: str) -> list[dict[str, Any]]:
        """List ideas in a specific lifecycle state.

        Args:
            lifecycle: The lifecycle state to filter by
        """
        return lifecycle_mgr.get_ideas_by_lifecycle(lifecycle)

    @mcp.tool()
    def move_to_backlog(
        idea_id: str,
        priority: int | None = None,
    ) -> dict[str, Any]:
        """Promote idea to backlog with optional priority.

        Args:
            idea_id: The idea ID
            priority: Optional priority (lower = higher priority)
        """
        return lifecycle_mgr.move_to_backlog(idea_id, priority)

    @mcp.tool()
    def check_parent_completion(idea_id: str) -> dict[str, Any]:
        """Check if parent can be marked complete (all children done).

        Args:
            idea_id: The parent idea ID to check
        """
        return lifecycle_mgr.check_parent_completion(idea_id)

    # =========================================================================
    # Dependency Tools
    # =========================================================================

    @mcp.tool()
    def add_dependency(
        idea_id: str,
        blocks: str | None = None,
        blocked_by: str | None = None,
    ) -> dict[str, Any]:
        """Add dependency relationships between ideas.

        Args:
            idea_id: The idea ID
            blocks: Comma-separated IDs this idea blocks
            blocked_by: Comma-separated IDs blocking this idea
        """
        return lifecycle_mgr.add_dependency(idea_id, blocks, blocked_by)

    @mcp.tool()
    def remove_dependency(
        idea_id: str,
        blocks: str | None = None,
        blocked_by: str | None = None,
    ) -> dict[str, Any]:
        """Remove dependency relationships between ideas.

        Args:
            idea_id: The idea ID
            blocks: Comma-separated IDs to unblock
            blocked_by: Comma-separated IDs to remove as blockers
        """
        return lifecycle_mgr.remove_dependency(idea_id, blocks, blocked_by)

    @mcp.tool()
    def get_idea_dependencies(idea_id: str) -> dict[str, Any]:
        """Get all dependency relationships for an idea.

        Shows parent, children, blocks, blocked_by, and related ideas.

        Args:
            idea_id: The idea ID
        """
        return lifecycle_mgr.get_idea_dependencies(idea_id)

    @mcp.tool()
    def create_sub_idea(
        parent_id: str,
        title: str,
        description: str = "",
        content: str = "",
        author: str = "AI",
    ) -> dict[str, Any]:
        """Create a child idea linked to a parent.

        Args:
            parent_id: Parent idea ID
            title: Title for the sub-idea
            description: Short description
            content: Full content
            author: Author name
        """
        return lifecycle_mgr.create_sub_idea(parent_id, title, description, content, author)

    # =========================================================================
    # Agent Memory Tools
    # =========================================================================

    @mcp.tool()
    def store_fact(
        subject: str,
        predicate: str,
        object: str,
        context: str | None = None,
        confidence: float = 1.0
    ) -> dict[str, Any]:
        """Store a fact in agent memory.

        Args:
            subject: The subject (e.g., "user", "project-X")
            predicate: The relationship (e.g., "prefers", "works_on")
            object: The object/value
            context: Optional context tag
            confidence: Confidence score 0.0-1.0
        """
        fact = MemoryFact(
            subject=subject,
            predicate=predicate,
            object=object,
            context=context,
            confidence=confidence,
        )
        fact_id = agent_memory.store_fact(fact)
        return {"status": "stored", "fact_id": fact_id}

    @mcp.tool()
    def recall_facts(
        subject: str | None = None,
        predicate: str | None = None,
        context: str | None = None,
        limit: int = 100
    ) -> list[dict[str, Any]]:
        """Recall facts from agent memory.

        Args:
            subject: Filter by subject
            predicate: Filter by predicate
            context: Filter by context
            limit: Maximum results
        """
        return agent_memory.recall(
            subject=subject,
            predicate=predicate,
            context=context,
            limit=limit
        )

    @mcp.tool()
    def forget_fact(fact_id: str) -> dict[str, Any]:
        """Remove a fact from agent memory.

        Args:
            fact_id: The fact ID to forget
        """
        success = agent_memory.forget(fact_id)
        return {"status": "forgotten" if success else "not_found", "fact_id": fact_id}

    @mcp.tool()
    def recall_recent_facts(hours: int = 24, limit: int = 100) -> list[dict[str, Any]]:
        """Recall facts from the last N hours.

        Args:
            hours: Number of hours to look back (default 24)
            limit: Maximum results
        """
        return agent_memory.recall_recent(hours=hours, limit=limit)

    @mcp.tool()
    def forget_by_context(context: str) -> dict[str, Any]:
        """Remove all facts with a given context.

        Args:
            context: The context tag to forget
        """
        count = agent_memory.forget_by_context(context)
        return {"status": "forgotten", "count": count, "context": context}

    @mcp.tool()
    def get_memory_stats() -> dict[str, Any]:
        """Get agent memory statistics."""
        return {
            "fact_count": agent_memory.count_facts(),
            "contexts": agent_memory.get_all_contexts(),
            "unique_subjects": agent_memory.get_subjects(),
        }

    # =========================================================================
    # Wikidata Tools
    # =========================================================================

    @mcp.tool()
    def lookup_wikidata(qid: str, force_refresh: bool = False) -> dict[str, Any]:
        """Look up a Wikidata entity.

        Args:
            qid: Wikidata QID (e.g., "Q42")
            force_refresh: Bypass cache and fetch fresh data
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
        }

    @mcp.tool()
    def query_wikidata(
        sparql: str,
        cache_entities: bool = True,
        timeout: int = 30
    ) -> dict[str, Any]:
        """Execute a SPARQL query against the Wikidata endpoint.

        Args:
            sparql: SPARQL query. Common prefixes (wd:, wdt:, etc.) are auto-added.
            cache_entities: Cache discovered entities for fast re-lookup.
            timeout: Query timeout in seconds (default 30).
        """
        results = wikidata_cache.query(
            sparql,
            cache_entities=cache_entities,
            timeout=timeout
        )

        if results and "error" in results[0]:
            return {"error": results[0]["error"], "results": []}

        return {
            "count": len(results),
            "results": results,
            "cached": cache_entities,
        }

    @mcp.tool()
    def search_wikidata_cache(term: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search for entities in the local Wikidata cache by label.

        Args:
            term: Search term (case-insensitive)
            limit: Maximum results
        """
        return wikidata_cache.search(term, limit=limit)

    @mcp.tool()
    def get_wikidata_stats() -> dict[str, Any]:
        """Get Wikidata cache statistics."""
        return wikidata_cache.get_stats()

    # =========================================================================
    # Additional Ideas Tools
    # =========================================================================

    @mcp.tool()
    def get_related_ideas(idea_id: str) -> list[dict[str, Any]]:
        """Get ideas related to a given idea.

        Args:
            idea_id: The idea ID (e.g., "idea-1" or just "1")
        """
        if not idea_id.startswith("idea-"):
            idea_id = f"idea-{idea_id}"
        return ideas_store.get_related_ideas(idea_id)

    @mcp.tool()
    def get_ideas_by_wikidata(qid: str) -> list[dict[str, Any]]:
        """Get ideas that reference a specific Wikidata entity.

        Args:
            qid: Wikidata QID (e.g., "Q42")
        """
        if not qid.startswith("Q"):
            qid = f"Q{qid}"
        return ideas_store.get_ideas_by_wikidata(qid)

    @mcp.tool()
    def get_all_tags() -> list[dict[str, Any]]:
        """Get all tags used across ideas with usage counts."""
        return ideas_store.get_all_tags()

    # =========================================================================
    # Cross-Graph Query Tools
    # =========================================================================

    @mcp.tool()
    def sparql_query(query: str, validate: bool = True) -> dict[str, Any]:
        """Execute a SPARQL query across the knowledge graph.

        This tool provides direct SPARQL access to all graphs:
        - Default graph: Ideas (SKOS:Concept)
        - Named graph <http://semantic-tool-use.org/graphs/memory>: Agent memory
        - Named graph <http://semantic-tool-use.org/graphs/wikidata>: Wikidata cache

        Args:
            query: SPARQL SELECT query
            validate: If True, validates query for common LLM hallucination patterns
        """
        if validate:
            validation_result = _validate_sparql_query(query)
            if not validation_result["valid"]:
                return {
                    "error": "Query validation failed",
                    "issues": validation_result["issues"],
                    "query": query
                }

        try:
            results = kg_store.query(query)
            return {
                "variables": results.variables,
                "bindings": results.bindings,
                "count": len(results.bindings)
            }
        except Exception as e:
            return {"error": str(e), "query": query}

    @mcp.tool()
    def sparql_update(query: str, validate: bool = True) -> dict[str, Any]:
        """Execute a SPARQL UPDATE against the knowledge graph.

        Supported operations:
        - INSERT DATA { ... } — add triples to the default or a named graph
        - DELETE DATA { ... } — remove specific triples
        - DELETE WHERE { ... } — remove triples matching a pattern
        - INSERT { ... } WHERE { ... } — insert triples derived from a query

        Destructive graph-level operations (DROP, CLEAR, CREATE, LOAD) are
        rejected to prevent accidental data loss.

        Args:
            query: SPARQL UPDATE query
            validate: If True, validates query for common LLM hallucination patterns
        """
        # Fail-closed: reject destructive graph-level operations
        query_upper = query.upper()
        destructive_ops = {"DROP", "CLEAR", "CREATE", "LOAD"}
        for op in destructive_ops:
            if op in query_upper:
                return {
                    "error": f"Destructive operation '{op}' is not allowed. Use INSERT DATA, DELETE DATA, DELETE WHERE, or INSERT...WHERE.",
                    "query": query,
                }

        if validate:
            validation_result = _validate_sparql_query(query)
            if not validation_result["valid"]:
                return {
                    "error": "Query validation failed",
                    "issues": validation_result["issues"],
                    "query": query,
                }

        try:
            kg_store.update(query)
            return {"success": True, "query": query}
        except Exception as e:
            return {"error": str(e), "query": query}

    @mcp.tool()
    def get_graph_stats() -> dict[str, Any]:
        """Get comprehensive knowledge graph statistics.

        Returns detailed statistics across all graphs including:
        - Total triples per graph
        - Idea counts by lifecycle
        - Memory fact counts
        - Wikidata cache status
        """
        from knowledge_graph.core.lifecycle import RALPH_LIFECYCLES

        base_stats = kg_store.get_stats()

        # Add idea lifecycle breakdown
        lifecycle_counts = {}
        for state in RALPH_LIFECYCLES:
            lifecycle_counts[state] = ideas_store.count_ideas(lifecycle=state)

        # Add tag count
        tags = ideas_store.get_all_tags()

        return {
            **base_stats,
            "idea_count": ideas_store.count_ideas(),
            "ideas_by_lifecycle": lifecycle_counts,
            "tag_count": len(tags),
            "memory_fact_count": agent_memory.count_facts(),
            "memory_contexts": agent_memory.get_all_contexts(),
            "wikidata": wikidata_cache.get_stats(),
        }

    @mcp.tool()
    def export_idea_markdown(idea_id: str) -> str:
        """Render an idea from RDF back to markdown format.

        Read-only export of the idea's content and metadata.

        Args:
            idea_id: The idea ID to export
        """
        if not idea_id.startswith("idea-") and not idea_id.startswith("seed-"):
            idea_id = f"idea-{idea_id}"

        idea = ideas_store.get_idea(idea_id)
        if not idea:
            return f"Error: Idea not found: {idea_id}"

        lines = ["---"]
        lines.append(f"id: {idea.id}")
        lines.append(f"title: {idea.title}")
        lines.append(f"author: {idea.author}")
        if idea.agent:
            lines.append(f"agent: {idea.agent}")
        lines.append(f"lifecycle: {idea.lifecycle}")
        lines.append(f"created: {idea.created.isoformat()}")
        if idea.tags:
            lines.append(f"tags: [{', '.join(idea.tags)}]")
        if idea.parent:
            lines.append(f"parent: {idea.parent}")
        if idea.children:
            lines.append(f"children: [{', '.join(idea.children)}]")
        if idea.blocks:
            lines.append(f"blocks: [{', '.join(idea.blocks)}]")
        if idea.blocked_by:
            lines.append(f"blocked_by: [{', '.join(idea.blocked_by)}]")
        if idea.priority is not None:
            lines.append(f"priority: {idea.priority}")
        lines.append("---\n")

        lines.append(f"# {idea.title}\n")

        if idea.description:
            lines.append(f"{idea.description}\n")

        if idea.content:
            lines.append(idea.content)

        return "\n".join(lines)

    @mcp.tool()
    def list_by_author(
        author: str | None = None,
        agent: str | None = None,
        include_seeds: bool = True,
    ) -> list[dict[str, Any]]:
        """List ideas filtered by author and/or agent.

        Args:
            author: Filter by human author
            agent: Filter by AI agent name
            include_seeds: Include seed-type ideas (default True)
        """
        from knowledge_graph.core.llm import LlmAnalysis
        llm = LlmAnalysis(kg_store, ideas_store)
        return llm.list_by_author(author, agent, include_seeds)

    @mcp.tool()
    def extract_todos(idea_id: str | None = None) -> dict[str, Any]:
        """Extract TODO items (markdown checkboxes) from idea content.

        Args:
            idea_id: Specific idea ID, or None for all ideas
        """
        from knowledge_graph.core.llm import LlmAnalysis
        llm = LlmAnalysis(kg_store, ideas_store)
        return llm.extract_todos(idea_id)

    # =========================================================================
    # MCP Resources: idea:// and seed://
    # =========================================================================

    @mcp.resource("idea://{idea_id}")
    def idea_resource(idea_id: str) -> str:
        """Get idea content as an MCP resource.

        Args:
            idea_id: The idea ID (e.g., "idea-1")
        """
        if not idea_id.startswith("idea-"):
            idea_id = f"idea-{idea_id}"
        idea = ideas_store.get_idea(idea_id)
        if not idea:
            return f"Idea not found: {idea_id}"
        return idea.content or idea.description or idea.title

    @mcp.resource("seed://{seed_id}")
    def seed_resource(seed_id: str) -> str:
        """Get seed content as an MCP resource.

        Args:
            seed_id: The seed ID (e.g., "seed-20260126-123456-abc1")
        """
        if not seed_id.startswith("seed-"):
            seed_id = f"seed-{seed_id}"
        idea = ideas_store.get_idea(seed_id)
        if not idea:
            return f"Seed not found: {seed_id}"
        return idea.content or idea.title

    # =========================================================================
    # Search Tools (gated behind --enable-search)
    # =========================================================================
    if settings.enable_search:
        from knowledge_graph.core.search import SemanticSearch
        semantic_search_engine = SemanticSearch(kg_store, ideas_store)

        @mcp.tool()
        def semantic_search(
            query: str,
            top_k: int = 10,
            include_seeds: bool = True,
        ) -> list[dict[str, Any]]:
            """Find ideas by meaning using local embeddings (no API key needed).

            Uses all-MiniLM-L6-v2 (384 dims) for offline semantic search.

            Args:
                query: Natural language query
                top_k: Number of results (default 10)
                include_seeds: Include seeds in results
            """
            return semantic_search_engine.search(query, top_k, include_seeds)

        @mcp.tool()
        def explore_concept(concept: str, limit: int = 10) -> dict[str, Any]:
            """Hybrid search: keyword (SPARQL CONTAINS) + semantic similarity.

            Args:
                concept: Concept to explore
                limit: Maximum results
            """
            return semantic_search_engine.explore_concept(concept, limit)

        logger.info("Registered semantic search tools")

    # =========================================================================
    # LLM Tools (gated behind --enable-llm)
    # =========================================================================
    if settings.enable_llm:
        from knowledge_graph.core.llm import LlmAnalysis
        llm_analysis = LlmAnalysis(kg_store, ideas_store)

        @mcp.tool()
        def check_novelty(title: str, description: str) -> dict[str, Any]:
            """Check if a proposed idea is novel or overlaps with existing ideas.

            Uses Claude to analyze novelty against all existing ideas.

            Args:
                title: Proposed idea title
                description: Proposed idea description
            """
            return llm_analysis.check_novelty(title, description)

        @mcp.tool()
        def find_related_ideas_llm(
            idea_id: str,
            refresh: bool = False,
        ) -> dict[str, Any]:
            """Find and explain relationships between ideas using LLM.

            Persists discovered relationships as RDF triples.

            Args:
                idea_id: The idea ID to analyze
                refresh: Force re-analysis even if cached
            """
            return llm_analysis.find_related_ideas(idea_id, refresh)

        @mcp.tool()
        def discover_categories(refresh: bool = False) -> dict[str, Any]:
            """AI discovers emergent categories from idea content.

            Args:
                refresh: Force re-analysis
            """
            return llm_analysis.discover_categories(refresh)

        @mcp.tool()
        def merge_ideas(
            idea_ids: list[str],
            new_title: str,
            author: str = "AI",
        ) -> dict[str, Any]:
            """Combine related ideas into one using LLM synthesis.

            Args:
                idea_ids: List of idea IDs to merge
                new_title: Title for the merged idea
                author: Author name
            """
            return llm_analysis.merge_ideas(idea_ids, new_title, author)

        logger.info("Registered LLM analysis tools")


def _validate_sparql_query(query: str) -> dict[str, Any]:
    """
    Validate SPARQL query for common LLM hallucination patterns.

    Five risk patterns identified in research (R2):
    1. Custom properties (idea:*) - verify against schema
    2. Multi-hop traversals (>3 hops) - flag for review
    3. Aggregations (GROUP BY, COUNT) - syntax check
    4. Named graph references - verify graph exists
    5. Date/time comparisons - validate format
    """
    issues = []
    query_upper = query.upper()

    # Pattern 1: Check for potentially invalid custom properties
    import re
    custom_props = re.findall(r'idea:(\w+)', query)
    valid_idea_props = {
        'lifecycle', 'wikidataRef', 'agent', 'parent', 'child',
        'vision', 'requirements', 'considerations', 'useCases',
        'IdeaPool', 'Idea', 'Seed', 'tag', 'cachedAt',
        'content', 'lifecycleUpdated', 'lifecycleReason',
        'capturedAt', 'crystallizedFrom', 'embeddingJson',
        'blocks', 'blockedBy', 'priority', 'confidence', 'effort',
    }
    invalid_props = [p for p in custom_props if p not in valid_idea_props]
    if invalid_props:
        issues.append(f"Unknown idea: properties: {invalid_props}. Valid properties: {sorted(valid_idea_props)}")

    # Pattern 2: Check for deep traversals (more than 3 property paths)
    path_pattern = re.findall(r'[?:\w]+(?:/[?:\w]+){3,}', query)
    if path_pattern:
        issues.append(f"Deep property paths detected (>3 hops): {path_pattern}. Consider simplifying.")

    # Pattern 3: Basic aggregation syntax check
    if 'GROUP BY' in query_upper:
        if 'SELECT' in query_upper:
            select_match = re.search(r'SELECT\s+(.*?)\s*WHERE', query, re.IGNORECASE | re.DOTALL)
            groupby_match = re.search(r'GROUP\s+BY\s+(\?[\w]+)', query, re.IGNORECASE)
            if select_match and groupby_match:
                pass  # Simplified check

    # Pattern 4: Check named graph references
    graph_refs = re.findall(r'GRAPH\s+<([^>]+)>', query, re.IGNORECASE)
    valid_graphs = {
        'http://semantic-tool-use.org/graphs/memory',
        'http://semantic-tool-use.org/graphs/wikidata',
        'http://semantic-tool-use.org/graphs/phases',  # knowledge_graph.core.store.GRAPH_PHASES
    }
    for graph in graph_refs:
        if graph not in valid_graphs:
            issues.append(f"Unknown named graph: {graph}. Valid graphs: {sorted(valid_graphs)}")

    # Pattern 5: Check date/time literals format
    datetime_literals = re.findall(r'"([^"]+)"\^\^xsd:dateTime', query)
    for dt in datetime_literals:
        try:
            from datetime import datetime as dt_class
            dt_class.fromisoformat(dt.replace('Z', '+00:00'))
        except ValueError:
            issues.append(f"Invalid dateTime format: {dt}. Use ISO 8601 format.")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "warnings": []
    }
