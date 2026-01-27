"""Entry point for the Ontology Server.

Run with: python -m ontology_server

The server can operate in multiple modes:
1. MCP stdio mode (default): For Claude Code integration
2. HTTP mode: REST API + MCP SSE (use --http flag)
3. Combined mode: Include A-Box (knowledge graph) tools (use --enable-abox flag)
"""

import argparse
import logging
import sys
from pathlib import Path

from .config import settings, Settings
from .core.store import OntologyStore
from .core.validation import SHACLValidator
from .mcp.server import create_mcp_server


def setup_logging(level: str = "INFO"):
    """Configure logging for the server."""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stderr,  # Log to stderr to keep stdout clean for MCP
    )


def resolve_ontology_path(path: Path) -> Path:
    """Resolve ontology path, checking common locations."""
    if path.exists():
        return path.resolve()

    # Check relative to current directory
    cwd_path = Path.cwd() / path
    if cwd_path.exists():
        return cwd_path.resolve()

    # Check relative to this file's directory (for development)
    dev_path = Path(__file__).parent.parent.parent.parent / "ontology" / "domain" / "visual-artifacts"
    if dev_path.exists():
        return dev_path.resolve()

    # Check common project locations
    project_root = Path(__file__).parent.parent.parent.parent
    candidates = [
        project_root / "ontologies",
        project_root / "ontology" / "domain" / "visual-artifacts",
        Path.home() / ".ontologies",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()

    return path.resolve()  # Return as-is, will warn when loading


def main():
    """Run the Ontology Server."""
    parser = argparse.ArgumentParser(
        description="Ontology Server - MCP and REST API for ontology management"
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Run in HTTP mode (REST API + MCP SSE) instead of MCP stdio"
    )
    parser.add_argument(
        "--host",
        default=settings.host,
        help=f"HTTP host (default: {settings.host})"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=settings.port,
        help=f"HTTP port (default: {settings.port})"
    )
    parser.add_argument(
        "--ontology-path",
        type=Path,
        default=settings.ontology_path,
        help=f"Path to ontology files (default: {settings.ontology_path})"
    )
    parser.add_argument(
        "--shapes-path",
        type=Path,
        default=settings.shapes_path,
        help=f"Path to SHACL shapes (default: {settings.shapes_path})"
    )
    parser.add_argument(
        "--log-level",
        default=settings.log_level,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help=f"Logging level (default: {settings.log_level})"
    )
    parser.add_argument(
        "--enable-abox",
        action="store_true",
        help="Enable A-Box (knowledge graph) tools for ideas, agent memory, and Wikidata"
    )
    parser.add_argument(
        "--kg-persist",
        type=Path,
        default=None,
        help="Path for knowledge graph persistence (default: in-memory)"
    )
    parser.add_argument(
        "--ideas-dir",
        type=Path,
        default=None,
        help="Directory to migrate ideas from on startup (requires --enable-abox)"
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.log_level)
    logger = logging.getLogger(__name__)

    # Create settings with CLI overrides
    cli_settings = Settings(
        ontology_path=args.ontology_path,
        shapes_path=args.shapes_path,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
    )

    # Resolve paths
    ontology_path = resolve_ontology_path(cli_settings.ontology_path)
    shapes_path = resolve_ontology_path(cli_settings.shapes_path)

    logger.info(f"Ontology path: {ontology_path}")
    logger.info(f"Shapes path: {shapes_path}")

    # Initialize store and load ontologies
    store = OntologyStore()

    if ontology_path.exists():
        count = store.load_directory(ontology_path)
        logger.info(f"Loaded {count} ontologies from {ontology_path}")

        # Log loaded ontologies
        for onto in store.list_ontologies():
            logger.debug(f"  - {onto['uri']}: {onto['triple_count']} triples")
    else:
        logger.warning(f"Ontology path does not exist: {ontology_path}")
        logger.warning("Server will start with no ontologies loaded")

    # Initialize validator
    validator = SHACLValidator(shapes_path if shapes_path.exists() else None)

    # Optionally initialize knowledge graph for A-Box functionality
    kg_store = None
    if args.enable_abox:
        try:
            from knowledge_graph import KnowledgeGraphStore

            # Initialize knowledge graph store
            kg_persist = str(args.kg_persist) if args.kg_persist else None
            kg_store = KnowledgeGraphStore(kg_persist)
            logger.info(f"Knowledge graph initialized (persist={kg_persist or 'in-memory'})")

            # Optionally migrate ideas
            if args.ideas_dir and args.ideas_dir.exists():
                from knowledge_graph.migration import migrate_ideas
                logger.info(f"Migrating ideas from {args.ideas_dir}")
                stats = migrate_ideas(args.ideas_dir, kg_store)
                logger.info(f"Migration complete: {stats}")

        except ImportError as e:
            logger.error(f"Failed to enable A-Box: {e}")
            logger.error("Install pyoxigraph: pip install pyoxigraph")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Failed to initialize knowledge graph: {e}")
            sys.exit(1)

    # Create MCP server (with optional knowledge graph integration)
    mcp = create_mcp_server(cli_settings, store, validator, kg_store)

    if args.http:
        # HTTP mode: Run with uvicorn (MCP available via SSE at /sse)
        logger.info(f"Starting HTTP server on {cli_settings.host}:{cli_settings.port}")
        try:
            import uvicorn
            from .api.app import create_app

            app = create_app(cli_settings, store, validator, kg_store)
            uvicorn.run(app, host=cli_settings.host, port=cli_settings.port)
        except ImportError:
            logger.error("HTTP mode requires uvicorn. Install with: pip install uvicorn[standard]")
            sys.exit(1)
    else:
        # MCP stdio mode (default)
        logger.info("Starting MCP server in stdio mode")
        tools = ["list_ontologies", "get_ontology", "query_ontology",
                 "get_classes", "get_properties", "add_triple", "validate_instance", "search_ontology"]
        if kg_store:
            tools.extend(["query_ideas", "get_idea", "create_idea", "update_idea",
                         "store_fact", "recall_facts", "forget_fact",
                         "lookup_wikidata", "query_wikidata", "get_kg_stats"])
        logger.info(f"Tools available: {', '.join(tools)}")
        mcp.run()


if __name__ == "__main__":
    main()
