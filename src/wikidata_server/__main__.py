"""Run the standalone Wikidata MCP server over stdio/SSE."""

from __future__ import annotations

import os

from knowledge_graph import KnowledgeGraphStore

from .server import create_wikidata_server


def main() -> None:
    persist = os.environ.get("WIKIDATA_KG_PATH") or os.environ.get("KG_PERSIST_PATH")
    kg_store = KnowledgeGraphStore(persist_path=persist)
    server = create_wikidata_server(
        kg_store,
        api_key=os.environ.get("WIKIDATA_API_KEY") or os.environ.get("ONTOLOGY_API_KEY"),
        host=os.environ.get("WIKIDATA_HOST", "localhost"),
        port=int(os.environ.get("WIKIDATA_PORT", "8200")),
    )
    server.run()


if __name__ == "__main__":
    main()
