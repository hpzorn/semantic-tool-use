# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Ontology server and knowledge graph backend for semantic AI tool orchestration. Provides MCP (Model Context Protocol) and REST APIs for ontology management, SHACL validation, idea lifecycle tracking, and agent memory.

## Common Commands

```bash
# Setup
uv sync --all-extras
source .venv/bin/activate

# Testing
pytest tests/                 # Run all tests
pytest tests/test_store.py    # Run single test file
pytest -k "test_query"        # Run tests matching pattern

# Linting/Formatting
ruff check src/               # Lint check
ruff check --fix src/         # Auto-fix lint issues
mypy src/                     # Type checking

# Ontology Server (development)
python -m ontology_server                     # MCP stdio mode (single session)
python -m ontology_server --http              # REST API + MCP SSE mode
python -m ontology_server --enable-abox       # Enable knowledge graph (A-Box) tools

# Development launcher
./start-ontology-server.sh                    # Foreground with all features
./start-ontology-server.sh --background       # Background with PID file
./start-ontology-server.sh --stop             # Stop background server

# Service management (production)
./service/install.sh                          # Auto-detect OS, install as service
./service/install.sh --dry-run                # Preview without installing
./service/install.sh --uninstall              # Remove service

# Docker
docker compose up                             # Start server in container
```

## Ontology Server (Production)

The ontology server runs as a shared HTTP service with MCP SSE, allowing multiple Claude sessions to share the same A-Box (knowledge graph) with persistent storage.

**Endpoints:**
- HTTP: `http://localhost:8100`
- MCP SSE: `http://localhost:8100/sse`
- Dashboard: `http://localhost:8100/dashboard`

**Persistence:** `~/.semantic-tool-use/kg` (Oxigraph/RocksDB)

**Management:**
```bash
# View logs
tail -f ~/.semantic-tool-use/ontology-server.error.log

# Manual start (foreground, for debugging)
./start-ontology-server.sh
```

## Architecture

### Ontology Server (`src/ontology_server/`)

MCP-native server providing semantic tools for T-Box (schema) operations:

- **core/store.py**: In-memory RDF store using rdflib. Manages multiple named graphs, supports SPARQL queries across single or all ontologies. Supports multiple `--ontology-path` arguments for loading from several directories.
- **core/validation.py**: SHACL validation using pyshacl. Validates RDF instances against shapes.
- **mcp/server.py**: FastMCP server exposing tools: `list_ontologies`, `get_ontology`, `query_ontology`, `get_classes`, `get_properties`, `add_triple`, `remove_triple`, `update_triple`, `validate_instance`, `search_ontology`, `validate_ontology_quality`, `list_quality_shapes`, `get_quality_summary`.
- **shapes/**: Bundled SHACL shapes for ontology quality validation.
- **api/app.py**: REST API layer (run with `--http` flag).
- **dashboard/**: Web dashboard for browsing ontologies, instances, and ideas.
- **auth.py**: Optional Bearer token authentication (`ONTOLOGY_AUTH_ENABLED=1`).

### Knowledge Graph Backend (`src/knowledge_graph/`)

Unified Oxigraph-based A-Box (instance) store. Integrated with ontology-server via `--enable-abox` flag.

- **core/store.py**: Oxigraph wrapper with named graph support, SPARQL queries
- **core/ideas.py**: Ideas as SKOS+Dublin Core instances
- **core/memory.py**: Agent memory using reified statement pattern
- **core/wikidata.py**: Wikidata entity cache for factual grounding
- **core/lifecycle.py**: Idea lifecycle state machine (seed → backlog → researching → implementing → completed)
- **mcp_server.py**: Standalone MCP server (or use integrated via ontology-server)

Additional MCP tools when `--enable-abox` is enabled:
- Ideas: `query_ideas`, `get_idea`, `create_idea`, `update_idea`, `set_lifecycle`
- Memory: `store_fact`, `recall_facts`, `forget_fact`
- Wikidata: `lookup_wikidata` (by QID), `query_wikidata` (SPARQL)
- Cross-graph: `sparql_query`, `get_graph_stats`

### Ontologies (`ontology/`)

- **domain/visual-artifacts/**: Visual artifacts ontology (presentations, social media, diagrams)
- **domain/idea-pool/**: Ideas ontology with SHACL shapes (for knowledge graph)

### RDF Namespaces

```python
# Visual Artifacts Ontology
VAO = "http://semantic-tool-use.org/ontology/visual-artifacts#"
PRES = "http://semantic-tool-use.org/ontology/visual-artifacts/presentation#"
SOCIAL = "http://semantic-tool-use.org/ontology/visual-artifacts/social#"
DIAG = "http://semantic-tool-use.org/ontology/visual-artifacts/diagram#"

# Idea Pool (Knowledge Graph A-Box)
IDEA = "http://semantic-tool-use.org/ontology/idea-pool#"
IDEAS = "http://semantic-tool-use.org/ideas/"  # Instance namespace
```

## Test Patterns

Tests use pytest fixtures defined in `tests/conftest.py`:
- `store`: Pre-loaded OntologyStore with sample ontology
- `empty_store`: Fresh OntologyStore
- `validator`: SHACLValidator instance
- `sample_ttl`: Sample ontology as string
- `fixtures_path`: Path to `tests/fixtures/`

Test locations:
- `tests/`: Main test suite (API, dashboard, store, validation, auth, MCP)
- `src/knowledge_graph/tests/`: Knowledge graph unit tests

## Configuration

Server settings via `src/ontology_server/config.py` using pydantic-settings. Environment variables use `ONTOLOGY_` prefix:
- `ONTOLOGY_ONTOLOGY_PATH`: Directory with .ttl files
- `ONTOLOGY_SHAPES_PATH`: Directory with SHACL shapes
- `ONTOLOGY_HOST`/`ONTOLOGY_PORT`: For HTTP mode
- `ONTOLOGY_AUTH_ENABLED`: Set to `1` to require Bearer token

## Wikidata Integration

The `query_wikidata` tool executes SPARQL against `query.wikidata.org` for discovering entities. Common prefixes are auto-added.

**Common Wikidata properties:**
- `wdt:P31` - instance of (type)
- `wdt:P17` - country
- `wdt:P625` - coordinate location
- `wdt:P1082` - population

Discovered entities are automatically cached in the local knowledge graph for fast re-lookup.
