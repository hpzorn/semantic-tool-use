"""
Knowledge Graph Backend for Ontology Server

A unified Oxigraph-based knowledge graph that provides:
- Ideas as RDF instances (A-Box) using SKOS+Dublin Core
- Agent memory with reified statement pattern
- Wikidata entity cache for factual grounding
- Single SPARQL endpoint for all queries

Architecture:
- Default graph: Ideas (SKOS:Concept)
- Named graph <memory:agent>: Agent memory (reified facts)
- Named graph <wikidata:cache>: Wikidata labels/descriptions
"""

from .core.store import KnowledgeGraphStore
from .core.ideas import IdeasStore
from .core.memory import AgentMemory
from .core.wikidata import WikidataCache
from .core.lifecycle import LifecycleManager
from .core.seeds import SeedStore

__version__ = "0.2.0"
__all__ = [
    "KnowledgeGraphStore",
    "IdeasStore",
    "AgentMemory",
    "WikidataCache",
    "LifecycleManager",
    "SeedStore",
]
