"""Ontology Dashboard sub-package.

Provides an HTMX-powered web dashboard for browsing ontologies,
ideas, and agent memory.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

if TYPE_CHECKING:
    from knowledge_graph import AgentMemory, IdeasStore, KnowledgeGraphStore
    from ontology_server.core.store import OntologyStore

logger = logging.getLogger(__name__)

_PACKAGE_DIR = Path(__file__).resolve().parent

# Namespace prefix table used by the short_uri Jinja2 filter.
_SHORT_URI_PREFIXES = [
    ("http://tulla.dev/phase#", "phase:"),
    ("http://tulla.dev/prd#", "prd:"),
    ("http://tulla.dev/isaqb#", "isaqb:"),
    ("http://tulla.dev/architecture#", "arch:"),
    ("http://tulla.dev/trace#", "trace:"),
    ("http://www.w3.org/2004/02/skos/core#", "skos:"),
    # Semantic tool-use ontologies
    ("http://semantic-tool-use.org/ontology/tool-use#", "stu:"),
    ("http://semantic-tool-use.org/ontology/visual-artifacts#", "vao:"),
    ("http://semantic-tool-use.org/ontology/idea-pool#", "idea:"),
    ("http://semantic-tool-use.org/ontology/visual-artifacts/presentation#", "pres:"),
    ("http://semantic-tool-use.org/ontology/visual-artifacts/social#", "social:"),
    # Standard W3C and Dublin Core namespaces
    ("http://www.w3.org/2000/01/rdf-schema#", "rdfs:"),
    ("http://www.w3.org/2002/07/owl#", "owl:"),
    ("http://www.w3.org/1999/02/22-rdf-syntax-ns#", "rdf:"),
    ("http://purl.org/dc/terms/", "dcterms:"),
]


def short_uri(uri: str) -> str:
    """Shorten a full URI to ``prefix:local`` form if a known prefix matches."""
    for namespace, prefix in _SHORT_URI_PREFIXES:
        if uri.startswith(namespace):
            return prefix + uri[len(namespace):]
    return uri


def create_dashboard_app(
    ontology_store: "OntologyStore",
    kg_store: "KnowledgeGraphStore",
    agent_memory: "AgentMemory",
    ideas_store: "IdeasStore",
) -> FastAPI:
    """Create the Ontology Dashboard FastAPI sub-application.

    Args:
        ontology_store: T-Box ontology store.
        kg_store: Unified knowledge-graph store (Oxigraph).
        agent_memory: Agent memory (reified facts).
        ideas_store: SKOS+DC ideas store.

    Returns:
        A FastAPI app suitable for mounting on the main server.
    """
    app = FastAPI(title="Ontology Dashboard")

    # -- Stores on app.state ---------------------------------------------------
    app.state.ontology_store = ontology_store
    app.state.kg_store = kg_store
    app.state.agent_memory = agent_memory
    app.state.ideas_store = ideas_store

    # -- Templates -------------------------------------------------------------
    templates_dir = _PACKAGE_DIR / "templates"
    templates_dir.mkdir(exist_ok=True)
    templates = Jinja2Templates(directory=str(templates_dir))

    def dashboard_url(request: Request, name: str, **path_params: str) -> str:
        """Generate a prefix-safe URL for a dashboard route.

        Works regardless of where the dashboard sub-app is mounted
        by using the ASGI root_path that Starlette sets automatically.
        """
        url = request.url_for(name, **path_params)
        return str(url)

    templates.env.globals["dashboard_url"] = dashboard_url
    templates.env.filters["short_uri"] = short_uri

    app.state.templates = templates

    # -- Static files ----------------------------------------------------------
    static_dir = _PACKAGE_DIR / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="dashboard_static")

    # -- Routes ----------------------------------------------------------------
    from .routes import router  # noqa: E402

    app.include_router(router)

    logger.info("Ontology Dashboard sub-application created")
    return app
