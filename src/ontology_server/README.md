# Ontology Server

Unified MCP and REST API server for ontology management.

## Installation

```bash
cd src
pip install -e ".[dev]"
```

## Usage

### MCP Mode (for Claude Code)

```bash
python -m ontology_server --ontology-path ../ontology/domain/visual-artifacts
```

### HTTP Mode (REST API)

```bash
python -m ontology_server --http --ontology-path ../ontology/domain/visual-artifacts
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `list_ontologies` | List all loaded ontologies with metadata |
| `get_ontology` | Get ontology content as Turtle |
| `query_ontology` | Execute SPARQL queries |
| `get_classes` | List all OWL classes |
| `get_properties` | List all OWL properties |
| `add_triple` | Add a triple to an ontology |
| `validate_instance` | Validate RDF against SHACL shapes |
| `search_ontology` | Search by label/comment text |

## Claude Code Configuration

Add to `~/.claude/claude_code_config.json`:

```json
{
  "mcpServers": {
    "ontology": {
      "command": "python3",
      "args": ["-m", "ontology_server", "--ontology-path", "/path/to/ontologies"]
    }
  }
}
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ONTOLOGY_ONTOLOGY_PATH` | `ontologies` | Path to ontology files |
| `ONTOLOGY_SHAPES_PATH` | `ontologies/shapes` | Path to SHACL shapes |
| `ONTOLOGY_PORT` | `8420` | HTTP server port |
| `ONTOLOGY_LOG_LEVEL` | `INFO` | Logging level |

## Testing

```bash
cd ..  # Go to project root
pytest tests/test_store.py tests/test_validation.py tests/test_mcp_tools.py -v
```

## Project Structure

```
ontology_server/
├── __init__.py
├── __main__.py          # Entry point
├── config.py            # Pydantic settings
├── core/
│   ├── store.py         # RDF triplestore
│   └── validation.py    # SHACL validator
├── mcp/
│   └── server.py        # MCP server + tools
└── api/
    └── app.py           # FastAPI app (Phase 3)
```
