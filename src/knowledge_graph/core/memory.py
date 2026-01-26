"""
Agent Memory - Persistent memory for AI agents using reified statements.

Integrates with semantic-tool-use ontology:
- Memory facts can be attributed to stu:Agent instances
- Aligns with stu:Agent from tool-use-core.ttl

Stores facts as reified statements with metadata:
- Subject, predicate, object (the fact)
- Timestamp (when stored)
- Confidence (0.0-1.0)
- Context (session ID, topic, etc.)

All data is stored in the named graph <http://semantic-tool-use.org/graphs/memory>.
"""

import time
import logging
from datetime import datetime, timezone
from typing import Any
from dataclasses import dataclass, field
import uuid

from .store import KnowledgeGraphStore, NAMESPACES, GRAPH_MEMORY

logger = logging.getLogger(__name__)

# Namespace shortcuts
RDF = NAMESPACES["rdf"]
XSD = NAMESPACES["xsd"]
MEMORY = NAMESPACES["memory"]


@dataclass
class MemoryFact:
    """A fact stored in agent memory."""
    subject: str
    predicate: str
    object: str
    context: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float = 1.0
    fact_id: str | None = None

    def __post_init__(self):
        if self.fact_id is None:
            self.fact_id = str(uuid.uuid4())[:8]


class AgentMemory:
    """
    Persistent agent memory using reified statement pattern.

    Integrates with semantic-tool-use ontology (stu:Agent alignment).

    Provides:
    - Store facts with metadata
    - Recall by subject, predicate, or context
    - Temporal queries (recent facts)
    - Forget (delete) facts

    All data is stored in the named graph <http://semantic-tool-use.org/graphs/memory>.
    """

    def __init__(self, store: KnowledgeGraphStore):
        """
        Initialize agent memory.

        Args:
            store: The underlying knowledge graph store
        """
        self._store = store
        self._graph = GRAPH_MEMORY
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize the memory schema if not present."""
        # Check if schema exists
        query = f"""
        ASK WHERE {{
            GRAPH <{self._graph}> {{
                <{MEMORY}Fact> a rdfs:Class .
            }}
        }}
        """
        try:
            if self._store.ask(query):
                logger.debug("Memory schema already initialized")
                return
        except Exception:
            pass  # Schema doesn't exist yet

        logger.info("Initializing agent memory schema")

        # Define Fact class
        self._store.add_triple(
            f"{MEMORY}Fact",
            f"{RDF}type",
            f"{NAMESPACES['rdfs']}Class",
            graph=self._graph
        )
        self._store.add_triple(
            f"{MEMORY}Fact",
            f"{NAMESPACES['rdfs']}label",
            "A reified fact in agent memory",
            is_literal=True,
            graph=self._graph
        )

        # Define properties
        for prop in ["subject", "predicate", "object", "timestamp", "confidence", "context"]:
            self._store.add_triple(
                f"{MEMORY}{prop}",
                f"{RDF}type",
                f"{RDF}Property",
                graph=self._graph
            )

        self._store.flush()

    def _fact_uri(self, fact_id: str) -> str:
        """Generate URI for a fact."""
        return f"{MEMORY}fact/{fact_id}"

    def store_fact(self, fact: MemoryFact) -> str:
        """
        Store a fact in memory.

        Args:
            fact: The MemoryFact to store

        Returns:
            The fact ID
        """
        uri = self._fact_uri(fact.fact_id)

        # Type
        self._store.add_triple(
            uri,
            f"{RDF}type",
            f"{MEMORY}Fact",
            graph=self._graph
        )

        # Fact content
        self._store.add_triple(
            uri,
            f"{MEMORY}subject",
            fact.subject,
            is_literal=True,
            graph=self._graph
        )
        self._store.add_triple(
            uri,
            f"{MEMORY}predicate",
            fact.predicate,
            is_literal=True,
            graph=self._graph
        )
        self._store.add_triple(
            uri,
            f"{MEMORY}object",
            fact.object,
            is_literal=True,
            graph=self._graph
        )

        # Metadata
        self._store.add_triple(
            uri,
            f"{MEMORY}timestamp",
            fact.timestamp.isoformat(),
            datatype=f"{XSD}dateTime",
            graph=self._graph
        )
        self._store.add_triple(
            uri,
            f"{MEMORY}confidence",
            str(fact.confidence),
            datatype=f"{XSD}decimal",
            graph=self._graph
        )

        if fact.context:
            self._store.add_triple(
                uri,
                f"{MEMORY}context",
                fact.context,
                is_literal=True,
                graph=self._graph
            )

        self._store.flush()
        logger.debug(f"Stored fact: {fact.fact_id}")
        return fact.fact_id

    def recall(
        self,
        subject: str | None = None,
        predicate: str | None = None,
        context: str | None = None,
        min_confidence: float | None = None,
        limit: int = 100
    ) -> list[dict[str, Any]]:
        """
        Recall facts from memory with optional filters.

        Args:
            subject: Filter by subject
            predicate: Filter by predicate
            context: Filter by context
            min_confidence: Minimum confidence threshold
            limit: Maximum results

        Returns:
            List of matching facts
        """
        filters = []
        if subject:
            filters.append(f'FILTER(?subject = "{subject}")')
        if predicate:
            filters.append(f'FILTER(?predicate = "{predicate}")')
        if context:
            filters.append(f'FILTER(?context = "{context}")')
        if min_confidence is not None:
            filters.append(f'FILTER(?confidence >= {min_confidence})')

        filter_clause = "\n".join(filters)

        query = f"""
        PREFIX memory: <{MEMORY}>
        PREFIX rdf: <{RDF}>
        PREFIX xsd: <{XSD}>

        SELECT ?fact ?subject ?predicate ?object ?timestamp ?confidence ?context
        WHERE {{
            GRAPH <{self._graph}> {{
                ?fact rdf:type memory:Fact ;
                      memory:subject ?subject ;
                      memory:predicate ?predicate ;
                      memory:object ?object ;
                      memory:timestamp ?timestamp ;
                      memory:confidence ?confidence .
                OPTIONAL {{ ?fact memory:context ?context }}
                {filter_clause}
            }}
        }}
        ORDER BY DESC(?timestamp)
        LIMIT {limit}
        """

        results = self._store.query(query)
        return [
            {
                "fact_id": r["fact"].split("/")[-1] if r.get("fact") else None,
                "subject": r.get("subject"),
                "predicate": r.get("predicate"),
                "object": r.get("object"),
                "timestamp": r.get("timestamp"),
                "confidence": float(r["confidence"]) if r.get("confidence") else 1.0,
                "context": r.get("context"),
            }
            for r in results
        ]

    def recall_recent(self, hours: int = 24, limit: int = 100) -> list[dict[str, Any]]:
        """
        Recall facts from the last N hours.

        Args:
            hours: Number of hours to look back
            limit: Maximum results

        Returns:
            List of recent facts
        """
        cutoff = datetime.now(timezone.utc)
        cutoff = cutoff.replace(hour=max(0, cutoff.hour - hours % 24))
        if hours >= 24:
            # Approximate days
            days = hours // 24
            cutoff = cutoff.replace(day=max(1, cutoff.day - days))

        query = f"""
        PREFIX memory: <{MEMORY}>
        PREFIX rdf: <{RDF}>
        PREFIX xsd: <{XSD}>

        SELECT ?fact ?subject ?predicate ?object ?timestamp ?confidence ?context
        WHERE {{
            GRAPH <{self._graph}> {{
                ?fact rdf:type memory:Fact ;
                      memory:subject ?subject ;
                      memory:predicate ?predicate ;
                      memory:object ?object ;
                      memory:timestamp ?timestamp ;
                      memory:confidence ?confidence .
                OPTIONAL {{ ?fact memory:context ?context }}
                FILTER(?timestamp >= "{cutoff.isoformat()}"^^xsd:dateTime)
            }}
        }}
        ORDER BY DESC(?timestamp)
        LIMIT {limit}
        """

        results = self._store.query(query)
        return [
            {
                "fact_id": r["fact"].split("/")[-1] if r.get("fact") else None,
                "subject": r.get("subject"),
                "predicate": r.get("predicate"),
                "object": r.get("object"),
                "timestamp": r.get("timestamp"),
                "confidence": float(r["confidence"]) if r.get("confidence") else 1.0,
                "context": r.get("context"),
            }
            for r in results
        ]

    def forget(self, fact_id: str) -> bool:
        """
        Remove a fact from memory.

        Args:
            fact_id: The fact ID to forget

        Returns:
            True if deleted, False if not found
        """
        uri = self._fact_uri(fact_id)

        # Check if exists
        query = f"""
        ASK WHERE {{
            GRAPH <{self._graph}> {{
                <{uri}> a <{MEMORY}Fact> .
            }}
        }}
        """
        if not self._store.ask(query):
            return False

        # Remove all triples about this fact
        # Use native Oxigraph method since we're in a named graph
        fact_node = self._store._node(uri)
        graph_node = self._store._node(self._graph)

        quads = list(self._store.store.quads_for_pattern(fact_node, None, None, graph_node))
        for quad in quads:
            self._store.store.remove(quad)

        self._store.flush()
        logger.debug(f"Forgot fact: {fact_id}")
        return True

    def forget_by_context(self, context: str) -> int:
        """
        Remove all facts with a given context.

        Args:
            context: The context to forget

        Returns:
            Number of facts deleted
        """
        # First get all facts with this context
        facts = self.recall(context=context, limit=10000)
        count = 0
        for fact in facts:
            if self.forget(fact["fact_id"]):
                count += 1
        return count

    def count_facts(self) -> int:
        """Count total facts in memory."""
        query = f"""
        PREFIX memory: <{MEMORY}>
        PREFIX rdf: <{RDF}>

        SELECT (COUNT(?fact) as ?count)
        WHERE {{
            GRAPH <{self._graph}> {{
                ?fact rdf:type memory:Fact .
            }}
        }}
        """

        results = self._store.query(query)
        if results.bindings:
            return int(results.bindings[0].get("count", 0))
        return 0

    def get_all_contexts(self) -> list[str]:
        """Get all unique contexts in memory."""
        query = f"""
        PREFIX memory: <{MEMORY}>

        SELECT DISTINCT ?context
        WHERE {{
            GRAPH <{self._graph}> {{
                ?fact memory:context ?context .
            }}
        }}
        ORDER BY ?context
        """

        results = self._store.query(query)
        return [r["context"] for r in results if r.get("context")]

    def get_subjects(self) -> list[str]:
        """Get all unique subjects in memory."""
        query = f"""
        PREFIX memory: <{MEMORY}>

        SELECT DISTINCT ?subject
        WHERE {{
            GRAPH <{self._graph}> {{
                ?fact memory:subject ?subject .
            }}
        }}
        ORDER BY ?subject
        """

        results = self._store.query(query)
        return [r["subject"] for r in results if r.get("subject")]

    def clear_memory(self) -> int:
        """Clear all facts from memory."""
        count = self._store.clear_graph(self._graph)
        self._init_schema()  # Re-initialize schema
        logger.info(f"Cleared agent memory ({count} triples)")
        return count
