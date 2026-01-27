# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Research project investigating whether upper ontologies can serve as an interlingua for LLM-driven tool orchestration with semantic verification. The core hypothesis is that semantic verification using OWL ontologies can catch errors that JSON Schema misses.

## Common Commands

```bash
# Setup
./setup.sh                    # Full setup with reasoners (requires Java 17+)
./setup.sh --minimal          # Python-only setup
source .venv/bin/activate     # Activate virtual environment

# Testing
pytest tests/                 # Run all tests
pytest tests/test_store.py    # Run single test file
pytest -k "test_query"        # Run tests matching pattern
pytest -v                     # Verbose output

# Linting/Formatting
ruff check src/               # Lint check
ruff check --fix src/         # Auto-fix lint issues
black src/ tests/             # Format code
mypy src/                     # Type checking

# Ontology Server (development)
python -m ontology_server                     # MCP stdio mode (single session)
python -m ontology_server --http              # REST API + MCP SSE mode
python -m ontology_server --enable-abox       # Enable knowledge graph (A-Box) tools

# Services
docker-compose up fuseki      # Start SPARQL server at http://localhost:3030
```

## Ontology Server (Production)

The ontology server runs as a shared HTTP service with MCP SSE, allowing multiple Claude sessions to share the same A-Box (knowledge graph) with persistent storage.

**Endpoints:**
- HTTP: `http://localhost:8100`
- MCP SSE: `http://localhost:8100/sse`
- Health: `http://localhost:8100/health`

**Persistence:** `~/.semantic-tool-use/kg` (RocksDB)

**Management:**
```bash
# Check status
curl http://localhost:8100/health

# View logs
tail -f ~/.semantic-tool-use/ontology-server.log

# Restart server
launchctl unload ~/Library/LaunchAgents/org.semantic-tool-use.ontology-server.plist
launchctl load ~/Library/LaunchAgents/org.semantic-tool-use.ontology-server.plist

# Stop server
launchctl unload ~/Library/LaunchAgents/org.semantic-tool-use.ontology-server.plist

# Start server (after stop)
launchctl load ~/Library/LaunchAgents/org.semantic-tool-use.ontology-server.plist

# Manual start (foreground, for debugging)
./start-ontology-server.sh
```

## Architecture

### Ontology Server (`src/ontology_server/`)

MCP-native server providing semantic tools for T-Box (schema) operations:

- **core/store.py**: In-memory RDF store using rdflib. Manages multiple named graphs, supports SPARQL queries across single or all ontologies. Key class: `OntologyStore`.
- **core/validation.py**: SHACL validation using pyshacl. Validates RDF instances against shapes. Key classes: `SHACLValidator`, `ValidationResult`, `Violation`.
- **mcp/server.py**: FastMCP server exposing tools: `list_ontologies`, `get_ontology`, `query_ontology`, `get_classes`, `get_properties`, `add_triple`, `remove_triple`, `update_triple`, `validate_instance`, `search_ontology`, `validate_ontology_quality`, `list_quality_shapes`, `get_quality_summary`.
- **shapes/**: Bundled SHACL shapes for ontology quality validation (`owl-shapes.ttl`, `ontology-metadata-shapes.ttl`).
- **api/app.py**: Optional REST API layer (run with `--http` flag).

### Knowledge Graph Backend (`src/knowledge_graph/`)

Unified Oxigraph-based A-Box (instance) store. Integrated with ontology-server via `--enable-abox` flag.

- **core/store.py**: Oxigraph wrapper with named graph support, SPARQL queries
- **core/ideas.py**: Ideas as SKOS+Dublin Core instances (`idea:Idea rdfs:subClassOf stu:Resource`)
- **core/memory.py**: Agent memory using reified statement pattern
- **core/wikidata.py**: Wikidata entity cache for factual grounding
- **mcp_server.py**: Standalone MCP server (or use integrated via ontology-server)

Additional MCP tools when `--enable-abox` is enabled:
- Ideas: `query_ideas`, `get_idea`, `create_idea`, `update_idea`
- Memory: `store_fact`, `recall_facts`, `forget_fact`
- Wikidata: `lookup_wikidata` (by QID), `query_wikidata` (SPARQL discovery)
- Stats: `get_kg_stats`

### Research Pipeline (planned, see `src/`)

- **registry/**: Semantic tool definitions loader
- **reasoner/**: OWL reasoner integration (HermiT/Pellet)
- **translation/**: LLM to semantic request conversion
- **feedback/**: Convert reasoner violations to actionable feedback
- **pipeline/**: Full orchestration: translate -> verify -> feedback -> retry

### Ontologies (`ontology/`)

- **core/**: Tool-use core ontology aligned with BFO (`tool-use-core.ttl`)
- **imports/**: BFO subset and CCO extensions
- **domain/**: Domain-specific ontologies:
  - `visual-artifacts/`: Presentations, social media, diagrams (primary test domain)
  - `idea-pool/`: Ideas ontology with SHACL shapes (for knowledge graph)
  - `fhir/`: Healthcare tools
  - `iso20022/`: Financial messaging

### RDF Namespaces

```python
# Core Tool-Use Ontology
STU = "http://semantic-tool-use.org/ontology/tool-use#"

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
- `src/ontology_server/tests/`: Unit tests for ontology server
- `src/knowledge_graph/tests/`: Unit tests for knowledge graph
- `tests/`: Integration tests

## Configuration

Server settings via `src/ontology_server/config.py` using pydantic-settings. Environment variables use `ONTOLOGY_` prefix:
- `ONTOLOGY_ONTOLOGY_PATH`: Directory with .ttl files
- `ONTOLOGY_SHAPES_PATH`: Directory with SHACL shapes
- `ONTOLOGY_MCP_NAME`: Server name for MCP
- `ONTOLOGY_HOST`/`ONTOLOGY_PORT`: For HTTP mode

## Wikidata Integration

The `query_wikidata` tool executes SPARQL against `query.wikidata.org` for discovering entities. Common prefixes are auto-added.

**Example queries:**
```sparql
# German cities with population > 100k
SELECT ?city ?cityLabel ?population ?coord WHERE {
    ?city wdt:P31 wd:Q515 .          # instance of city
    ?city wdt:P17 wd:Q183 .          # country: Germany
    ?city wdt:P1082 ?population .    # population
    ?city wdt:P625 ?coord .          # coordinates
    FILTER(?population > 100000)
    SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
}
ORDER BY DESC(?population) LIMIT 20

# Rivers in France with length
SELECT ?river ?riverLabel ?length WHERE {
    ?river wdt:P31 wd:Q4022 .        # instance of river
    ?river wdt:P17 wd:Q142 .         # country: France
    OPTIONAL { ?river wdt:P2043 ?length }
    SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
}
LIMIT 50
```

**Common Wikidata properties:**
- `wdt:P31` - instance of (type)
- `wdt:P17` - country
- `wdt:P625` - coordinate location
- `wdt:P1082` - population
- `wdt:P2043` - length
- `wdt:P2046` - area
- `wdt:P36` - capital
- `wdt:P131` - located in administrative entity

Discovered entities are automatically cached in the local knowledge graph for fast re-lookup.

## Research Tracking

See `RESEARCH_PLAN.md` for 38 tasks across 6 workstreams with YAML task definitions and dependency graph.
