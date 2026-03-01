# Semantic Tool Use

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

Ontology server and knowledge graph backend for semantic AI tool orchestration. Provides MCP (Model Context Protocol) and REST APIs for ontology management, SHACL validation, idea lifecycle tracking, and agent memory.

## Quick Start

```bash
# Install dependencies
uv sync --all-extras

# Run the server
./start-ontology-server.sh

# Or directly
python -m ontology_server --http --port 8100 --enable-abox
```

The server is available at `http://localhost:8100` with:
- REST API for ontology queries and knowledge graph operations
- MCP endpoint at `/sse` for Claude Code integration
- Dashboard at `/dashboard`

## Installation

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### From source

```bash
git clone https://github.com/hpz/semantic-tool-use.git
cd semantic-tool-use
uv sync --all-extras
```

### As a service

```bash
# Auto-detects macOS (launchd) or Linux (systemd)
./service/install.sh

# With custom options
./service/install.sh --port 9000 --auth --ontology-path /path/to/ontologies
```

### Docker

```bash
docker compose up
```

## Project Structure

```
semantic-tool-use/
├── src/
│   ├── ontology_server/      # MCP + REST API server
│   │   ├── api/              # FastAPI routes
│   │   ├── core/             # OntologyStore, SHACL validation
│   │   ├── mcp/              # MCP protocol server
│   │   └── dashboard/        # Web dashboard
│   └── knowledge_graph/      # A-Box: ideas, memory, Wikidata
│       ├── core/             # Store, ideas, memory, lifecycle
│       └── migration.py      # Markdown → RDF migration
├── ontology/
│   └── domain/
│       └── visual-artifacts/ # BFO-aligned ontologies
├── service/                  # Service templates (launchd, systemd)
├── tests/                    # pytest test suite
├── docs/                     # Architecture documentation
└── archive/                  # Historical v1 research prototype
```

## Features

- **Ontology Management**: Load, query (SPARQL), and edit OWL ontologies
- **SHACL Validation**: Validate RDF instances against shape constraints
- **Knowledge Graph**: Ideas with lifecycle tracking, agent memory, Wikidata integration
- **Multi-path Loading**: Load ontologies from multiple directories (e.g., multiple projects)
- **MCP Integration**: Full Model Context Protocol support for AI coding assistants
- **Authentication**: Optional Bearer token auth with auto-generated keys

## Configuration

The server accepts CLI arguments and environment variables (`ONTOLOGY_` prefix):

```bash
python -m ontology_server \
    --http                              # Enable REST API
    --port 8100                         # Server port
    --ontology-path ./ontology/domain/visual-artifacts \
    --ontology-path /other/ontologies   # Multiple paths supported
    --enable-abox                       # Enable knowledge graph
    --kg-persist ~/.semantic-tool-use/kg # Persistent storage
    --enable-llm                        # LLM analysis tools (needs ANTHROPIC_API_KEY)
    --enable-search                     # Semantic search (needs sentence-transformers)
```

## Development

```bash
# Run tests
uv run pytest tests/ -x -q

# Lint
uv run ruff check src/ tests/

# Type check
uv run mypy src/
```

## Archive

The `archive/` directory contains the original v1 research prototype — a neuro-symbolic pipeline for LLM-driven tool orchestration with SHACL-based semantic verification. See [archive/README.md](archive/README.md) for details.

## License

[Apache License 2.0](LICENSE)
