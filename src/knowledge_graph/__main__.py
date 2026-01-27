"""Entry point for the Knowledge Graph MCP Server (standalone).

Run with: python -m knowledge_graph

For integrated use with ontology-server, use:
    python -m ontology_server --enable-abox
"""

from .mcp_server import main

if __name__ == "__main__":
    main()
