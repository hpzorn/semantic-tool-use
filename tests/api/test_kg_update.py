"""Tests for the POST /kg/update endpoint.

Covers:
1. Successful SPARQL UPDATE execution returns {"success": true, "query": ...}
2. Invalid SPARQL (exception from kg_store.update()) returns an error dict
3. The endpoint calls kg_store.update() with the provided query string
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from ontology_server.api.app import create_app
from ontology_server.config import Settings
from ontology_server.core.validation import ValidationResult


def _make_settings() -> Settings:
    """Create test settings with auth disabled."""
    return Settings(
        api_key="",
        ontology_path=Path("ontology"),
        shapes_path=Path("ontology/shapes"),
        port=8421,
        log_level="DEBUG",
    )


def _make_client(*, kg_store: MagicMock | None = None) -> TestClient:
    """Create a TestClient with a mocked KG store."""
    ontology_store = MagicMock()
    ontology_store._graphs = {}
    ontology_store.list_ontologies.return_value = []

    validator = MagicMock()
    validator.validate.return_value = ValidationResult(conforms=True)

    settings = _make_settings()
    app = create_app(
        settings=settings,
        store=ontology_store,
        validator=validator,
        kg_store=kg_store,
    )
    return TestClient(app)


class TestKgUpdateSuccess:
    """Successful SPARQL UPDATE execution returns {"success": true}."""

    def test_successful_update_returns_success(self) -> None:
        kg = MagicMock()
        kg.update.return_value = None
        client = _make_client(kg_store=kg)

        resp = client.post("/kg/update", json={"query": "INSERT DATA { <urn:s> <urn:p> <urn:o> . }"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["query"] == "INSERT DATA { <urn:s> <urn:p> <urn:o> . }"

    def test_delete_update_returns_success(self) -> None:
        kg = MagicMock()
        kg.update.return_value = None
        client = _make_client(kg_store=kg)

        sparql = "DELETE WHERE { <urn:s> <urn:p> ?o . }"
        resp = client.post("/kg/update", json={"query": sparql})

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


class TestKgUpdateError:
    """Invalid SPARQL returns an error dict."""

    def test_invalid_sparql_returns_error(self) -> None:
        kg = MagicMock()
        kg.update.side_effect = Exception("Parse error: invalid SPARQL")
        client = _make_client(kg_store=kg)

        resp = client.post("/kg/update", json={"query": "NOT VALID SPARQL"})

        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data
        assert "Parse error" in data["error"]

    def test_runtime_error_returns_error(self) -> None:
        kg = MagicMock()
        kg.update.side_effect = RuntimeError("Graph not found")
        client = _make_client(kg_store=kg)

        resp = client.post("/kg/update", json={"query": "DROP GRAPH <urn:g>"})

        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data
        assert "Graph not found" in data["error"]


class TestKgUpdateDelegation:
    """The endpoint calls kg_store.update() with the provided query string."""

    def test_update_called_with_query(self) -> None:
        kg = MagicMock()
        kg.update.return_value = None
        client = _make_client(kg_store=kg)

        sparql = "INSERT DATA { <urn:x> <urn:y> <urn:z> . }"
        client.post("/kg/update", json={"query": sparql})

        kg.update.assert_called_once_with(sparql)

    def test_empty_query_still_delegates(self) -> None:
        kg = MagicMock()
        kg.update.return_value = None
        client = _make_client(kg_store=kg)

        client.post("/kg/update", json={"query": ""})

        kg.update.assert_called_once_with("")
