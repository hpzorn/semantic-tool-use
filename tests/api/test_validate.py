"""Regression tests for the POST /validate endpoint.

The /validate endpoint lives on the main FastAPI app (not the dashboard sub-app).
Tests create a client from create_app() with mocked OntologyStore, KnowledgeGraphStore,
and SHACLValidator.

Covers:
1. Instance found in KG phases graph via ask() → successful validation
2. Instance not found in any store → "No triples found" violation
3. Prefix-compacted URI still found by SPARQL ASK
4. Fallback to T-Box OntologyStore when KG ask() returns False
5. Missing instance_uri or shape_uri returns an error response
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from ontology_server.api.app import create_app
from ontology_server.config import Settings
from ontology_server.core.validation import ValidationResult, Violation


GRAPH_PHASES = "http://semantic-tool-use.org/graphs/phases"

SAMPLE_INSTANCE_TTL = """\
@prefix ex: <http://example.org/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

ex:MyInstance a ex:Thing ;
    rdfs:label "Test instance" .
"""

SAMPLE_SHAPES_TTL = """\
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ex: <http://example.org/> .

ex:ThingShape a sh:NodeShape ;
    sh:targetClass ex:Thing .
"""


def _make_settings() -> Settings:
    """Create test settings with auth disabled."""
    return Settings(
        api_key="",
        ontology_path=Path("ontology"),
        shapes_path=Path("ontology/shapes"),
        port=8421,
        log_level="DEBUG",
    )


def _make_client(
    *,
    kg_store: MagicMock | None = None,
    ontology_store: MagicMock | None = None,
    validator: MagicMock | None = None,
) -> TestClient:
    """Create a TestClient from create_app() with mocked dependencies."""
    if ontology_store is None:
        ontology_store = MagicMock()
        ontology_store._graphs = {}
        ontology_store.list_ontologies.return_value = []

    if validator is None:
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


class TestValidateInstanceFoundInKG:
    """Scenario 1: Instance found in KG phases graph via ask() → successful validation."""

    def test_kg_ask_true_validates_successfully(self) -> None:
        kg = MagicMock()
        kg.ask.return_value = True
        kg.export_turtle.return_value = SAMPLE_INSTANCE_TTL

        mock_validator = MagicMock()
        mock_validator.validate.return_value = ValidationResult(conforms=True)

        client = _make_client(kg_store=kg, validator=mock_validator)

        resp = client.post("/validate", json={
            "instance_uri": "http://example.org/MyInstance",
            "shape_uri": "http://example.org/ThingShape",
        })

        data = resp.json()
        assert resp.status_code == 200
        assert data["conforms"] is True
        assert data["violation_count"] == 0

        # Verify ask() was called with a SPARQL ASK against the phases graph
        # (ask() may also be called during app startup for schema checks)
        validate_ask_calls = [
            c for c in kg.ask.call_args_list
            if GRAPH_PHASES in c[0][0] and "http://example.org/MyInstance" in c[0][0]
        ]
        assert len(validate_ask_calls) == 1
        assert "ASK" in validate_ask_calls[0][0][0]

        # Verify export_turtle was called with phases graph and subject filter
        kg.export_turtle.assert_called_once_with(GRAPH_PHASES, subject="http://example.org/MyInstance")

        # Verify validator.validate was called
        mock_validator.validate.assert_called_once()

    def test_kg_found_with_violations(self) -> None:
        """KG instance found but validation produces violations."""
        kg = MagicMock()
        kg.ask.return_value = True
        kg.export_turtle.return_value = SAMPLE_INSTANCE_TTL

        mock_validator = MagicMock()
        mock_validator.validate.return_value = ValidationResult(
            conforms=False,
            violations=[Violation(message="Missing required property")],
        )

        client = _make_client(kg_store=kg, validator=mock_validator)

        resp = client.post("/validate", json={
            "instance_uri": "http://example.org/MyInstance",
            "shape_uri": "http://example.org/ThingShape",
        })

        data = resp.json()
        assert data["conforms"] is False
        assert data["violation_count"] == 1
        assert "Missing required property" in data["violations"][0]["message"]


class TestValidateInstanceNotFound:
    """Scenario 2: Instance not found in any store → "No triples found" violation."""

    def test_not_in_kg_or_tbox(self) -> None:
        kg = MagicMock()
        kg.ask.return_value = False

        ontology_store = MagicMock()
        ontology_store._graphs = {}

        client = _make_client(kg_store=kg, ontology_store=ontology_store)

        resp = client.post("/validate", json={
            "instance_uri": "http://example.org/NonExistent",
            "shape_uri": "http://example.org/ThingShape",
        })

        data = resp.json()
        assert data["conforms"] is False
        assert data["violation_count"] == 1
        assert "No triples found" in data["violations"][0]["message"]
        assert "http://example.org/NonExistent" in data["violations"][0]["message"]

    def test_no_kg_store_and_empty_tbox(self) -> None:
        """No KG store at all, and T-Box has no matching instance."""
        ontology_store = MagicMock()
        ontology_store._graphs = {}

        client = _make_client(kg_store=None, ontology_store=ontology_store)

        resp = client.post("/validate", json={
            "instance_uri": "http://example.org/Ghost",
            "shape_uri": "http://example.org/SomeShape",
        })

        data = resp.json()
        assert data["conforms"] is False
        assert "No triples found" in data["violations"][0]["message"]


class TestValidatePrefixCompactedURI:
    """Scenario 3: Prefix-compacted URI still found by SPARQL ASK."""

    def test_compact_uri_found_via_ask(self) -> None:
        """A prefix-compacted URI like prd:Project-1 is passed directly
        to the SPARQL ASK. The mock ask() returns True, confirming that
        prefix expansion is handled by the store's _expand_prefixes()."""
        kg = MagicMock()
        kg.ask.return_value = True
        kg.export_turtle.return_value = SAMPLE_INSTANCE_TTL

        mock_validator = MagicMock()
        mock_validator.validate.return_value = ValidationResult(conforms=True)

        client = _make_client(kg_store=kg, validator=mock_validator)

        # Use a compact URI — the endpoint wraps it in angle brackets
        # and ask() handles prefix expansion internally
        resp = client.post("/validate", json={
            "instance_uri": "http://tulla.dev/prd#project-ralph",
            "shape_uri": "http://example.org/ThingShape",
        })

        data = resp.json()
        assert data["conforms"] is True

        # Verify the URI was passed through to the ASK query
        ask_sparql = kg.ask.call_args[0][0]
        assert "http://tulla.dev/prd#project-ralph" in ask_sparql


class TestValidateFallbackToTBox:
    """Scenario 4: Fallback to T-Box OntologyStore when KG ask() returns False."""

    def test_kg_miss_tbox_hit(self) -> None:
        """KG ask() returns False, instance found in OntologyStore graph."""
        from rdflib import Graph, URIRef, Namespace, RDF, RDFS

        kg = MagicMock()
        kg.ask.return_value = False

        # Build a real rdflib graph with the instance
        EX = Namespace("http://example.org/")
        g = Graph()
        g.bind("ex", EX)
        g.add((EX.FallbackInstance, RDF.type, EX.Thing))
        g.add((EX.FallbackInstance, RDFS.label, URIRef("http://example.org/label")))

        # Also add a shapes graph
        shapes_g = Graph()
        shapes_g.parse(data=SAMPLE_SHAPES_TTL, format="turtle")

        ontology_store = MagicMock()
        ontology_store._graphs = {
            "ontology://test/main": g,
            "ontology://test/shapes": shapes_g,
        }

        mock_validator = MagicMock()
        mock_validator.validate.return_value = ValidationResult(conforms=True)

        client = _make_client(
            kg_store=kg,
            ontology_store=ontology_store,
            validator=mock_validator,
        )

        resp = client.post("/validate", json={
            "instance_uri": "http://example.org/FallbackInstance",
            "shape_uri": "http://example.org/ThingShape",
        })

        data = resp.json()
        assert data["conforms"] is True

        # Verify KG was tried first (ask() also called during startup)
        validate_ask_calls = [
            c for c in kg.ask.call_args_list
            if GRAPH_PHASES in c[0][0] and "http://example.org/FallbackInstance" in c[0][0]
        ]
        assert len(validate_ask_calls) == 1
        # Verify export_turtle was NOT called (since ask returned False)
        kg.export_turtle.assert_not_called()
        # Verify validator was called (T-Box fallback found the instance)
        mock_validator.validate.assert_called_once()

    def test_no_kg_store_tbox_hit(self) -> None:
        """No KG store configured at all, instance found in T-Box."""
        from rdflib import Graph, Namespace, RDF, RDFS

        EX = Namespace("http://example.org/")
        g = Graph()
        g.bind("ex", EX)
        g.add((EX.TBoxOnly, RDF.type, EX.Thing))

        ontology_store = MagicMock()
        ontology_store._graphs = {"ontology://test/main": g}

        mock_validator = MagicMock()
        mock_validator.validate.return_value = ValidationResult(conforms=True)

        client = _make_client(
            kg_store=None,
            ontology_store=ontology_store,
            validator=mock_validator,
        )

        resp = client.post("/validate", json={
            "instance_uri": "http://example.org/TBoxOnly",
            "shape_uri": "http://example.org/SomeShape",
        })

        data = resp.json()
        assert data["conforms"] is True
        mock_validator.validate.assert_called_once()


class TestValidateMissingParams:
    """Scenario 5: Missing instance_uri or shape_uri returns an error response."""

    def test_missing_instance_uri(self) -> None:
        client = _make_client()

        resp = client.post("/validate", json={
            "shape_uri": "http://example.org/ThingShape",
        })

        data = resp.json()
        assert "error" in data
        assert "instance_uri" in data["error"]
        assert "shape_uri" in data["error"]

    def test_missing_shape_uri(self) -> None:
        client = _make_client()

        resp = client.post("/validate", json={
            "instance_uri": "http://example.org/MyInstance",
        })

        data = resp.json()
        assert "error" in data
        assert "instance_uri" in data["error"]
        assert "shape_uri" in data["error"]

    def test_both_missing(self) -> None:
        client = _make_client()

        resp = client.post("/validate", json={})

        data = resp.json()
        assert "error" in data
        assert "required" in data["error"].lower() or "instance_uri" in data["error"]

    def test_empty_strings(self) -> None:
        """Empty string values should be treated as missing."""
        client = _make_client()

        resp = client.post("/validate", json={
            "instance_uri": "",
            "shape_uri": "",
        })

        data = resp.json()
        assert "error" in data
