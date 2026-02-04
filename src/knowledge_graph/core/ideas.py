"""
Ideas Store - SKOS+Dublin Core based idea storage.

Models ideas as SKOS:Concept AND stu:Resource with Dublin Core metadata.

Integrates with semantic-tool-use base ontology (BFO+CCO aligned):
- Ideas are both skos:Concept and stu:Resource (from tool-use-core.ttl)
- idea:Idea is defined as subclass of stu:Resource
- Aligns with semantic-tool-use namespace: http://semantic-tool-use.org/ontology/

Ontology:
- Ideas are skos:Concept + stu:Resource instances
- skos:prefLabel for title
- dcterms:description for description
- dcterms:creator for author
- dcterms:created for creation date
- dcterms:subject for tags (pointing to skos:Concept)
- skos:related for related ideas
- idea:lifecycle for lifecycle state
- idea:wikidataRef for Wikidata entity references
- idea:content for full markdown content
- idea:blocks / idea:blockedBy for dependencies
"""

import re
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from dataclasses import dataclass, field

from .store import KnowledgeGraphStore, NAMESPACES

logger = logging.getLogger(__name__)

# Namespace shortcuts
RDF = NAMESPACES["rdf"]
RDFS = NAMESPACES["rdfs"]
XSD = NAMESPACES["xsd"]
OWL = NAMESPACES["owl"]
SKOS = NAMESPACES["skos"]
DCTERMS = NAMESPACES["dcterms"]
IDEA = NAMESPACES["idea"]
IDEAS = NAMESPACES["ideas"]
WD = NAMESPACES["wd"]
# Semantic Tool Use base ontology
STU = NAMESPACES["stu"]


@dataclass
class Idea:
    """Represents an idea in the knowledge graph.

    Custom properties per PRD RQ3 (SKOS+DC with 5 custom properties):
    - lifecycle: Current state of the idea (seed, backlog, researching, etc.)
    - vision: High-level goal or vision statement
    - requirements: List of requirements for implementation
    - considerations: List of considerations, constraints, or trade-offs
    - useCases: List of use cases or applications
    """
    id: str  # e.g., "idea-1" or "idea-17a"
    title: str
    description: str = ""
    content: str = ""  # Full markdown content
    author: str = "unknown"
    agent: str | None = None
    created: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    lifecycle: str = "seed"
    lifecycle_updated: datetime | None = None
    lifecycle_reason: str = ""
    tags: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)  # list of idea IDs
    wikidata_refs: list[str] = field(default_factory=list)  # list of Q-numbers
    parent: str | None = None  # parent idea ID for sub-ideas
    children: list[str] = field(default_factory=list)  # child idea IDs
    blocks: list[str] = field(default_factory=list)  # idea IDs this blocks
    blocked_by: list[str] = field(default_factory=list)  # idea IDs blocking this
    is_seed: bool = False  # True if rdf:type includes idea:Seed
    captured_at: datetime | None = None  # For seeds
    crystallized_from: str | None = None  # Seed ID this was crystallized from
    embedding: list[float] = field(default_factory=list)
    priority: int | None = None
    # PRD custom properties (RQ3: 5 custom properties for SKOS+DC)
    vision: str | None = None
    requirements: list[str] = field(default_factory=list)
    considerations: list[str] = field(default_factory=list)
    use_cases: list[str] = field(default_factory=list)

    @property
    def uri(self) -> str:
        """Get the full URI for this idea."""
        return f"{IDEAS}{self.id}"


class IdeasStore:
    """
    Store for ideas using SKOS+Dublin Core ontology.

    Provides CRUD operations and SPARQL queries for ideas.
    Ideas are stored in the default graph of the knowledge graph.
    """

    def __init__(self, store: KnowledgeGraphStore):
        """
        Initialize the ideas store.

        Args:
            store: The underlying knowledge graph store
        """
        self._store = store
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize the SKOS+DC schema (T-Box) aligned with semantic-tool-use ontology."""
        # Check if schema already exists
        query = f"""
        ASK WHERE {{
            <{IDEA}IdeaPool> a skos:ConceptScheme .
        }}
        """
        if self._store.ask(query):
            logger.debug("Schema already initialized")
            return

        # Add schema triples
        logger.info("Initializing SKOS+DC schema for ideas (aligned with semantic-tool-use)")

        # =================================================================
        # Ontology Declaration
        # =================================================================
        self._store.add_triple(
            f"{IDEA[:-1]}",  # Remove trailing #
            f"{RDF}type",
            f"{OWL}Ontology"
        )
        self._store.add_triple(
            f"{IDEA[:-1]}",
            f"{RDFS}label",
            "Idea Pool Ontology",
            is_literal=True
        )
        self._store.add_triple(
            f"{IDEA[:-1]}",
            f"{RDFS}comment",
            "Extension of semantic-tool-use ontology for idea management",
            is_literal=True
        )
        # Import reference to base ontology
        self._store.add_triple(
            f"{IDEA[:-1]}",
            f"{OWL}imports",
            f"{STU[:-1]}"  # http://semantic-tool-use.org/ontology/tool-use
        )

        # =================================================================
        # idea:Idea class - extends stu:Resource (from tool-use-core.ttl)
        # =================================================================
        self._store.add_triple(
            f"{IDEA}Idea",
            f"{RDF}type",
            f"{OWL}Class"
        )
        self._store.add_triple(
            f"{IDEA}Idea",
            f"{RDFS}subClassOf",
            f"{STU}Resource"  # Aligns with stu:Resource from tool-use-core.ttl
        )
        self._store.add_triple(
            f"{IDEA}Idea",
            f"{RDFS}subClassOf",
            f"{SKOS}Concept"  # Also a SKOS concept for interoperability
        )
        self._store.add_triple(
            f"{IDEA}Idea",
            f"{RDFS}label",
            "Idea",
            is_literal=True,
            lang="en"
        )
        self._store.add_triple(
            f"{IDEA}Idea",
            f"{RDFS}comment",
            "A captured idea in the idea pool, modeled as both stu:Resource and skos:Concept",
            is_literal=True,
            lang="en"
        )

        # idea:Seed subclass
        self._store.add_triple(f"{IDEA}Seed", f"{RDF}type", f"{OWL}Class")
        self._store.add_triple(f"{IDEA}Seed", f"{RDFS}subClassOf", f"{IDEA}Idea")

        # =================================================================
        # Concept Scheme
        # =================================================================
        self._store.add_triple(
            f"{IDEA}IdeaPool",
            f"{RDF}type",
            f"{SKOS}ConceptScheme"
        )
        self._store.add_triple(
            f"{IDEA}IdeaPool",
            f"{RDFS}label",
            "Semantic Tool Use Idea Pool",
            is_literal=True
        )

        # Custom properties (T-Box)
        for prop, label, range_type in [
            ("lifecycle", "Lifecycle state of an idea", f"{XSD}string"),
            ("content", "Full markdown content", f"{XSD}string"),
            ("lifecycleUpdated", "Timestamp of last lifecycle change", f"{XSD}dateTime"),
            ("lifecycleReason", "Reason for lifecycle change", f"{XSD}string"),
            ("capturedAt", "Timestamp when seed was captured", f"{XSD}dateTime"),
            ("embeddingJson", "JSON-serialized embedding vector", f"{XSD}string"),
            ("agent", "AI agent that created or worked on this idea", f"{XSD}string"),
            ("vision", "Vision statement for the idea", f"{XSD}string"),
            ("requirements", "A requirement for implementing the idea", f"{XSD}string"),
            ("considerations", "A consideration, constraint, or trade-off", f"{XSD}string"),
            ("useCases", "A use case or application of the idea", f"{XSD}string"),
        ]:
            self._store.add_triple(f"{IDEA}{prop}", f"{RDF}type", f"{RDF}Property")
            self._store.add_triple(f"{IDEA}{prop}", f"{RDFS}domain", f"{SKOS}Concept")
            self._store.add_triple(f"{IDEA}{prop}", f"{RDFS}range", range_type)
            self._store.add_triple(f"{IDEA}{prop}", f"{RDFS}label", label, is_literal=True)

        # idea:wikidataRef
        self._store.add_triple(f"{IDEA}wikidataRef", f"{RDF}type", f"{RDF}Property")
        self._store.add_triple(f"{IDEA}wikidataRef", f"{RDFS}domain", f"{SKOS}Concept")
        self._store.add_triple(f"{IDEA}wikidataRef", f"{RDFS}comment", "Reference to a Wikidata entity", is_literal=True)

        # Object properties: parent/child, blocks/blockedBy, crystallizedFrom
        for prop in ["parent", "child", "blocks", "blockedBy", "crystallizedFrom"]:
            self._store.add_triple(f"{IDEA}{prop}", f"{RDF}type", f"{RDF}Property")

        self._store.flush()

    def create_idea(self, idea: Idea) -> str:
        """
        Create a new idea in the store.

        Args:
            idea: The idea to create

        Returns:
            The idea URI
        """
        uri = idea.uri

        # Check if idea already exists
        if self.get_idea(idea.id):
            raise ValueError(f"Idea {idea.id} already exists")

        # Type as idea:Idea (which is subClassOf stu:Resource and skos:Concept)
        self._store.add_triple(uri, f"{RDF}type", f"{IDEA}Idea")
        # Also explicitly type as skos:Concept for SKOS tooling compatibility
        self._store.add_triple(uri, f"{RDF}type", f"{SKOS}Concept")

        # If it's a seed, also type as idea:Seed
        if idea.is_seed:
            self._store.add_triple(uri, f"{RDF}type", f"{IDEA}Seed")

        self._store.add_triple(uri, f"{SKOS}inScheme", f"{IDEA}IdeaPool")
        self._store.add_triple(uri, f"{SKOS}prefLabel", idea.title, is_literal=True)

        # Dublin Core metadata
        if idea.description:
            self._store.add_triple(uri, f"{DCTERMS}description", idea.description, is_literal=True)
        self._store.add_triple(uri, f"{DCTERMS}creator", idea.author, is_literal=True)
        self._store.add_triple(
            uri, f"{DCTERMS}created",
            idea.created.isoformat(),
            datatype=f"{XSD}dateTime"
        )

        # Custom properties
        self._store.add_triple(uri, f"{IDEA}lifecycle", idea.lifecycle, is_literal=True)

        if idea.content:
            self._store.add_triple(uri, f"{IDEA}content", idea.content, is_literal=True)

        if idea.agent:
            self._store.add_triple(uri, f"{IDEA}agent", idea.agent, is_literal=True)

        if idea.lifecycle_updated:
            self._store.add_triple(
                uri, f"{IDEA}lifecycleUpdated",
                idea.lifecycle_updated.isoformat(),
                datatype=f"{XSD}dateTime"
            )

        if idea.lifecycle_reason:
            self._store.add_triple(uri, f"{IDEA}lifecycleReason", idea.lifecycle_reason, is_literal=True)

        if idea.captured_at:
            self._store.add_triple(
                uri, f"{IDEA}capturedAt",
                idea.captured_at.isoformat(),
                datatype=f"{XSD}dateTime"
            )

        if idea.crystallized_from:
            self._store.add_triple(uri, f"{IDEA}crystallizedFrom", f"{IDEAS}{idea.crystallized_from}")

        if idea.priority is not None:
            self._store.add_triple(
                uri, f"{IDEA}priority",
                str(idea.priority),
                datatype=f"{XSD}integer"
            )

        if idea.embedding:
            self._store.add_triple(uri, f"{IDEA}embeddingJson", json.dumps(idea.embedding), is_literal=True)

        # Tags as dcterms:subject pointing to tag concepts
        for tag in idea.tags:
            tag_uri = f"{IDEA}tag/{tag}"
            self._store.add_triple(uri, f"{DCTERMS}subject", tag_uri)
            # Ensure tag concept exists
            self._store.add_triple(tag_uri, f"{RDF}type", f"{SKOS}Concept")
            self._store.add_triple(tag_uri, f"{SKOS}prefLabel", tag, is_literal=True)

        # Related ideas
        for related_id in idea.related:
            self._store.add_triple(uri, f"{SKOS}related", f"{IDEAS}{related_id}")

        # Wikidata references
        for wd_ref in idea.wikidata_refs:
            self._store.add_triple(uri, f"{IDEA}wikidataRef", f"{WD}{wd_ref}")

        # Parent-child relationships
        if idea.parent:
            self._store.add_triple(uri, f"{IDEA}parent", f"{IDEAS}{idea.parent}")
            self._store.add_triple(f"{IDEAS}{idea.parent}", f"{IDEA}child", uri)

        for child_id in idea.children:
            self._store.add_triple(uri, f"{IDEA}child", f"{IDEAS}{child_id}")

        # Dependency relationships
        for blocked_id in idea.blocks:
            self._store.add_triple(uri, f"{IDEA}blocks", f"{IDEAS}{blocked_id}")
        for blocker_id in idea.blocked_by:
            self._store.add_triple(uri, f"{IDEA}blockedBy", f"{IDEAS}{blocker_id}")

        # PRD custom properties (RQ3: 5 custom properties)
        if idea.vision:
            self._store.add_triple(uri, f"{IDEA}vision", idea.vision, is_literal=True)

        for req in idea.requirements:
            self._store.add_triple(uri, f"{IDEA}requirements", req, is_literal=True)

        for consideration in idea.considerations:
            self._store.add_triple(uri, f"{IDEA}considerations", consideration, is_literal=True)

        for use_case in idea.use_cases:
            self._store.add_triple(uri, f"{IDEA}useCases", use_case, is_literal=True)

        self._store.flush()
        logger.info(f"Created idea: {idea.id}")
        return uri

    def get_idea(self, idea_id: str) -> Idea | None:
        """
        Get an idea by ID.

        Args:
            idea_id: The idea ID (e.g., "idea-1")

        Returns:
            The Idea object or None if not found
        """
        uri = f"{IDEAS}{idea_id}"

        query = f"""
        SELECT ?title ?description ?content ?author ?agent ?created ?lifecycle
               ?lifecycleUpdated ?lifecycleReason ?parent ?capturedAt
               ?crystallizedFrom ?priority ?embeddingJson
        WHERE {{
            <{uri}> a skos:Concept ;
                    skos:prefLabel ?title .
            OPTIONAL {{ <{uri}> dcterms:description ?description }}
            OPTIONAL {{ <{uri}> idea:content ?content }}
            OPTIONAL {{ <{uri}> dcterms:creator ?author }}
            OPTIONAL {{ <{uri}> idea:agent ?agent }}
            OPTIONAL {{ <{uri}> dcterms:created ?created }}
            OPTIONAL {{ <{uri}> idea:lifecycle ?lifecycle }}
            OPTIONAL {{ <{uri}> idea:lifecycleUpdated ?lifecycleUpdated }}
            OPTIONAL {{ <{uri}> idea:lifecycleReason ?lifecycleReason }}
            OPTIONAL {{ <{uri}> idea:parent ?parent }}
            OPTIONAL {{ <{uri}> idea:capturedAt ?capturedAt }}
            OPTIONAL {{ <{uri}> idea:crystallizedFrom ?crystallizedFrom }}
            OPTIONAL {{ <{uri}> idea:priority ?priority }}
            OPTIONAL {{ <{uri}> idea:embeddingJson ?embeddingJson }}
        }}
        """

        results = self._store.query(query)
        if not results.bindings:
            return None

        row = results.bindings[0]

        # Check if it's a seed
        is_seed_query = f"ASK WHERE {{ <{uri}> a <{IDEA}Seed> }}"
        is_seed = self._store.ask(is_seed_query)

        # Get tags
        tags_query = f"""
        SELECT ?tag WHERE {{
            <{uri}> dcterms:subject ?tagUri .
            ?tagUri skos:prefLabel ?tag .
        }}
        """
        tags = [r["tag"] for r in self._store.query(tags_query)]

        # Get related ideas
        related_query = f"""
        SELECT ?relatedId WHERE {{
            <{uri}> skos:related ?related .
            BIND(REPLACE(STR(?related), "{IDEAS}", "") AS ?relatedId)
        }}
        """
        related = [r["relatedId"] for r in self._store.query(related_query)]

        # Get Wikidata refs
        wd_query = f"""
        SELECT ?qid WHERE {{
            <{uri}> idea:wikidataRef ?wd .
            BIND(REPLACE(STR(?wd), "{WD}", "") AS ?qid)
        }}
        """
        wikidata_refs = [r["qid"] for r in self._store.query(wd_query)]

        # Get children
        children_query = f"""
        SELECT ?childId WHERE {{
            <{uri}> idea:child ?child .
            BIND(REPLACE(STR(?child), "{IDEAS}", "") AS ?childId)
        }}
        """
        children = [r["childId"] for r in self._store.query(children_query)]

        # Get blocks
        blocks_query = f"""
        SELECT ?blockedId WHERE {{
            <{uri}> idea:blocks ?blocked .
            BIND(REPLACE(STR(?blocked), "{IDEAS}", "") AS ?blockedId)
        }}
        """
        blocks = [r["blockedId"] for r in self._store.query(blocks_query)]

        # Get blocked_by
        blocked_by_query = f"""
        SELECT ?blockerId WHERE {{
            <{uri}> idea:blockedBy ?blocker .
            BIND(REPLACE(STR(?blocker), "{IDEAS}", "") AS ?blockerId)
        }}
        """
        blocked_by = [r["blockerId"] for r in self._store.query(blocked_by_query)]

        # Get PRD custom properties
        vision_query = f"SELECT ?vision WHERE {{ <{uri}> idea:vision ?vision }}"
        vision_results = self._store.query(vision_query)
        vision = vision_results.bindings[0].get("vision") if vision_results.bindings else None

        requirements_query = f"SELECT ?req WHERE {{ <{uri}> idea:requirements ?req }}"
        requirements = [r["req"] for r in self._store.query(requirements_query) if r.get("req")]

        considerations_query = f"SELECT ?c WHERE {{ <{uri}> idea:considerations ?c }}"
        considerations = [r["c"] for r in self._store.query(considerations_query) if r.get("c")]

        use_cases_query = f"SELECT ?uc WHERE {{ <{uri}> idea:useCases ?uc }}"
        use_cases = [r["uc"] for r in self._store.query(use_cases_query) if r.get("uc")]

        # Parse dates
        created = datetime.now(timezone.utc)
        if row.get("created"):
            try:
                created = datetime.fromisoformat(row["created"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        lifecycle_updated = None
        if row.get("lifecycleUpdated"):
            try:
                lifecycle_updated = datetime.fromisoformat(row["lifecycleUpdated"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        captured_at = None
        if row.get("capturedAt"):
            try:
                captured_at = datetime.fromisoformat(row["capturedAt"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        # Parse parent
        parent = None
        if row.get("parent"):
            parent = row["parent"].replace(IDEAS, "")

        # Parse crystallizedFrom
        crystallized_from = None
        if row.get("crystallizedFrom"):
            crystallized_from = row["crystallizedFrom"].replace(IDEAS, "")

        # Parse priority
        priority = None
        if row.get("priority") is not None:
            try:
                priority = int(row["priority"])
            except (ValueError, TypeError):
                pass

        # Parse embedding
        embedding = []
        if row.get("embeddingJson"):
            try:
                embedding = json.loads(row["embeddingJson"])
            except (json.JSONDecodeError, TypeError):
                pass

        return Idea(
            id=idea_id,
            title=row.get("title", ""),
            description=row.get("description", ""),
            content=row.get("content", ""),
            author=row.get("author", "unknown"),
            agent=row.get("agent"),
            created=created,
            lifecycle=row.get("lifecycle", "seed"),
            lifecycle_updated=lifecycle_updated,
            lifecycle_reason=row.get("lifecycleReason", ""),
            tags=tags,
            related=related,
            wikidata_refs=wikidata_refs,
            parent=parent,
            children=children,
            blocks=blocks,
            blocked_by=blocked_by,
            is_seed=is_seed,
            captured_at=captured_at,
            crystallized_from=crystallized_from,
            embedding=embedding,
            priority=priority,
            vision=vision,
            requirements=requirements,
            considerations=considerations,
            use_cases=use_cases,
        )

    def update_idea(self, idea: Idea) -> None:
        """
        Update an existing idea.

        Args:
            idea: The idea with updated values
        """
        uri = idea.uri

        # Check if idea exists
        if not self.get_idea(idea.id):
            raise ValueError(f"Idea {idea.id} does not exist")

        # Remove old data (keeping rdf:type and skos:inScheme)
        for pred in [
            f"{SKOS}prefLabel", f"{DCTERMS}description", f"{DCTERMS}creator",
            f"{DCTERMS}created", f"{IDEA}lifecycle", f"{IDEA}agent",
            f"{DCTERMS}subject", f"{SKOS}related", f"{IDEA}wikidataRef",
            f"{IDEA}parent", f"{IDEA}child",
            f"{IDEA}content", f"{IDEA}lifecycleUpdated", f"{IDEA}lifecycleReason",
            f"{IDEA}capturedAt", f"{IDEA}crystallizedFrom", f"{IDEA}priority",
            f"{IDEA}embeddingJson",
            f"{IDEA}blocks", f"{IDEA}blockedBy",
            f"{IDEA}vision", f"{IDEA}requirements", f"{IDEA}considerations", f"{IDEA}useCases",
        ]:
            self._store.remove_triple(uri, pred)

        # Add updated data
        self._store.add_triple(uri, f"{SKOS}prefLabel", idea.title, is_literal=True)
        if idea.description:
            self._store.add_triple(uri, f"{DCTERMS}description", idea.description, is_literal=True)
        if idea.content:
            self._store.add_triple(uri, f"{IDEA}content", idea.content, is_literal=True)
        self._store.add_triple(uri, f"{DCTERMS}creator", idea.author, is_literal=True)
        self._store.add_triple(
            uri, f"{DCTERMS}created",
            idea.created.isoformat(),
            datatype=f"{XSD}dateTime"
        )
        self._store.add_triple(uri, f"{IDEA}lifecycle", idea.lifecycle, is_literal=True)

        if idea.agent:
            self._store.add_triple(uri, f"{IDEA}agent", idea.agent, is_literal=True)

        if idea.lifecycle_updated:
            self._store.add_triple(
                uri, f"{IDEA}lifecycleUpdated",
                idea.lifecycle_updated.isoformat(),
                datatype=f"{XSD}dateTime"
            )

        if idea.lifecycle_reason:
            self._store.add_triple(uri, f"{IDEA}lifecycleReason", idea.lifecycle_reason, is_literal=True)

        if idea.captured_at:
            self._store.add_triple(
                uri, f"{IDEA}capturedAt",
                idea.captured_at.isoformat(),
                datatype=f"{XSD}dateTime"
            )

        if idea.crystallized_from:
            self._store.add_triple(uri, f"{IDEA}crystallizedFrom", f"{IDEAS}{idea.crystallized_from}")

        if idea.priority is not None:
            self._store.add_triple(uri, f"{IDEA}priority", str(idea.priority), datatype=f"{XSD}integer")

        if idea.embedding:
            self._store.add_triple(uri, f"{IDEA}embeddingJson", json.dumps(idea.embedding), is_literal=True)

        # Handle seed type
        if idea.is_seed:
            # Ensure seed type exists
            seed_check = f"ASK WHERE {{ <{uri}> a <{IDEA}Seed> }}"
            if not self._store.ask(seed_check):
                self._store.add_triple(uri, f"{RDF}type", f"{IDEA}Seed")

        for tag in idea.tags:
            tag_uri = f"{IDEA}tag/{tag}"
            self._store.add_triple(uri, f"{DCTERMS}subject", tag_uri)
            self._store.add_triple(tag_uri, f"{RDF}type", f"{SKOS}Concept")
            self._store.add_triple(tag_uri, f"{SKOS}prefLabel", tag, is_literal=True)

        for related_id in idea.related:
            self._store.add_triple(uri, f"{SKOS}related", f"{IDEAS}{related_id}")

        for wd_ref in idea.wikidata_refs:
            self._store.add_triple(uri, f"{IDEA}wikidataRef", f"{WD}{wd_ref}")

        if idea.parent:
            self._store.add_triple(uri, f"{IDEA}parent", f"{IDEAS}{idea.parent}")

        for child_id in idea.children:
            self._store.add_triple(uri, f"{IDEA}child", f"{IDEAS}{child_id}")

        for blocked_id in idea.blocks:
            self._store.add_triple(uri, f"{IDEA}blocks", f"{IDEAS}{blocked_id}")
        for blocker_id in idea.blocked_by:
            self._store.add_triple(uri, f"{IDEA}blockedBy", f"{IDEAS}{blocker_id}")

        # PRD custom properties
        if idea.vision:
            self._store.add_triple(uri, f"{IDEA}vision", idea.vision, is_literal=True)

        for req in idea.requirements:
            self._store.add_triple(uri, f"{IDEA}requirements", req, is_literal=True)

        for consideration in idea.considerations:
            self._store.add_triple(uri, f"{IDEA}considerations", consideration, is_literal=True)

        for use_case in idea.use_cases:
            self._store.add_triple(uri, f"{IDEA}useCases", use_case, is_literal=True)

        self._store.flush()
        logger.info(f"Updated idea: {idea.id}")

    def delete_idea(self, idea_id: str) -> bool:
        """
        Delete an idea from the store.

        Args:
            idea_id: The idea ID to delete

        Returns:
            True if deleted, False if not found
        """
        uri = f"{IDEAS}{idea_id}"

        # Check if exists
        if not self.get_idea(idea_id):
            return False

        # Remove all triples about this idea
        self._store.remove_triple(uri)

        # Also remove any triples pointing to this idea
        self._store.remove_triple(obj=uri)

        self._store.flush()
        logger.info(f"Deleted idea: {idea_id}")
        return True

    def append_to_idea(self, idea_id: str, content: str) -> bool:
        """
        Append content to an existing idea's content field.

        Args:
            idea_id: The idea ID
            content: Content to append

        Returns:
            True if successful
        """
        idea = self.get_idea(idea_id)
        if not idea:
            return False

        existing = idea.content or ""
        idea.content = existing + "\n\n" + content if existing else content
        self.update_idea(idea)
        return True

    def get_next_id(self) -> str:
        """Get the next available idea ID."""
        existing = self.list_ideas(limit=10000)
        max_num = 0
        for i in existing:
            match = re.match(r"idea-(\d+)", i["id"])
            if match:
                max_num = max(max_num, int(match.group(1)))
        return f"idea-{max_num + 1}"

    def list_ideas(
        self,
        lifecycle: str | None = None,
        author: str | None = None,
        tag: str | None = None,
        limit: int = 100,
        offset: int = 0
    ) -> list[dict[str, Any]]:
        """
        List ideas with optional filters.

        Args:
            lifecycle: Filter by lifecycle state
            author: Filter by author
            tag: Filter by tag
            limit: Maximum results
            offset: Result offset for pagination

        Returns:
            List of idea summaries
        """
        filters = []
        if lifecycle:
            filters.append(f'FILTER(?lifecycle = "{lifecycle}")')
        if author:
            filters.append(f'FILTER(?author = "{author}")')
        if tag:
            filters.append(f'?idea dcterms:subject <{IDEA}tag/{tag}> .')

        filter_clause = "\n".join(filters)

        query = f"""
        SELECT DISTINCT ?idea ?title ?lifecycle ?author ?created
        WHERE {{
            ?idea a skos:Concept ;
                  skos:inScheme <{IDEA}IdeaPool> ;
                  skos:prefLabel ?title .
            OPTIONAL {{ ?idea idea:lifecycle ?lifecycle }}
            OPTIONAL {{ ?idea dcterms:creator ?author }}
            OPTIONAL {{ ?idea dcterms:created ?created }}
            {filter_clause}
        }}
        ORDER BY DESC(?created)
        LIMIT {limit}
        OFFSET {offset}
        """

        results = self._store.query(query)
        return [
            {
                "id": r["idea"].replace(IDEAS, ""),
                "title": r.get("title", ""),
                "lifecycle": r.get("lifecycle", "seed"),
                "author": r.get("author", "unknown"),
                "created": r.get("created"),
            }
            for r in results
        ]

    def search_ideas(self, term: str, limit: int = 50) -> list[dict[str, Any]]:
        """
        Search ideas by text in title, description, or content.

        Args:
            term: Search term
            limit: Maximum results

        Returns:
            List of matching ideas
        """
        # Escape special characters in search term
        term = term.lower().replace('"', '\\"')

        query = f"""
        SELECT DISTINCT ?idea ?title ?description ?lifecycle
        WHERE {{
            ?idea a skos:Concept ;
                  skos:inScheme <{IDEA}IdeaPool> ;
                  skos:prefLabel ?title .
            OPTIONAL {{ ?idea dcterms:description ?description }}
            OPTIONAL {{ ?idea idea:content ?content }}
            OPTIONAL {{ ?idea idea:lifecycle ?lifecycle }}
            FILTER(
                CONTAINS(LCASE(?title), "{term}") ||
                CONTAINS(LCASE(COALESCE(?description, "")), "{term}") ||
                CONTAINS(LCASE(COALESCE(?content, "")), "{term}")
            )
        }}
        LIMIT {limit}
        """

        results = self._store.query(query)
        return [
            {
                "id": r["idea"].replace(IDEAS, ""),
                "title": r.get("title", ""),
                "description": r.get("description", ""),
                "lifecycle": r.get("lifecycle", "seed"),
            }
            for r in results
        ]

    def get_ideas_by_lifecycle(self, lifecycle: str) -> list[dict[str, Any]]:
        """Get all ideas in a specific lifecycle state."""
        return self.list_ideas(lifecycle=lifecycle, limit=1000)

    def get_related_ideas(self, idea_id: str) -> list[dict[str, Any]]:
        """Get ideas related to the given idea."""
        uri = f"{IDEAS}{idea_id}"

        query = f"""
        SELECT ?related ?title ?lifecycle
        WHERE {{
            {{ <{uri}> skos:related ?related }}
            UNION
            {{ ?related skos:related <{uri}> }}
            ?related skos:prefLabel ?title .
            OPTIONAL {{ ?related idea:lifecycle ?lifecycle }}
        }}
        """

        results = self._store.query(query)
        return [
            {
                "id": r["related"].replace(IDEAS, ""),
                "title": r.get("title", ""),
                "lifecycle": r.get("lifecycle", "seed"),
            }
            for r in results
        ]

    def get_ideas_by_wikidata(self, qid: str) -> list[dict[str, Any]]:
        """Get ideas referencing a Wikidata entity."""
        query = f"""
        SELECT ?idea ?title ?lifecycle
        WHERE {{
            ?idea a skos:Concept ;
                  skos:prefLabel ?title ;
                  idea:wikidataRef <{WD}{qid}> .
            OPTIONAL {{ ?idea idea:lifecycle ?lifecycle }}
        }}
        """

        results = self._store.query(query)
        return [
            {
                "id": r["idea"].replace(IDEAS, ""),
                "title": r.get("title", ""),
                "lifecycle": r.get("lifecycle", "seed"),
            }
            for r in results
        ]

    def count_ideas(self, lifecycle: str | None = None) -> int:
        """Count ideas, optionally filtered by lifecycle."""
        filter_clause = f'FILTER(?lifecycle = "{lifecycle}")' if lifecycle else ""

        query = f"""
        SELECT (COUNT(DISTINCT ?idea) as ?count)
        WHERE {{
            ?idea a skos:Concept ;
                  skos:inScheme <{IDEA}IdeaPool> .
            OPTIONAL {{ ?idea idea:lifecycle ?lifecycle }}
            {filter_clause}
        }}
        """

        results = self._store.query(query)
        if results.bindings:
            return int(results.bindings[0].get("count", 0))
        return 0

    def get_all_tags(self) -> list[dict[str, Any]]:
        """Get all tags with usage counts."""
        query = f"""
        SELECT ?tag (COUNT(?idea) as ?count)
        WHERE {{
            ?idea dcterms:subject ?tagUri .
            ?tagUri skos:prefLabel ?tag .
        }}
        GROUP BY ?tag
        ORDER BY DESC(?count)
        """

        results = self._store.query(query)
        return [
            {"tag": r["tag"], "count": int(r["count"])}
            for r in results
        ]
