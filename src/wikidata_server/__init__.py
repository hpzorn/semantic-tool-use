"""Standalone Wikidata MCP server.

Extracted from ontology-server per MIGRATION.md so the ontology server stays
focused on the idea/pipeline domain. Mounted by no Tulla pipeline agent and
exposed in no dashboard view — it is an ad-hoc capability surface.

Backed by the same knowledge_graph.core.wikidata.WikidataCache used by the
ontology server, so the on-disk cache graph is shared.
"""

from .server import create_wikidata_server

__all__ = ["create_wikidata_server"]
