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

import re
import time
import logging
from datetime import datetime, timezone
from typing import Any
from dataclasses import dataclass, field
import uuid

from .store import KnowledgeGraphStore, NAMESPACES, GRAPH_MEMORY

logger = logging.getLogger(__name__)


def _sparql_escape_literal(value: str) -> str:
    """Escape a string for safe embedding as a SPARQL plain-literal value."""
    value = value.replace("\\", "\\\\")
    value = value.replace('"', '\\"')
    value = value.replace("\n", "\\n")
    value = value.replace("\r", "\\r")
    return value


# Namespace shortcuts
RDF = NAMESPACES["rdf"]
XSD = NAMESPACES["xsd"]
MEMORY = NAMESPACES["memory"]
PROV = NAMESPACES["prov"]
IDEAS = NAMESPACES["ideas"]
AGENTS = NAMESPACES["agents"]

# The per-idea naming convention the pipeline has always used for contexts
# ("lesson-idea-9", "prd-idea-9", "arch-idea-9", "p4-tasks-idea-9", ...).
# Structural scoping materializes it as real graph edges so scoping is no
# longer a string convention (Workstream D1).
_CONTEXT_RE = re.compile(r"^(?P<kind>.+?)-(?P<idea>idea-\d+)$")


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
    agent: str | None = None  # storing agent name -> prov:wasAttributedTo

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
        try:
            self.materialize_scoping()
        except Exception:
            logger.exception("structural-scoping backfill failed (non-fatal)")

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

        # Structural scoping (Workstream D1): materialize the per-idea context
        # convention as REAL edges + PROV provenance, so scoping is graph
        # structure, not a string convention.
        self._add_structural_scoping(uri, fact.context)
        self._store.add_triple(
            uri,
            f"{PROV}generatedAtTime",
            fact.timestamp.isoformat(),
            datatype=f"{XSD}dateTime",
            graph=self._graph,
        )
        if fact.agent:
            self._store.add_triple(
                uri,
                f"{PROV}wasAttributedTo",
                f"{AGENTS}{fact.agent}",
                graph=self._graph,
            )

        self._store.flush()
        logger.debug(f"Stored fact: {fact.fact_id}")
        return fact.fact_id

    def _add_structural_scoping(self, fact_uri: str, context: str | None) -> bool:
        """Add memory:aboutIdea / memory:contextKind edges derived from the
        per-idea context convention. Returns True if edges were added."""
        if not context:
            return False
        m = _CONTEXT_RE.match(context)
        if not m:
            return False
        self._store.add_triple(
            fact_uri,
            f"{MEMORY}aboutIdea",
            f"{IDEAS}{m.group('idea')}",
            graph=self._graph,
        )
        self._store.add_triple(
            fact_uri,
            f"{MEMORY}contextKind",
            m.group("kind"),
            is_literal=True,
            graph=self._graph,
        )
        return True

    def materialize_scoping(self) -> int:
        """Backfill structural scoping for legacy facts (idempotent).

        Facts stored before Workstream D1 carry only the context string;
        this derives memory:aboutIdea / memory:contextKind for them so
        cross-idea queries see the whole brain, not just new facts.
        """
        query = f"""
        PREFIX memory: <{MEMORY}>
        PREFIX rdf: <{RDF}>
        SELECT ?fact ?context WHERE {{
            GRAPH <{self._graph}> {{
                ?fact rdf:type memory:Fact ;
                      memory:context ?context .
                FILTER NOT EXISTS {{ ?fact memory:aboutIdea ?any }}
            }}
        }}
        """
        migrated = 0
        for row in self._store.query(query):
            if self._add_structural_scoping(row["fact"], row.get("context")):
                migrated += 1
        if migrated:
            self._store.flush()
            logger.info("Materialized structural scoping for %d legacy facts", migrated)
        return migrated

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
            filters.append(f'FILTER(?subject = "{_sparql_escape_literal(subject)}")')
        if predicate:
            filters.append(f'FILTER(?predicate = "{_sparql_escape_literal(predicate)}")')
        if context:
            filters.append(f'FILTER(?context = "{_sparql_escape_literal(context)}")')
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

    def recall_lessons(
        self,
        files: list[str] | None = None,
        terms: list[str] | None = None,
        exclude_idea: str | None = None,
        idea: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Recall implementation lessons ACROSS ideas (Workstream D2).

        Lessons are memory facts with contextKind "lesson" (any idea). A
        lesson is *relevant* when its text — or a companion
        ``lesson:touchesFile`` fact sharing its memory:subject — mentions any
        of the given file basenames or terms. With no filters, returns the
        most recent lessons brain-wide.

        Args:
            files: file paths the current work touches (matched by basename)
            terms: free-text relevance terms (patterns, quality attributes)
            exclude_idea: idea id whose own lessons to skip (e.g. "idea-15")
            idea: restrict to ONE idea (mutually exclusive with exclude_idea)
            limit: max lessons returned, most recent first
        """
        needles: list[str] = []
        for f in files or []:
            base = f.rsplit("/", 1)[-1].strip().lower()
            if base:
                needles.append(base)
        needles += [t.strip().lower() for t in (terms or []) if t.strip()]

        filters: list[str] = ['FILTER(?predicate != "lesson:touchesFile")']
        if exclude_idea:
            eid = exclude_idea if exclude_idea.startswith("idea-") else f"idea-{exclude_idea}"
            filters.append(f"FILTER(!BOUND(?idea) || ?idea != <{IDEAS}{eid}>)")
        if idea:
            iid = idea if idea.startswith("idea-") else f"idea-{idea}"
            filters.append(f"FILTER(?idea = <{IDEAS}{iid}>)")
        if needles:
            esc = [_sparql_escape_literal(n) for n in needles]
            text_match = " || ".join(f'CONTAINS(LCASE(?object), "{n}")' for n in esc)
            file_match = " || ".join(f'CONTAINS(LCASE(?tfile), "{n}")' for n in esc)
            filters.append(
                f"FILTER( ({text_match}) || EXISTS {{\n"
                f'                ?tf memory:predicate "lesson:touchesFile" ;\n'
                f"                    memory:subject ?lsubj ;\n"
                f"                    memory:object ?tfile .\n"
                f"                FILTER({file_match})\n"
                f"            }} )"
            )

        filter_clause = "\n                ".join(filters)
        query = f"""
        PREFIX memory: <{MEMORY}>
        PREFIX rdf: <{RDF}>
        PREFIX prov: <{PROV}>

        SELECT ?fact ?lsubj ?object ?timestamp ?idea ?agent
        WHERE {{
            GRAPH <{self._graph}> {{
                ?fact rdf:type memory:Fact ;
                      memory:contextKind "lesson" ;
                      memory:subject ?lsubj ;
                      memory:predicate ?predicate ;
                      memory:object ?object ;
                      memory:timestamp ?timestamp .
                OPTIONAL {{ ?fact memory:aboutIdea ?idea }}
                OPTIONAL {{ ?fact prov:wasAttributedTo ?agent }}
                {filter_clause}
            }}
        }}
        ORDER BY DESC(?timestamp)
        LIMIT {int(limit)}
        """
        results = self._store.query(query)
        out = []
        for r in results:
            idea_uri = r.get("idea") or ""
            out.append({
                "lesson": r.get("object"),
                "idea": idea_uri.rsplit("/", 1)[-1] if idea_uri else None,
                "subject": r.get("lsubj"),
                "timestamp": r.get("timestamp"),
                "agent": (r.get("agent") or "").rsplit("/", 1)[-1] or None,
            })
        return out

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
