"""MCP server with ontology management tools."""

from typing import Any
import logging

from mcp.server.fastmcp import FastMCP

from ..config import Settings
from ..core.store import OntologyStore
from ..core.validation import SHACLValidator

logger = logging.getLogger(__name__)


def create_mcp_server(
    settings: Settings,
    store: OntologyStore,
    validator: SHACLValidator | None = None
) -> FastMCP:
    """Create MCP server with ontology tools.

    Args:
        settings: Server configuration
        store: Initialized ontology store
        validator: Optional SHACL validator (created from settings if not provided)

    Returns:
        Configured FastMCP server instance
    """
    if validator is None:
        validator = SHACLValidator(settings.get_shapes_path())

    mcp = FastMCP(
        name=settings.mcp_name,
        version=settings.mcp_version,
    )

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
    return mcp
