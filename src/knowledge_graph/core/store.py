"""
Unified Oxigraph-based Knowledge Graph Store.

Provides a single triplestore with named graphs for different data types:
- Default graph: Ideas (SKOS:Concept)
- Named graph <memory:agent>: Agent memory (reified facts)
- Named graph <wikidata:cache>: Wikidata labels/descriptions
"""

import logging
from pathlib import Path
from typing import Any, Iterator
from dataclasses import dataclass

import pyoxigraph as ox

logger = logging.getLogger(__name__)


# Standard namespace URIs
# Integration with semantic-tool-use base ontology
NAMESPACES = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "owl": "http://www.w3.org/2002/07/owl#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "dcterms": "http://purl.org/dc/terms/",
    "foaf": "http://xmlns.com/foaf/0.1/",
    # Semantic Tool Use base ontology (BFO+CCO aligned)
    "stu": "http://semantic-tool-use.org/ontology/tool-use#",
    # Idea pool extension ontology
    "idea": "http://semantic-tool-use.org/ontology/idea-pool#",
    "ideas": "http://semantic-tool-use.org/ideas/",
    # Agent memory
    "memory": "http://semantic-tool-use.org/memory/",
    # External references
    "wd": "http://www.wikidata.org/entity/",
    "wdt": "http://www.wikidata.org/prop/direct/",
    "schema": "http://schema.org/",
    # BFO/CCO for alignment
    "bfo": "http://purl.obolibrary.org/obo/BFO_",
    "cco": "http://www.ontologyrepository.com/CommonCoreOntologies/",
}

# Named graph URIs (aligned with semantic-tool-use namespace)
GRAPH_MEMORY = "http://semantic-tool-use.org/graphs/memory"
GRAPH_WIKIDATA = "http://semantic-tool-use.org/graphs/wikidata"


@dataclass
class QueryResult:
    """Container for SPARQL query results."""
    variables: list[str]
    bindings: list[dict[str, Any]]

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self.bindings)

    def __len__(self) -> int:
        return len(self.bindings)


class KnowledgeGraphStore:
    """
    Unified Oxigraph-based triplestore with named graphs.

    Provides:
    - SPARQL 1.1 query support
    - Named graph isolation for different data types
    - RocksDB persistence
    - Transaction support

    Named Graphs:
    - Default: Ideas as SKOS:Concept
    - memory:agent: Agent memory (reified facts)
    - wikidata:cache: Cached Wikidata entities
    """

    def __init__(self, persist_path: str | Path | None = None):
        """
        Initialize the knowledge graph store.

        Args:
            persist_path: Path for RocksDB persistence. If None, uses in-memory store.
        """
        if persist_path:
            self._persist_path = Path(persist_path)
            self._persist_path.mkdir(parents=True, exist_ok=True)
            self._store = ox.Store(str(self._persist_path))
            logger.info(f"Initialized persistent store at {self._persist_path}")
        else:
            self._persist_path = None
            self._store = ox.Store()
            logger.info("Initialized in-memory store")

    @property
    def store(self) -> ox.Store:
        """Access the underlying Oxigraph store."""
        return self._store

    def _node(self, uri: str) -> ox.NamedNode:
        """Create a NamedNode from URI."""
        return ox.NamedNode(uri)

    def _literal(self, value: Any, datatype: str | None = None, lang: str | None = None) -> ox.Literal:
        """Create a Literal with optional datatype or language tag."""
        if lang:
            return ox.Literal(str(value), language=lang)
        if datatype:
            return ox.Literal(str(value), datatype=ox.NamedNode(datatype))
        return ox.Literal(str(value))

    def _graph_node(self, graph_uri: str | None = None) -> ox.NamedNode | ox.DefaultGraph:
        """Get the graph node for a named graph or default graph."""
        if graph_uri:
            return ox.NamedNode(graph_uri)
        return ox.DefaultGraph()

    def _expand_prefixes(self, sparql: str) -> str:
        """Add PREFIX declarations to SPARQL query if not present."""
        prefixes = []
        for prefix, uri in NAMESPACES.items():
            if f"{prefix}:" in sparql and f"PREFIX {prefix}:" not in sparql:
                prefixes.append(f"PREFIX {prefix}: <{uri}>")

        if prefixes:
            return "\n".join(prefixes) + "\n" + sparql
        return sparql

    def _extract_value(self, term: Any) -> Any:
        """Extract Python value from Oxigraph term."""
        if term is None:
            return None
        if isinstance(term, ox.NamedNode):
            return str(term.value)
        if isinstance(term, ox.Literal):
            value = term.value
            # Handle typed literals
            datatype = term.datatype
            if datatype:
                dt_str = str(datatype.value)
                if "integer" in dt_str or "int" in dt_str:
                    return int(value)
                if "decimal" in dt_str or "float" in dt_str or "double" in dt_str:
                    return float(value)
                if "boolean" in dt_str:
                    return value.lower() == "true"
            return value
        if isinstance(term, ox.BlankNode):
            return f"_:{term.value}"
        return str(term)

    def add_triple(
        self,
        subject: str,
        predicate: str,
        obj: str | Any,
        is_literal: bool = False,
        datatype: str | None = None,
        lang: str | None = None,
        graph: str | None = None
    ) -> None:
        """
        Add a triple to the store.

        Args:
            subject: Subject URI
            predicate: Predicate URI
            obj: Object URI or literal value
            is_literal: If True, treat obj as literal
            datatype: Optional XSD datatype for literal
            lang: Optional language tag for literal
            graph: Named graph URI (None for default graph)
        """
        s = self._node(subject)
        p = self._node(predicate)

        if is_literal or datatype or lang:
            o = self._literal(obj, datatype, lang)
        elif isinstance(obj, str) and (obj.startswith("http://") or obj.startswith("https://")):
            o = self._node(obj)
        else:
            o = self._literal(obj)

        g = self._graph_node(graph)
        self._store.add(ox.Quad(s, p, o, g))

    def remove_triple(
        self,
        subject: str | None = None,
        predicate: str | None = None,
        obj: str | None = None,
        graph: str | None = None
    ) -> int:
        """
        Remove triples matching the pattern.

        Args:
            subject: Subject URI (None for wildcard)
            predicate: Predicate URI (None for wildcard)
            obj: Object URI/literal (None for wildcard)
            graph: Named graph URI (None for default graph)

        Returns:
            Number of triples removed
        """
        s = self._node(subject) if subject else None
        p = self._node(predicate) if predicate else None
        g = self._graph_node(graph)

        # Handle object - could be URI or literal
        o = None
        if obj:
            if obj.startswith("http://") or obj.startswith("https://"):
                o = self._node(obj)
            else:
                o = self._literal(obj)

        # Find matching quads
        quads = list(self._store.quads_for_pattern(s, p, o, g))
        count = len(quads)

        for quad in quads:
            self._store.remove(quad)

        return count

    def query(self, sparql: str, default_graph: str | None = None) -> QueryResult:
        """
        Execute a SPARQL SELECT query.

        Args:
            sparql: SPARQL query string
            default_graph: Optional graph to use as default

        Returns:
            QueryResult with variables and bindings
        """
        sparql = self._expand_prefixes(sparql)

        try:
            results = self._store.query(sparql)

            # Get variable names from QuerySolutions
            variables = [str(var.value) for var in results.variables] if hasattr(results, 'variables') else []

            bindings = []
            for row in results:
                binding = {}
                # Access by variable name using string key
                for var in variables:
                    value = row[var]
                    binding[var] = self._extract_value(value)
                bindings.append(binding)

            return QueryResult(variables=variables, bindings=bindings)
        except Exception as e:
            logger.error(f"SPARQL query error: {e}\nQuery: {sparql}")
            raise

    def ask(self, sparql: str) -> bool:
        """Execute a SPARQL ASK query."""
        sparql = self._expand_prefixes(sparql)
        try:
            result = self._store.query(sparql)
            return bool(result)
        except Exception as e:
            logger.error(f"SPARQL ASK error: {e}")
            raise

    def update(self, sparql: str) -> None:
        """Execute a SPARQL UPDATE query."""
        sparql = self._expand_prefixes(sparql)
        try:
            self._store.update(sparql)
        except Exception as e:
            logger.error(f"SPARQL UPDATE error: {e}")
            raise

    def count_triples(self, graph: str | None = None) -> int:
        """Count triples in a graph."""
        g = self._graph_node(graph)
        return len(list(self._store.quads_for_pattern(None, None, None, g)))

    def export_turtle(self, graph: str | None = None) -> str:
        """Export graph as Turtle format."""
        g = self._graph_node(graph)
        quads = list(self._store.quads_for_pattern(None, None, None, g))

        # Build turtle manually since pyoxigraph doesn't have direct serialization
        lines = []

        # Add prefixes
        for prefix, uri in NAMESPACES.items():
            lines.append(f"@prefix {prefix}: <{uri}> .")
        lines.append("")

        # Group by subject
        by_subject: dict[str, list[tuple]] = {}
        for quad in quads:
            s = str(quad.subject.value)
            p = str(quad.predicate.value)
            o = quad.object

            if s not in by_subject:
                by_subject[s] = []
            by_subject[s].append((p, o))

        # Format triples
        for subj, po_list in sorted(by_subject.items()):
            # Compact URI if possible
            s_str = f"<{subj}>"
            for prefix, uri in NAMESPACES.items():
                if subj.startswith(uri):
                    s_str = f"{prefix}:{subj[len(uri):]}"
                    break

            lines.append(f"{s_str}")
            for i, (pred, obj) in enumerate(po_list):
                # Compact predicate
                p_str = f"<{pred}>"
                for prefix, uri in NAMESPACES.items():
                    if pred.startswith(uri):
                        p_str = f"{prefix}:{pred[len(uri):]}"
                        break

                # Format object
                if isinstance(obj, ox.NamedNode):
                    o_str = f"<{obj.value}>"
                    for prefix, uri in NAMESPACES.items():
                        if obj.value.startswith(uri):
                            o_str = f"{prefix}:{obj.value[len(uri):]}"
                            break
                elif isinstance(obj, ox.Literal):
                    if obj.language:
                        o_str = f'"{obj.value}"@{obj.language}'
                    elif obj.datatype:
                        dt = str(obj.datatype.value)
                        if dt == f"{NAMESPACES['xsd']}string":
                            o_str = f'"{obj.value}"'
                        else:
                            dt_compact = f"<{dt}>"
                            for prefix, uri in NAMESPACES.items():
                                if dt.startswith(uri):
                                    dt_compact = f"{prefix}:{dt[len(uri):]}"
                                    break
                            o_str = f'"{obj.value}"^^{dt_compact}'
                    else:
                        o_str = f'"{obj.value}"'
                else:
                    o_str = f'"{obj}"'

                sep = " ;" if i < len(po_list) - 1 else " ."
                lines.append(f"    {p_str} {o_str}{sep}")

        return "\n".join(lines)

    def load_turtle(self, turtle: str, graph: str | None = None) -> int:
        """
        Load Turtle data into a graph.

        Args:
            turtle: Turtle format RDF data
            graph: Named graph URI (None for default graph)

        Returns:
            Number of triples loaded
        """
        g = self._graph_node(graph)
        initial_count = self.count_triples(graph)

        # Parse and load
        for quad in ox.parse(turtle, "text/turtle"):
            # Rewrite to target graph
            new_quad = ox.Quad(quad.subject, quad.predicate, quad.object, g)
            self._store.add(new_quad)

        return self.count_triples(graph) - initial_count

    def clear_graph(self, graph: str | None = None) -> int:
        """Clear all triples from a graph."""
        g = self._graph_node(graph)
        quads = list(self._store.quads_for_pattern(None, None, None, g))
        count = len(quads)

        for quad in quads:
            self._store.remove(quad)

        logger.info(f"Cleared {count} triples from graph {graph or 'default'}")
        return count

    def flush(self) -> None:
        """Ensure all data is persisted to disk."""
        if self._persist_path:
            self._store.flush()
            logger.debug("Flushed store to disk")

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about the store."""
        default_count = self.count_triples()
        memory_count = self.count_triples(GRAPH_MEMORY)
        wikidata_count = self.count_triples(GRAPH_WIKIDATA)

        return {
            "total_triples": default_count + memory_count + wikidata_count,
            "default_graph_triples": default_count,
            "memory_graph_triples": memory_count,
            "wikidata_graph_triples": wikidata_count,
            "persist_path": str(self._persist_path) if self._persist_path else None,
        }
