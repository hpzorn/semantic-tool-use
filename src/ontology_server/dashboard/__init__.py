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
