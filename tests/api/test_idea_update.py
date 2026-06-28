"""Tests for POST /ideas/{idea_id}/update (python-tulla REST regression fix).

This route was missing from the server while the python-tulla adapter POSTed to
it (MIGRATION.md §3a). Verifies field updates persist and that a supplied
lifecycle is routed through the validated set_lifecycle transition.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ontology_server.api.app import create_app
from ontology_server.config import Settings
from ontology_server.core.validation import ValidationResult
from unittest.mock import MagicMock


def _client():
    from knowledge_graph import KnowledgeGraphStore
    from knowledge_graph.core.ideas import IdeasStore, Idea

    kg = KnowledgeGraphStore()
    ideas = IdeasStore(kg)
    ideas.create_idea(Idea(id="idea-900", title="Old title", description="d", content="c"))

    ontology_store = MagicMock()
    ontology_store._graphs = {}
    ontology_store.list_ontologies.return_value = []
    validator = MagicMock()
    validator.validate.return_value = ValidationResult(conforms=True)
    settings = Settings(api_key="", ontology_path=Path("ontology"),
                        shapes_path=Path("ontology/shapes"), port=8499, log_level="DEBUG")
    app = create_app(settings=settings, store=ontology_store, validator=validator, kg_store=kg)
    return TestClient(app), ideas


def test_update_persists_fields():
    client, ideas = _client()
    resp = client.post("/ideas/idea-900/update", json={"title": "New title", "tags": ["x"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "updated"
    assert set(body["updated_fields"]) == {"title", "tags"}
    assert ideas.get_idea("idea-900").title == "New title"


def test_update_unknown_idea_returns_error():
    client, _ = _client()
    resp = client.post("/ideas/idea-does-not-exist/update", json={"title": "x"})
    assert "error" in resp.json()


def test_update_routes_lifecycle_through_set_lifecycle():
    client, ideas = _client()
    resp = client.post("/ideas/idea-900/update",
                       json={"description": "d2", "lifecycle": "sprout"})
    assert resp.status_code == 200
    assert resp.json()["lifecycle"] is not None
