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

PHASE_NS = "http://impl-ralph.io/phase#"
TRACE_NS = "http://impl-ralph.io/trace#"
PRD_NS = "http://impl-ralph.io/prd#"
SKOS_NS = "http://www.w3.org/2004/02/skos/core#"
ISAQB_NS = "http://impl-ralph.io/isaqb#"
ARCH_NS = "http://impl-ralph.io/architecture#"
PHASES_GRAPH = "http://semantic-tool-use.org/graphs/phases"
KNOWN_PHASES = ["d0", "d1", "d2", "d3", "d4", "d5"]

# Quality Focus Chain mappings: quality focus → pattern → principle
# Based on iSAQB quality model and common design patterns
_QUALITY_FOCUS_CHAIN: dict[str, dict[str, str]] = {
    f"{ISAQB_NS}Usability": {
        "focus_label": "Usability",
        "pattern_uri": f"{ISAQB_NS}ProgressiveDisclosure",
        "pattern_label": "Progressive Disclosure",
        "principle_uri": f"{ISAQB_NS}SchemaFirstRendering",
        "principle_label": "Schema-First Rendering",
    },
    f"{ISAQB_NS}Maintainability": {
        "focus_label": "Maintainability",
        "pattern_uri": f"{ISAQB_NS}ServiceLayerAbstraction",
        "pattern_label": "Service Layer Abstraction",
        "principle_uri": f"{ISAQB_NS}ExtensionOverCreation",
        "principle_label": "Extension Over Creation",
    },
    f"{ISAQB_NS}Extensibility": {
        "focus_label": "Extensibility",
        "pattern_uri": f"{ISAQB_NS}RegistryPattern",
        "pattern_label": "Registry Pattern",
        "principle_uri": f"{ISAQB_NS}GracefulDegradation",
        "principle_label": "Graceful Degradation",
    },
    f"{ISAQB_NS}Performance": {
        "focus_label": "Performance",
        "pattern_uri": f"{ISAQB_NS}ProgressiveEnhancement",
        "pattern_label": "Progressive Enhancement",
        "principle_uri": f"{ISAQB_NS}MaximizeReuse",
        "principle_label": "Maximize Reuse",
    },
    f"{ISAQB_NS}FunctionalCorrectness": {
        "focus_label": "Functional Correctness",
        "pattern_uri": f"{ISAQB_NS}ServiceLayerOnly",
        "pattern_label": "Service Layer Only",
        "principle_uri": f"{ISAQB_NS}ReuseOverInvention",
        "principle_label": "Reuse Over Invention",
    },
    f"{ISAQB_NS}Operability": {
        "focus_label": "Operability",
        "pattern_uri": f"{ISAQB_NS}ProgressiveEnhancement",
        "pattern_label": "Progressive Enhancement",
        "principle_uri": f"{ISAQB_NS}MinimizeNewCode",
        "principle_label": "Minimize New Code",
    },
    # Support compact prefix forms
    "isaqb:Usability": {
        "focus_label": "Usability",
        "pattern_uri": "isaqb:ProgressiveDisclosure",
        "pattern_label": "Progressive Disclosure",
        "principle_uri": "isaqb:SchemaFirstRendering",
        "principle_label": "Schema-First Rendering",
    },
    "isaqb:Maintainability": {
        "focus_label": "Maintainability",
        "pattern_uri": "isaqb:ServiceLayerAbstraction",
        "pattern_label": "Service Layer Abstraction",
        "principle_uri": "isaqb:ExtensionOverCreation",
        "principle_label": "Extension Over Creation",
    },
    "isaqb:Extensibility": {
        "focus_label": "Extensibility",
        "pattern_uri": "isaqb:RegistryPattern",
        "pattern_label": "Registry Pattern",
        "principle_uri": "isaqb:GracefulDegradation",
        "principle_label": "Graceful Degradation",
    },
    "isaqb:Performance": {
        "focus_label": "Performance",
        "pattern_uri": "isaqb:ProgressiveEnhancement",
        "pattern_label": "Progressive Enhancement",
        "principle_uri": "isaqb:MaximizeReuse",
        "principle_label": "Maximize Reuse",
    },
    "isaqb:FunctionalCorrectness": {
        "focus_label": "Functional Correctness",
        "pattern_uri": "isaqb:ServiceLayerOnly",
        "pattern_label": "Service Layer Only",
        "principle_uri": "isaqb:ReuseOverInvention",
        "principle_label": "Reuse Over Invention",
    },
    "isaqb:Operability": {
        "focus_label": "Operability",
        "pattern_uri": "isaqb:ProgressiveEnhancement",
        "pattern_label": "Progressive Enhancement",
        "principle_uri": "isaqb:MinimizeNewCode",
        "principle_label": "Minimize New Code",
    },
}

# Type dispatch registry: maps RDF type URIs to route names
# Supports both full URIs and compact prefix forms
_TYPE_DISPATCH: dict[str, str] = {
    # Full URIs
    f"{PHASE_NS}PhaseOutput": "phase_detail",
    f"{SKOS_NS}Concept": "idea_detail",
    f"{PRD_NS}Requirement": "requirement_detail",
    f"{PRD_NS}Project": "project_detail",
    # Compact prefix forms (for KG results using compact prefixes)
    "phase:PhaseOutput": "phase_detail",
    "skos:Concept": "idea_detail",
    "prd:Requirement": "requirement_detail",
    "prd:Project": "project_detail",
}

_PRESERVES_PREFIX = f"{PHASE_NS}preserves-"
_ITERATION_INTENT_FIELDS = {
    "requirement_id", "quality_focus", "passed", "feedback", "commit_hash",
}


def _try_coerce(value: str) -> int | float | str:
    """Attempt to coerce a string value to int or float."""
    try:
        return int(value)
    except (ValueError, TypeError):
        pass
    try:
        return float(value)
    except (ValueError, TypeError):
        pass
    return value


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

    def get_quality_focus_chain(
        self, quality_focus_uri: str,
    ) -> dict[str, Any] | None:
        """Resolve a quality focus URI to its pattern and principle chain.

        Returns a dict with focus/pattern/principle labels and URIs, or None
        if the quality focus is not found in the mapping.
        """
        if not quality_focus_uri:
            return None

        chain = _QUALITY_FOCUS_CHAIN.get(quality_focus_uri)
        if chain:
            return {
                "focus_uri": quality_focus_uri,
                "focus_label": chain["focus_label"],
                "pattern_uri": chain["pattern_uri"],
                "pattern_label": chain["pattern_label"],
                "principle_uri": chain["principle_uri"],
                "principle_label": chain["principle_label"],
            }

        # Try to extract label from URI if not in mapping
        if "#" in quality_focus_uri:
            label = quality_focus_uri.split("#")[-1]
        elif ":" in quality_focus_uri:
            label = quality_focus_uri.split(":")[-1]
        else:
            label = quality_focus_uri

        # Return minimal chain with just the focus
        return {
            "focus_uri": quality_focus_uri,
            "focus_label": label,
            "pattern_uri": None,
            "pattern_label": None,
            "principle_uri": None,
            "principle_label": None,
        }

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

    # ------------------------------------------------------------------
    # Phase progress & facts (A-Box KG SPARQL)
    # ------------------------------------------------------------------

    def get_idea_progress(self, idea_id: str) -> dict[str, Any]:
        """Return phase-completion progress for *idea_id*.

        Queries the KG for ``phase:producedBy`` values linked to *idea_id*
        and computes completion percentage against :data:`KNOWN_PHASES`.
        """
        try:
            sparql = (
                f"PREFIX phase: <{PHASE_NS}>\n"
                f"SELECT DISTINCT ?phase WHERE {{\n"
                f"  GRAPH <{PHASES_GRAPH}> {{\n"
                f'    ?s phase:forRequirement "{idea_id}" .\n'
                f"    ?s phase:producedBy ?phase .\n"
                f"  }}\n"
                f"}}"
            )
            result = self._kg_store.query(sparql)
            raw_phases = [b.get("phase", "") for b in result.bindings]
        except Exception:
            logger.exception("get_idea_progress failed for %s", idea_id)
            return {
                "completed": [],
                "total": len(KNOWN_PHASES),
                "percent": 0,
                "current": None,
            }

        completed = sorted(p for p in raw_phases if p in KNOWN_PHASES)
        total = len(KNOWN_PHASES)
        percent = int(100 * len(completed) / total) if total else 0

        completed_set = set(completed)
        current: str | None = None
        for p in KNOWN_PHASES:
            if p not in completed_set:
                current = p
                break

        return {
            "completed": completed,
            "total": total,
            "percent": percent,
            "current": current,
        }

    def get_phase_facts(self, idea_id: str) -> dict[str, dict[str, Any]]:
        """Return grouped phase facts for *idea_id*.

        Groups ``phase:preserves-*`` triples into
        ``{phase_id: {field: coerced_value}}``.
        """
        try:
            sparql = (
                f"PREFIX phase: <{PHASE_NS}>\n"
                f"SELECT ?s ?p ?o WHERE {{\n"
                f"  GRAPH <{PHASES_GRAPH}> {{\n"
                f'    ?s phase:forRequirement "{idea_id}" .\n'
                f"    ?s ?p ?o .\n"
                f"  }}\n"
                f"}}"
            )
            result = self._kg_store.query(sparql)
        except Exception:
            logger.exception("get_phase_facts failed for %s", idea_id)
            return {}

        grouped: dict[str, dict[str, Any]] = {}
        for binding in result.bindings:
            pred = binding.get("p", "")
            if not pred.startswith(_PRESERVES_PREFIX):
                continue

            field_name = pred[len(_PRESERVES_PREFIX):]
            subj = binding.get("s", "")

            after_ns = subj[len(PHASE_NS):] if subj.startswith(PHASE_NS) else ""
            dash_idx = after_ns.find("-")
            if dash_idx == -1:
                continue
            phase_id = after_ns[dash_idx + 1:]

            value = _try_coerce(binding.get("o", ""))

            if phase_id not in grouped:
                grouped[phase_id] = {}
            grouped[phase_id][field_name] = value

        return grouped

    def get_phase_detail(
        self, idea_id: str, phase_id: str,
    ) -> dict[str, Any] | None:
        """Return intent fields, metadata, and trace ancestors for one phase."""
        subject = f"{PHASE_NS}{idea_id}-{phase_id}"

        try:
            sparql = f"SELECT ?p ?o WHERE {{ GRAPH <{PHASES_GRAPH}> {{ <{subject}> ?p ?o . }} }}"
            result = self._kg_store.query(sparql)
        except Exception:
            logger.exception("get_phase_detail query failed for %s", subject)
            return None

        if not result.bindings:
            return None

        intent_fields: dict[str, str] = {}
        metadata: dict[str, str] = {}

        for binding in result.bindings:
            pred = binding.get("p", "")
            obj = binding.get("o", "")

            if pred.startswith(_PRESERVES_PREFIX):
                field_name = pred[len(_PRESERVES_PREFIX):]
                intent_fields[field_name] = obj
            else:
                metadata[pred] = obj

        # Traverse trace:tracesTo chain
        trace_ancestors: list[str] = []
        try:
            ancestor_sparql = (
                f"PREFIX trace: <{TRACE_NS}>\n"
                f"SELECT ?ancestor WHERE {{\n"
                f"  GRAPH <{PHASES_GRAPH}> {{\n"
                f"    <{subject}> trace:tracesTo+ ?ancestor .\n"
                f"  }}\n"
                f"}}"
            )
            ancestor_result = self._kg_store.query(ancestor_sparql)
            trace_ancestors = [
                b.get("ancestor", "")
                for b in ancestor_result.bindings
                if b.get("ancestor")
            ]

            # Fetch facts for starting subject and ancestors
            for uri in [subject] + trace_ancestors:
                self._kg_store.query(f"SELECT ?p ?o WHERE {{ GRAPH <{PHASES_GRAPH}> {{ <{uri}> ?p ?o . }} }}")
        except Exception:
            logger.warning("traverse_chain failed for %s", subject)

        return {
            "phase_id": phase_id,
            "idea_id": idea_id,
            "intent_fields": intent_fields,
            "metadata": metadata,
            "trace_ancestors": trace_ancestors,
        }

    def _get_types(self, uri: str) -> list[str]:
        """Return rdf:type values for *uri* from the KG."""
        try:
            sparql = f"SELECT ?type WHERE {{ <{uri}> a ?type . }}"
            result = self._kg_store.query(sparql)
            return [b.get("type", "") for b in result.bindings if b.get("type")]
        except Exception:
            return []

    def _extract_route_params(
        self, route_name: str, uri: str,
    ) -> dict[str, Any]:
        """Extract route parameters based on route name and URI."""
        if route_name == "phase_detail":
            # URI format: http://impl-ralph.io/phase#<idea_id>-<phase_id>
            # e.g., http://impl-ralph.io/phase#idea-50-d0
            after_hash = uri.split("#", 1)[-1] if "#" in uri else uri.rsplit("/", 1)[-1]
            # Find the last dash to split idea_id and phase_id
            last_dash = after_hash.rfind("-")
            if last_dash != -1:
                idea_id = after_hash[:last_dash]
                phase_id = after_hash[last_dash + 1:]
            else:
                idea_id = after_hash
                phase_id = ""
            return {"idea_id": idea_id, "phase_id": phase_id}

        if route_name == "idea_detail":
            idea_id = uri.rsplit("/", 1)[-1]
            return {"idea_id": idea_id}

        if route_name == "requirement_detail":
            parts = uri.rsplit("/", 2)
            if len(parts) >= 3:
                context = parts[-2]
                subject = parts[-1]
            else:
                context = ""
                subject = parts[-1] if parts else ""
            return {"context": context, "subject": subject}

        if route_name == "project_detail":
            # URI format: http://impl-ralph.io/prd#project-<name>
            after_hash = uri.split("#", 1)[-1]
            return {"project_id": after_hash}

        return {"uri": uri}

    def resolve_uri(self, uri: str) -> tuple[str, dict[str, Any]]:
        """Determine the dashboard route for an arbitrary URI.

        Queries the KG for ``rdf:type`` and dispatches to the appropriate
        detail view using the _TYPE_DISPATCH registry. Falls back to
        ``generic_detail``.
        """
        # Self-referential guard
        if uri.startswith("/resolve/"):
            return "generic_detail", {"uri": uri}

        types = self._get_types(uri)
        if not types:
            return "generic_detail", {"uri": uri}

        # Look up each type in the dispatch registry
        for rdf_type in types:
            if rdf_type in _TYPE_DISPATCH:
                route_name = _TYPE_DISPATCH[rdf_type]
                params = self._extract_route_params(route_name, uri)
                return route_name, params

        return "generic_detail", {"uri": uri}

    def get_iteration_facts(self, idea_id: str) -> list[dict[str, Any]]:
        """Return implementation iteration facts for *idea_id*.

        Queries for ``impl-*`` phase outputs and extracts the five known
        iteration intent fields.
        """
        try:
            sparql = (
                f"PREFIX phase: <{PHASE_NS}>\n"
                f"SELECT ?s ?p ?o WHERE {{\n"
                f"  GRAPH <{PHASES_GRAPH}> {{\n"
                f'    ?s phase:forRequirement "{idea_id}" .\n'
                f"    ?s phase:producedBy ?produced .\n"
                f'    FILTER(STRSTARTS(?produced, "impl-"))\n'
                f"    ?s ?p ?o .\n"
                f"  }}\n"
                f"}}"
            )
            result = self._kg_store.query(sparql)
        except Exception:
            logger.exception("get_iteration_facts failed for %s", idea_id)
            return []

        by_subject: dict[str, dict[str, str]] = {}
        for binding in result.bindings:
            subj = binding.get("s", "")
            pred = binding.get("p", "")
            obj = binding.get("o", "")

            if not pred.startswith(_PRESERVES_PREFIX):
                continue
            field_name = pred[len(_PRESERVES_PREFIX):]
            if field_name not in _ITERATION_INTENT_FIELDS:
                continue

            if subj not in by_subject:
                by_subject[subj] = {}
            by_subject[subj][field_name] = obj

        return [by_subject[s] for s in sorted(by_subject)]

    def get_requirement_phase_history(
        self, context: str, subject: str,
    ) -> list[dict[str, Any]]:
        """Return ordered phase outputs linked to a requirement *subject*.

        Follows ``trace:tracesTo`` links to include ancestor phases.
        """
        try:
            sparql = (
                f"PREFIX phase: <{PHASE_NS}>\n"
                f"SELECT ?s ?p ?o WHERE {{\n"
                f"  GRAPH <{PHASES_GRAPH}> {{\n"
                f'    ?s phase:forRequirement "{subject}" .\n'
                f"    ?s ?p ?o .\n"
                f"  }}\n"
                f"}}"
            )
            result = self._kg_store.query(sparql)
        except Exception:
            logger.exception(
                "get_requirement_phase_history failed for %s/%s", context, subject,
            )
            return []

        if not result.bindings:
            return []

        by_subject: dict[str, list[tuple[str, str]]] = {}
        traced_ancestors: list[str] = []

        for binding in result.bindings:
            subj = binding.get("s", "")
            pred = binding.get("p", "")
            obj = binding.get("o", "")

            if subj not in by_subject:
                by_subject[subj] = []
            by_subject[subj].append((pred, obj))

            if pred == f"{TRACE_NS}tracesTo" and obj not in by_subject:
                traced_ancestors.append(obj)

        # Fetch traced ancestor triples
        for ancestor_uri in traced_ancestors:
            try:
                anc_sparql = f"SELECT ?p ?o WHERE {{ <{ancestor_uri}> ?p ?o . }}"
                anc_result = self._kg_store.query(anc_sparql)
                if anc_result.bindings:
                    by_subject[ancestor_uri] = [
                        (b.get("p", ""), b.get("o", ""))
                        for b in anc_result.bindings
                    ]
            except Exception:
                logger.warning("Failed to fetch ancestor %s", ancestor_uri)

        output: list[dict[str, Any]] = []
        for subj_uri in sorted(by_subject):
            po_pairs = by_subject[subj_uri]

            produced_by: str | None = None
            intent_fields: dict[str, str] = {}
            timestamp: str | None = None

            for pred, obj in po_pairs:
                if pred == f"{PHASE_NS}producedBy":
                    produced_by = obj
                elif pred.startswith(_PRESERVES_PREFIX):
                    field_name = pred[len(_PRESERVES_PREFIX):]
                    if field_name == "timestamp":
                        timestamp = obj
                    else:
                        intent_fields[field_name] = obj

            phase_id = produced_by
            if phase_id is None:
                after_ns = subj_uri[len(PHASE_NS):] if subj_uri.startswith(PHASE_NS) else ""
                dash_idx = after_ns.find("-")
                if dash_idx != -1:
                    phase_id = after_ns[dash_idx + 1:]

            output.append({
                "phase_id": phase_id,
                "produced_by": produced_by,
                "intent_fields": intent_fields,
                "timestamp": timestamp,
            })

        return output

    def get_triples_for_uri(self, uri: str) -> list[dict[str, str]]:
        """Return all predicate-object pairs for *uri* from the KG.

        Queries across all named graphs to find triples for the URI.
        """
        try:
            # Query across all graphs to find triples
            sparql = f"SELECT ?p ?o WHERE {{ GRAPH ?g {{ <{uri}> ?p ?o . }} }}"
            result = self._kg_store.query(sparql)
            return [
                {"predicate": b.get("p", ""), "object": b.get("o", "")}
                for b in result.bindings
            ]
        except Exception:
            logger.warning("get_triples_for_uri failed for %s", uri)
            return []
