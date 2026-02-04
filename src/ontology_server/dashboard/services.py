"""Dashboard service layer.

Provides a unified interface for dashboard route handlers to access
ontology, ideas, and agent-memory data.  Replaces AggregatorClient
HTTP calls with direct store calls.

Key design decisions:
- T-Box SPARQL queries go through OntologyStore.query()  (rdflib)
- A-Box SPARQL queries go through KnowledgeGraphStore.query()  (Oxigraph)
- AgentMemory and IdeasStore methods are synchronous
- All public methods return JSON-serialisable dicts / lists
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from knowledge_graph.core.memory import AgentMemory
    from knowledge_graph.core.ideas import IdeasStore
    from knowledge_graph.core.store import KnowledgeGraphStore
    from ontology_server.core.store import OntologyStore

logger = logging.getLogger(__name__)


class DashboardService:
    """Facade that wraps the four backing stores for the dashboard UI.

    Parameters
    ----------
    ontology_store:
        RDFlib-backed T-Box store (OWL ontologies).
    kg_store:
        Oxigraph-backed unified A-Box store.
    agent_memory:
        Reified-statement memory layer (uses *kg_store* internally).
    ideas_store:
        SKOS+DC idea pool (uses *kg_store* internally).
    """

    def __init__(
        self,
        ontology_store: "OntologyStore",
        kg_store: "KnowledgeGraphStore",
        agent_memory: "AgentMemory",
        ideas_store: "IdeasStore",
    ) -> None:
        self._ontology_store = ontology_store
        self._kg_store = kg_store
        self._agent_memory = agent_memory
        self._ideas_store = ideas_store

    # ------------------------------------------------------------------
    # Ontology (T-Box) — uses OntologyStore
    # ------------------------------------------------------------------

    def list_ontologies(self) -> list[dict[str, Any]]:
        """Return metadata for every loaded ontology."""
        return self._ontology_store.list_ontologies()

    def list_classes(self, ontology_uri: str | None = None) -> list[dict[str, str]]:
        """Return OWL classes, optionally scoped to one ontology."""
        return self._ontology_store.get_classes(ontology_uri)

    def list_instances(
        self,
        class_uri: str,
        ontology_uri: str | None = None,
    ) -> list[dict[str, str]]:
        """Return named individuals of *class_uri*.

        Uses ``OntologyStore.query()`` (T-Box SPARQL).
        """
        sparql = f"""
        SELECT ?instance ?label WHERE {{
            ?instance a <{class_uri}> .
            OPTIONAL {{ ?instance rdfs:label ?label }}
        }}
        ORDER BY ?instance
        """
        results = self._ontology_store.query(sparql, ontology_uri)
        return [
            {
                "uri": str(row[0]),
                "label": str(row[1]) if row[1] else None,
                "class_uri": class_uri,
            }
            for row in results
        ]

    def get_instance_detail(
        self,
        instance_uri: str,
        ontology_uri: str | None = None,
    ) -> dict[str, Any]:
        """Return all predicate-object pairs for *instance_uri*.

        Uses ``OntologyStore.query()`` (T-Box SPARQL).
        """
        sparql = f"""
        SELECT ?predicate ?object WHERE {{
            <{instance_uri}> ?predicate ?object .
        }}
        ORDER BY ?predicate
        """
        results = self._ontology_store.query(sparql, ontology_uri)
        properties: list[dict[str, str]] = [
            {
                "predicate": str(row[0]),
                "object": str(row[1]),
            }
            for row in results
        ]
        return {
            "uri": instance_uri,
            "properties": properties,
        }

    # ------------------------------------------------------------------
    # Ideas (A-Box) — uses IdeasStore (synchronous)
    # ------------------------------------------------------------------

    def list_ideas(
        self,
        lifecycle: str | None = None,
        search: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List ideas with optional lifecycle filter or text search."""
        if search:
            return self._ideas_store.search_ideas(search, limit=limit)
        return self._ideas_store.list_ideas(lifecycle=lifecycle, limit=limit)

    def get_idea_detail(self, idea_id: str) -> dict[str, Any] | None:
        """Return full idea data or *None* if not found."""
        idea = self._ideas_store.get_idea(idea_id)
        if idea is None:
            return None
        data = asdict(idea)
        # Convert datetime objects to ISO strings for template rendering
        for key in ("created", "lifecycle_updated", "captured_at"):
            if data.get(key) is not None:
                data[key] = data[key].isoformat()
        return data

    def get_idea_lifecycle_summary(self) -> dict[str, int]:
        """Return ``{lifecycle_state: count}`` for all ideas."""
        all_ideas = self._ideas_store.list_ideas(limit=10000)
        summary: dict[str, int] = {}
        for idea in all_ideas:
            state = idea.get("lifecycle", "seed")
            summary[state] = summary.get(state, 0) + 1
        return summary

    # ------------------------------------------------------------------
    # Agent Memory (A-Box) — uses AgentMemory (synchronous)
    # ------------------------------------------------------------------

    def list_fact_contexts(self) -> list[str]:
        """Return all distinct memory contexts."""
        return self._agent_memory.get_all_contexts()

    def list_facts(
        self,
        context: str | None = None,
        subject: str | None = None,
        predicate: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Recall facts with optional filters."""
        return self._agent_memory.recall(
            subject=subject,
            predicate=predicate,
            context=context,
            limit=limit,
        )

    def get_fact_subjects(self, context: str) -> list[dict[str, Any]]:
        """Return distinct subjects within *context* with counts.

        Each entry includes the subject string, fact count, and
        distinct predicate count.
        """
        facts = self._agent_memory.recall(context=context, limit=10000)
        subject_facts: dict[str, list] = {}
        for fact in facts:
            subj = fact.get("subject")
            if subj:
                subject_facts.setdefault(subj, []).append(fact)
        result = []
        for subj in sorted(subject_facts):
            subj_list = subject_facts[subj]
            predicates = {f.get("predicate") for f in subj_list if f.get("predicate")}
            result.append({
                "subject": subj,
                "fact_count": len(subj_list),
                "predicate_count": len(predicates),
            })
        return result

    # ------------------------------------------------------------------
    # PRD / Requirements (stored as facts in Agent Memory)
    # ------------------------------------------------------------------

    def list_prd_contexts(self) -> list[dict[str, Any]]:
        """Return memory contexts that look like PRD contexts (``prd-*``).

        Each entry includes the context name, extracted PRD number,
        requirement count, and total fact count.
        """
        contexts = [
            ctx for ctx in self._agent_memory.get_all_contexts()
            if ctx.startswith("prd-")
        ]
        result = []
        for ctx in sorted(contexts):
            facts = self._agent_memory.recall(context=ctx, limit=10000)
            req_count = sum(
                1 for f in facts
                if f.get("predicate") == "rdf:type"
                and f.get("object") == "prd:Requirement"
            )
            # Extract number from "prd-idea-50" → "idea-50"
            prd_number = ctx.removeprefix("prd-")
            result.append({
                "context": ctx,
                "prd_number": prd_number,
                "requirement_count": req_count,
                "fact_count": len(facts),
            })
        return result

    def get_prd_requirements(self, context: str) -> list[dict[str, Any]]:
        """Return all requirements stored under a PRD *context*.

        Requirements are facts whose predicate is ``rdf:type`` and
        object is ``prd:Requirement``.  For each requirement subject
        found, all its properties are gathered.
        """
        type_facts = self._agent_memory.recall(
            context=context,
            predicate="rdf:type",
            limit=10000,
        )
        req_subjects = [
            f["subject"]
            for f in type_facts
            if f.get("object") == "prd:Requirement"
        ]

        requirements: list[dict[str, Any]] = []
        for subj in req_subjects:
            facts = self._agent_memory.recall(
                subject=subj,
                context=context,
                limit=1000,
            )
            props: dict[str, Any] = {"subject": subj}
            for fact in facts:
                pred = fact.get("predicate", "")
                obj = fact.get("object", "")
                # Collect multi-valued predicates as lists
                if pred in props:
                    existing = props[pred]
                    if isinstance(existing, list):
                        existing.append(obj)
                    else:
                        props[pred] = [existing, obj]
                else:
                    props[pred] = obj
            requirements.append(props)

        return requirements

    def get_requirement_detail(
        self,
        context: str,
        subject: str,
    ) -> dict[str, Any]:
        """Return all facts for a single requirement *subject* in *context*."""
        facts = self._agent_memory.recall(
            subject=subject,
            context=context,
            limit=1000,
        )
        props: dict[str, Any] = {"subject": subject, "context": context}
        for fact in facts:
            pred = fact.get("predicate", "")
            obj = fact.get("object", "")
            if pred in props:
                existing = props[pred]
                if isinstance(existing, list):
                    existing.append(obj)
                else:
                    props[pred] = [existing, obj]
            else:
                props[pred] = obj
        return props

    # ------------------------------------------------------------------
    # Aggregated dashboard summary
    # ------------------------------------------------------------------

    def get_dashboard_summary(self) -> dict[str, Any]:
        """Return a high-level summary for the dashboard landing page."""
        kg_stats = self._kg_store.get_stats()
        ontologies = self._ontology_store.list_ontologies()
        idea_count = self._ideas_store.count_ideas()
        fact_count = self._agent_memory.count_facts()
        contexts = self._agent_memory.get_all_contexts()
        prd_contexts = [c for c in contexts if c.startswith("prd-")]

        # Count classes across all ontologies
        all_classes = self._ontology_store.get_classes(None)
        class_count = len(all_classes)

        # Count instances (named individuals) across all ontologies
        try:
            instance_results = self._ontology_store.query(
                "SELECT (COUNT(DISTINCT ?i) AS ?c) WHERE { ?i a ?cls . ?cls a owl:Class }"
            )
            instance_count = int(list(instance_results)[0][0])
        except Exception:
            instance_count = 0

        return {
            "ontology_count": len(ontologies),
            "ontologies": ontologies,
            "total_tbox_triples": sum(
                o.get("triple_count", 0) for o in ontologies
            ),
            "class_count": class_count,
            "instance_count": instance_count,
            "idea_count": idea_count,
            "idea_lifecycle": self.get_idea_lifecycle_summary(),
            "prd_count": len(prd_contexts),
            "fact_count": fact_count,
            "fact_context_count": len(contexts),
            "kg_stats": kg_stats,
        }
