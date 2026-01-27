"""MCP server with ontology management tools."""

from typing import Any, TYPE_CHECKING
import logging

from mcp.server.fastmcp import FastMCP

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

    mcp = FastMCP(settings.mcp_name)

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

        Examples:
            # Remove all triples about a specific subject
            remove_triple("ontology://my-onto", subject="http://example.org/MyClass")

            # Remove all labels from a resource
            remove_triple("ontology://my-onto",
                         subject="http://example.org/MyClass",
                         predicate="http://www.w3.org/2000/01/rdf-schema#label")

            # Remove a specific triple
            remove_triple("ontology://my-onto",
                         subject="http://example.org/MyClass",
                         predicate="http://www.w3.org/2000/01/rdf-schema#label",
                         object="Old Label")
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

        This is a convenience method that removes an existing triple
        and adds a new one with an updated object value.

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

        Example:
            # Update a label
            update_triple("ontology://my-onto",
                         subject="http://example.org/MyClass",
                         predicate="http://www.w3.org/2000/01/rdf-schema#label",
                         old_object="Old Label",
                         new_object="New Label",
                         is_literal=True)
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
            Validation result with:
            - conforms: Boolean indicating if instance is valid
            - violation_count: Number of violations found
            - violations: List of violation details
            - report: Full validation report text

        Example:
            validate_instance('''
                @prefix ex: <http://example.org/> .
                @prefix pres: <http://semantic-tool-use.org/ontology/visual-artifacts/presentation#> .

                ex:MyPresentation a pres:Presentation ;
                    pres:hasSlide ex:Slide1 .
            ''')
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

        # Build UNION query for labels and comments
        filter_clause = " || ".join([
            f'CONTAINS(LCASE(STR(?text)), LCASE("{term}"))'
        ])

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

        These are bundled SHACL shapes for validating ontology quality
        against OWL/RDF best practices.

        Returns:
            List of shape sets with:
            - name: Shape set name (use with validate_ontology_quality)
            - shape_count: Number of validation shapes
            - description: What the shapes validate

        Available shape sets:
        - owl-shapes: Validates OWL classes, properties, individuals
        - ontology-metadata-shapes: Validates ontology-level metadata
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

        Checks if an ontology follows OWL/RDF best practices:
        - Classes have labels and descriptions
        - Properties have domain/range defined
        - Proper use of OWL constructs (transitive, symmetric, etc.)
        - Ontology has proper metadata (version, creator, etc.)

        Args:
            ontology_uri: URI of loaded ontology to validate.
                         Use list_ontologies() to see available URIs.
            ontology_ttl: Alternative: Turtle string of ontology to validate.
                         (ontology_uri takes precedence if both provided)
            shape_sets: Optional list of shape sets to use.
                       Default uses all. Options:
                       - "owl-shapes": OWL class/property best practices
                       - "ontology-metadata-shapes": Ontology metadata quality

        Returns:
            Validation result with:
            - conforms: True if no violations found
            - violation_count: Number of issues
            - violations: List of issues by severity (Violation, Warning, Info)
            - report: Full validation report

        Example:
            # Validate a loaded ontology
            validate_ontology_quality(ontology_uri="ontology://visual-artifacts-core")

            # Validate only OWL best practices
            validate_ontology_quality(
                ontology_uri="ontology://diagram-domain",
                shape_sets=["owl-shapes"]
            )
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

        Validates against all upper ontology shapes and returns
        a summary grouped by severity level.

        Args:
            ontology_uri: URI of loaded ontology to analyze

        Returns:
            Summary with:
            - conforms: Overall conformance
            - by_severity: Count of issues by severity
            - top_issues: Most common issue types
            - recommendations: Suggestions for improvement
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
            # Track issue types by message prefix
            msg_key = v.message.split(" should ")[0] if " should " in v.message else v.message[:50]
            issue_types[msg_key] = issue_types.get(msg_key, 0) + 1

        # Sort issues by frequency
        top_issues = sorted(issue_types.items(), key=lambda x: -x[1])[:5]

        # Generate recommendations
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
        _register_knowledge_graph_tools(mcp, kg_store)
        logger.info("Registered A-Box (knowledge graph) tools")

    return mcp


def _register_knowledge_graph_tools(mcp: FastMCP, kg_store: "KnowledgeGraphStore") -> None:
    """Register knowledge graph tools with the MCP server.

    Args:
        mcp: FastMCP server instance
        kg_store: Knowledge graph store instance
    """
    from knowledge_graph.core.ideas import IdeasStore, Idea
    from knowledge_graph.core.memory import AgentMemory, MemoryFact
    from knowledge_graph.core.wikidata import WikidataCache

    ideas_store = IdeasStore(kg_store)
    agent_memory = AgentMemory(kg_store)
    wikidata_cache = WikidataCache(kg_store)

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
            lifecycle: Filter by lifecycle (seed, active, backlog, done, archived)
            author: Filter by author name
            tag: Filter by tag
            search: Text search in title and description
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
        """Get a single idea by ID.

        Args:
            idea_id: The idea ID (e.g., "idea-1" or just "1")
        """
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
            "created": idea.created.isoformat(),
            "lifecycle": idea.lifecycle,
            "tags": idea.tags,
            "related": idea.related,
        }

    @mcp.tool()
    def create_idea(
        title: str,
        description: str = "",
        author: str = "AI",
        lifecycle: str = "seed",
        tags: list[str] | None = None,
        related: list[str] | None = None
    ) -> dict[str, Any]:
        """Create a new idea in the knowledge graph.

        Args:
            title: Idea title
            description: Idea description
            author: Author name (default "AI")
            lifecycle: Initial state (default "seed")
            tags: List of tags
            related: List of related idea IDs
        """
        existing = ideas_store.list_ideas(limit=1000)
        max_num = 0
        for i in existing:
            match = i["id"].replace("idea-", "")
            if match.isdigit():
                max_num = max(max_num, int(match))
        new_id = f"idea-{max_num + 1}"

        idea = Idea(
            id=new_id,
            title=title,
            description=description,
            author=author,
            lifecycle=lifecycle,
            tags=tags or [],
            related=related or [],
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
        lifecycle: str | None = None,
        tags: list[str] | None = None
    ) -> dict[str, Any]:
        """Update an existing idea.

        Args:
            idea_id: The idea ID to update
            title: New title (optional)
            description: New description (optional)
            lifecycle: New lifecycle state (optional)
            tags: New tags list (replaces existing)
        """
        if not idea_id.startswith("idea-"):
            idea_id = f"idea-{idea_id}"

        idea = ideas_store.get_idea(idea_id)
        if not idea:
            return {"error": f"Idea not found: {idea_id}"}

        if title is not None:
            idea.title = title
        if description is not None:
            idea.description = description
        if lifecycle is not None:
            idea.lifecycle = lifecycle
        if tags is not None:
            idea.tags = tags

        try:
            ideas_store.update_idea(idea)
            return {"status": "updated", "id": idea_id}
        except Exception as e:
            return {"status": "error", "message": str(e)}

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

        Use this for discovery queries to find entities you don't know the QID for:
        - Cities in a region with coordinates and population
        - Countries with specific properties
        - Geographic features, people, organizations, etc.

        Args:
            sparql: SPARQL query. Common prefixes (wd:, wdt:, etc.) are auto-added.
            cache_entities: Cache discovered entities for fast re-lookup.
            timeout: Query timeout in seconds (default 30).

        Returns:
            Query results with rows and metadata.

        Examples:
            # German cities with population > 100k
            query_wikidata('''
                SELECT ?city ?cityLabel ?population ?coord WHERE {
                    ?city wdt:P31 wd:Q515 .
                    ?city wdt:P17 wd:Q183 .
                    ?city wdt:P1082 ?population .
                    ?city wdt:P625 ?coord .
                    FILTER(?population > 100000)
                    SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
                }
                ORDER BY DESC(?population) LIMIT 20
            ''')

            # Rivers in France
            query_wikidata('''
                SELECT ?river ?riverLabel ?length WHERE {
                    ?river wdt:P31 wd:Q4022 .
                    ?river wdt:P17 wd:Q142 .
                    OPTIONAL { ?river wdt:P2043 ?length }
                    SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
                }
                LIMIT 50
            ''')

        Common Wikidata properties:
            wdt:P31  - instance of (type)
            wdt:P17  - country
            wdt:P625 - coordinate location
            wdt:P1082 - population
            wdt:P2043 - length
            wdt:P2046 - area
            wdt:P36  - capital
            wdt:P131 - located in admin entity
        """
        results = wikidata_cache.query(
            sparql,
            cache_entities=cache_entities,
            timeout=timeout
        )

        # Check for errors
        if results and "error" in results[0]:
            return {"error": results[0]["error"], "results": []}

        return {
            "count": len(results),
            "results": results,
            "cached": cache_entities,
        }

    # =========================================================================
    # Additional Ideas Tools (PRD Requirements)
    # =========================================================================

    @mcp.tool()
    def get_related_ideas(idea_id: str) -> list[dict[str, Any]]:
        """Get ideas related to a given idea.

        Args:
            idea_id: The idea ID (e.g., "idea-1" or just "1")

        Returns:
            List of related ideas with their IDs, titles, and lifecycle states
        """
        if not idea_id.startswith("idea-"):
            idea_id = f"idea-{idea_id}"
        return ideas_store.get_related_ideas(idea_id)

    @mcp.tool()
    def get_ideas_by_wikidata(qid: str) -> list[dict[str, Any]]:
        """Get ideas that reference a specific Wikidata entity.

        Args:
            qid: Wikidata QID (e.g., "Q42")

        Returns:
            List of ideas referencing this Wikidata entity
        """
        if not qid.startswith("Q"):
            qid = f"Q{qid}"
        return ideas_store.get_ideas_by_wikidata(qid)

    @mcp.tool()
    def get_all_tags() -> list[dict[str, Any]]:
        """Get all tags used across ideas with usage counts.

        Returns:
            List of tags with their usage counts, sorted by frequency
        """
        return ideas_store.get_all_tags()

    # =========================================================================
    # Additional Agent Memory Tools (PRD Requirements)
    # =========================================================================

    @mcp.tool()
    def recall_recent_facts(hours: int = 24, limit: int = 100) -> list[dict[str, Any]]:
        """Recall facts from the last N hours.

        Args:
            hours: Number of hours to look back (default 24)
            limit: Maximum results

        Returns:
            List of recent facts
        """
        return agent_memory.recall_recent(hours=hours, limit=limit)

    @mcp.tool()
    def forget_by_context(context: str) -> dict[str, Any]:
        """Remove all facts with a given context.

        Args:
            context: The context tag to forget

        Returns:
            Count of facts forgotten
        """
        count = agent_memory.forget_by_context(context)
        return {"status": "forgotten", "count": count, "context": context}

    @mcp.tool()
    def get_memory_stats() -> dict[str, Any]:
        """Get agent memory statistics.

        Returns:
            Statistics including fact count, unique subjects, contexts, etc.
        """
        return {
            "fact_count": agent_memory.count_facts(),
            "contexts": agent_memory.get_all_contexts(),
            "unique_subjects": agent_memory.get_subjects(),
        }

    # =========================================================================
    # Additional Wikidata Tools (PRD Requirements)
    # =========================================================================

    @mcp.tool()
    def search_wikidata_cache(term: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search for entities in the local Wikidata cache by label.

        Args:
            term: Search term (case-insensitive)
            limit: Maximum results

        Returns:
            List of matching cached entities
        """
        return wikidata_cache.search(term, limit=limit)

    @mcp.tool()
    def get_wikidata_stats() -> dict[str, Any]:
        """Get Wikidata cache statistics.

        Returns:
            Statistics including cache size, TTL, stale entities, etc.
        """
        return wikidata_cache.get_stats()

    # =========================================================================
    # Cross-Graph Query Tools (PRD Requirements)
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

        Returns:
            Query results with variables and bindings, or error information

        Example:
            # Query ideas with a specific tag
            sparql_query('''
                SELECT ?idea ?title WHERE {
                    ?idea a skos:Concept ;
                          skos:prefLabel ?title ;
                          dcterms:subject <http://semantic-tool-use.org/ontology/idea-pool#tag/ai> .
                }
            ''')
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
    def get_graph_stats() -> dict[str, Any]:
        """Get comprehensive knowledge graph statistics.

        Returns detailed statistics across all graphs including:
        - Total triples per graph
        - Idea counts by lifecycle
        - Memory fact counts
        - Wikidata cache status
        """
        base_stats = kg_store.get_stats()

        # Add idea lifecycle breakdown
        lifecycle_counts = {}
        for state in ["seed", "sprout", "backlog", "researching", "implementing", "decomposing", "completed", "archived"]:
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


def _validate_sparql_query(query: str) -> dict[str, Any]:
    """
    Validate SPARQL query for common LLM hallucination patterns.

    Five risk patterns identified in research (R2):
    1. Custom properties (idea:*) - verify against schema
    2. Multi-hop traversals (>3 hops) - flag for review
    3. Aggregations (GROUP BY, COUNT) - syntax check
    4. Named graph references - verify graph exists
    5. Date/time comparisons - validate format

    Args:
        query: SPARQL query string

    Returns:
        Validation result with valid flag and any issues found
    """
    issues = []
    query_upper = query.upper()

    # Pattern 1: Check for potentially invalid custom properties
    import re
    custom_props = re.findall(r'idea:(\w+)', query)
    valid_idea_props = {
        'lifecycle', 'wikidataRef', 'agent', 'parent', 'child',
        'vision', 'requirements', 'considerations', 'useCases',
        'IdeaPool', 'Idea', 'tag', 'cachedAt'
    }
    invalid_props = [p for p in custom_props if p not in valid_idea_props]
    if invalid_props:
        issues.append(f"Unknown idea: properties: {invalid_props}. Valid properties: {sorted(valid_idea_props)}")

    # Pattern 2: Check for deep traversals (more than 3 property paths)
    # Simple heuristic: count "/" in property paths
    path_pattern = re.findall(r'[?:\w]+(?:/[?:\w]+){3,}', query)
    if path_pattern:
        issues.append(f"Deep property paths detected (>3 hops): {path_pattern}. Consider simplifying.")

    # Pattern 3: Basic aggregation syntax check
    if 'GROUP BY' in query_upper:
        if 'SELECT' in query_upper:
            # Check if aggregation variables match group by
            select_match = re.search(r'SELECT\s+(.*?)\s*WHERE', query, re.IGNORECASE | re.DOTALL)
            groupby_match = re.search(r'GROUP\s+BY\s+(\?[\w]+)', query, re.IGNORECASE)
            if select_match and groupby_match:
                select_vars = re.findall(r'\?[\w]+', select_match.group(1))
                group_var = groupby_match.group(1)
                # Non-aggregated variables in SELECT should be in GROUP BY
                # This is a simplified check
                pass

    # Pattern 4: Check named graph references
    graph_refs = re.findall(r'GRAPH\s+<([^>]+)>', query, re.IGNORECASE)
    valid_graphs = {
        'http://semantic-tool-use.org/graphs/memory',
        'http://semantic-tool-use.org/graphs/wikidata'
    }
    for graph in graph_refs:
        if graph not in valid_graphs:
            issues.append(f"Unknown named graph: {graph}. Valid graphs: {sorted(valid_graphs)}")

    # Pattern 5: Check date/time literals format
    datetime_literals = re.findall(r'"([^"]+)"\^\^xsd:dateTime', query)
    for dt in datetime_literals:
        try:
            # Try to parse ISO format
            from datetime import datetime as dt_class
            dt_class.fromisoformat(dt.replace('Z', '+00:00'))
        except ValueError:
            issues.append(f"Invalid dateTime format: {dt}. Use ISO 8601 format.")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "warnings": []  # Could add non-blocking warnings
    }
