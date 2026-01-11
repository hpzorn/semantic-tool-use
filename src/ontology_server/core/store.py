"""In-memory RDF store with file-based persistence."""

from pathlib import Path
from typing import Any
import logging

from rdflib import Graph, Namespace, URIRef, Literal, RDF, RDFS, OWL
from rdflib.query import Result

logger = logging.getLogger(__name__)

# Common namespaces used in the Visual Artifacts Ontology
VAO = Namespace("http://semantic-tool-use.org/ontology/visual-artifacts#")
PRES = Namespace("http://semantic-tool-use.org/ontology/visual-artifacts/presentation#")
SOCIAL = Namespace("http://semantic-tool-use.org/ontology/visual-artifacts/social#")
DIAG = Namespace("http://semantic-tool-use.org/ontology/visual-artifacts/diagram#")


class OntologyStore:
    """In-memory RDF store with file-based persistence.

    Manages multiple named graphs, each representing an ontology.
    Supports SPARQL queries across single or all ontologies.
    """

    def __init__(self):
        self._graphs: dict[str, Graph] = {}
        self._metadata: dict[str, dict[str, Any]] = {}

    def load_ontology(self, uri: str, path: Path) -> Graph:
        """Load ontology from TTL file.

        Args:
            uri: Unique identifier for this ontology (e.g., "ontology://visual-artifacts/core")
            path: Path to the Turtle file

        Returns:
            The loaded RDF Graph
        """
        graph = Graph()
        graph.parse(path, format="turtle")

        # Bind common namespaces for cleaner serialization
        graph.bind("vao", VAO)
        graph.bind("pres", PRES)
        graph.bind("social", SOCIAL)
        graph.bind("diag", DIAG)
        graph.bind("owl", OWL)
        graph.bind("rdfs", RDFS)

        self._graphs[uri] = graph

        # Collect metadata about the ontology
        classes = list(graph.subjects(RDF.type, OWL.Class))
        properties = list(graph.subjects(RDF.type, OWL.ObjectProperty)) + \
                     list(graph.subjects(RDF.type, OWL.DatatypeProperty))
        individuals = list(graph.subjects(RDF.type, OWL.NamedIndividual))

        self._metadata[uri] = {
            "path": str(path.resolve()),
            "triple_count": len(graph),
            "class_count": len(classes),
            "property_count": len(properties),
            "individual_count": len(individuals),
        }

        logger.info(f"Loaded ontology {uri}: {len(graph)} triples")
        return graph

    def load_directory(self, base_path: Path, base_uri: str = "ontology://") -> int:
        """Load all TTL files from directory recursively.

        Args:
            base_path: Root directory to scan for .ttl files
            base_uri: Base URI prefix for loaded ontologies

        Returns:
            Number of ontologies loaded
        """
        if not base_path.exists():
            logger.warning(f"Ontology path does not exist: {base_path}")
            return 0

        count = 0
        for ttl_file in sorted(base_path.rglob("*.ttl")):
            # Skip files in examples directory for main ontology loading
            if "examples" in ttl_file.parts:
                continue

            rel_path = ttl_file.relative_to(base_path)
            # Create URI from path: ontology://visual-artifacts/core
            uri = f"{base_uri}{rel_path.with_suffix('')}".replace("\\", "/")

            try:
                self.load_ontology(uri, ttl_file)
                count += 1
            except Exception as e:
                logger.error(f"Failed to load {ttl_file}: {e}")

        return count

    def list_ontologies(self) -> list[dict[str, Any]]:
        """List all loaded ontologies with metadata.

        Returns:
            List of ontology info dicts with uri, path, and statistics
        """
        return [
            {"uri": uri, **meta}
            for uri, meta in sorted(self._metadata.items())
        ]

    def get_ontology(self, uri: str) -> Graph | None:
        """Get ontology Graph by URI.

        Args:
            uri: Ontology URI

        Returns:
            RDF Graph or None if not found
        """
        return self._graphs.get(uri)

    def get_ontology_ttl(self, uri: str) -> str | None:
        """Get ontology serialized as Turtle string.

        Args:
            uri: Ontology URI

        Returns:
            Turtle string or None if not found
        """
        graph = self._graphs.get(uri)
        if graph:
            return graph.serialize(format="turtle")
        return None

    def query(self, sparql: str, ontology_uri: str | None = None) -> Result:
        """Execute SPARQL query.

        Args:
            sparql: SPARQL query string
            ontology_uri: Optional URI to query single ontology; if None, queries all

        Returns:
            Query results

        Raises:
            ValueError: If specified ontology not found
        """
        if ontology_uri:
            graph = self._graphs.get(ontology_uri)
            if not graph:
                raise ValueError(f"Ontology not found: {ontology_uri}")
            return graph.query(sparql)
        else:
            # Query across all graphs by combining them
            combined = Graph()
            for g in self._graphs.values():
                combined += g
            return combined.query(sparql)

    def add_triple(
        self,
        ontology_uri: str,
        subject: str,
        predicate: str,
        obj: str,
        is_literal: bool = False
    ) -> bool:
        """Add a triple to an ontology.

        Args:
            ontology_uri: Target ontology URI
            subject: Subject URI
            predicate: Predicate URI
            obj: Object URI or literal value
            is_literal: If True, treat obj as a literal value

        Returns:
            True if successful, False if ontology not found
        """
        graph = self._graphs.get(ontology_uri)
        if not graph:
            return False

        subj_ref = URIRef(subject)
        pred_ref = URIRef(predicate)

        if is_literal:
            obj_node = Literal(obj)
        else:
            # Try to parse as URI, fall back to literal
            if obj.startswith("http://") or obj.startswith("https://"):
                obj_node = URIRef(obj)
            else:
                obj_node = Literal(obj)

        graph.add((subj_ref, pred_ref, obj_node))

        # Update triple count
        self._metadata[ontology_uri]["triple_count"] = len(graph)

        logger.debug(f"Added triple to {ontology_uri}: ({subject}, {predicate}, {obj})")
        return True

    def remove_triple(
        self,
        ontology_uri: str,
        subject: str | None = None,
        predicate: str | None = None,
        obj: str | None = None
    ) -> int:
        """Remove triples matching the pattern.

        Args:
            ontology_uri: Target ontology URI
            subject: Subject URI (None for wildcard)
            predicate: Predicate URI (None for wildcard)
            obj: Object URI/literal (None for wildcard)

        Returns:
            Number of triples removed
        """
        graph = self._graphs.get(ontology_uri)
        if not graph:
            return 0

        subj = URIRef(subject) if subject else None
        pred = URIRef(predicate) if predicate else None
        ob = URIRef(obj) if obj and (obj.startswith("http://") or obj.startswith("https://")) else (Literal(obj) if obj else None)

        before = len(graph)
        graph.remove((subj, pred, ob))
        after = len(graph)

        removed = before - after
        self._metadata[ontology_uri]["triple_count"] = after

        return removed

    def save_ontology(self, uri: str) -> bool:
        """Save ontology back to its original file.

        Args:
            uri: Ontology URI

        Returns:
            True if successful, False if not found
        """
        graph = self._graphs.get(uri)
        meta = self._metadata.get(uri)

        if graph and meta:
            path = Path(meta["path"])
            graph.serialize(path, format="turtle")
            logger.info(f"Saved ontology {uri} to {path}")
            return True
        return False

    def get_classes(self, ontology_uri: str | None = None) -> list[dict[str, str]]:
        """Get all OWL classes from ontology.

        Args:
            ontology_uri: Optional specific ontology; if None, queries all

        Returns:
            List of class info dicts with uri and label
        """
        sparql = """
        SELECT ?class ?label WHERE {
            ?class a owl:Class .
            OPTIONAL { ?class rdfs:label ?label }
        }
        ORDER BY ?class
        """
        results = self.query(sparql, ontology_uri)
        return [
            {
                "uri": str(row[0]),  # ?class
                "label": str(row[1]) if row[1] else None  # ?label
            }
            for row in results
        ]

    def get_properties(self, ontology_uri: str | None = None) -> list[dict[str, str]]:
        """Get all OWL properties from ontology.

        Args:
            ontology_uri: Optional specific ontology; if None, queries all

        Returns:
            List of property info dicts
        """
        sparql = """
        SELECT ?prop ?type ?label ?domain ?range WHERE {
            VALUES ?type { owl:ObjectProperty owl:DatatypeProperty }
            ?prop a ?type .
            OPTIONAL { ?prop rdfs:label ?label }
            OPTIONAL { ?prop rdfs:domain ?domain }
            OPTIONAL { ?prop rdfs:range ?range }
        }
        ORDER BY ?prop
        """
        results = self.query(sparql, ontology_uri)
        return [
            {
                "uri": str(row.prop),
                "type": str(row.type).split("#")[-1],
                "label": str(row.label) if row.label else None,
                "domain": str(row.domain) if row.domain else None,
                "range": str(row.range_) if hasattr(row, 'range_') and row.range_ else None,
            }
            for row in results
        ]

    def __len__(self) -> int:
        """Return total number of triples across all ontologies."""
        return sum(len(g) for g in self._graphs.values())

    def __contains__(self, uri: str) -> bool:
        """Check if ontology URI exists."""
        return uri in self._graphs
