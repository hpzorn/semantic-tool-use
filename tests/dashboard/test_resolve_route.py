"""Integration tests for the /resolve/{uri:path} route handler."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from ontology_server.dashboard import create_dashboard_app

PHASE_NS = "http://impl-ralph.io/phase#"


def _kg_store_factory(query_side_effects: list) -> MagicMock:
    """Build a mock KnowledgeGraphStore with programmed query responses."""
    kg = MagicMock()
    kg.query.side_effect = query_side_effects
    kg.get_stats.return_value = {}
    return kg


def _type_result(types: list[str]) -> SimpleNamespace:
    return SimpleNamespace(bindings=[{"type": t} for t in types])


def _po_result(pairs: list[tuple[str, str]]) -> SimpleNamespace:
    return SimpleNamespace(bindings=[{"p": p, "o": o} for p, o in pairs])


def _make_client(kg_query_side_effects: list) -> TestClient:
    """Create a TestClient backed by a dashboard app with mocked stores."""
    ontology_store = MagicMock()
    ontology_store.list_ontologies.return_value = []
    ontology_store.get_classes.return_value = []
    ontology_store.query.return_value = iter([(0,)])

    kg = _kg_store_factory(kg_query_side_effects)

    agent_memory = MagicMock()
    agent_memory.get_all_contexts.return_value = []
    agent_memory.count_facts.return_value = 0

    ideas_store = MagicMock()
    ideas_store.count_ideas.return_value = 0

    app = create_dashboard_app(
        ontology_store=ontology_store,
        kg_store=kg,
        agent_memory=agent_memory,
        ideas_store=ideas_store,
    )
    return TestClient(app, follow_redirects=False)


class TestResolveRouteRedirect:
    """Request /resolve/ with a known URI -> assert 302 redirect."""

    def test_skos_concept_uri_returns_302(self) -> None:
        """A skos:Concept URI triggers a 302 redirect to idea_detail."""
        uri = "http://example.org/ideas/idea-42"
        client = _make_client([
            _type_result(["http://www.w3.org/2004/02/skos/core#Concept"]),
        ])

        response = client.get(f"/resolve/{uri}")

        assert response.status_code == 302
        location = response.headers["location"]
        assert "idea-42" in location

    def test_unregistered_route_falls_back_to_generic(self) -> None:
        """When resolve_uri returns a route that doesn't exist yet, fall back to 200."""
        # Use a slash-based URI (not hash URI) to avoid fragment stripping
        uri = "http://impl-ralph.io/phase/idea50-d1"
        client = _make_client([
            # resolve_uri: returns phase_detail which is not yet registered
            _type_result([f"{PHASE_NS}PhaseOutput"]),
            # get_triples_for_uri: called as fallback
            _po_result([
                (f"{PHASE_NS}producedBy", "d1"),
            ]),
        ])

        response = client.get(f"/resolve/{uri}")

        assert response.status_code == 200
        body = response.text
        assert "idea50-d1" in body


class TestResolveRouteGenericDetail:
    """Request /resolve/ with an unknown URI -> assert 200 with generic template."""

    def test_unknown_type_returns_200_with_triples(self) -> None:
        """An unknown rdf:type renders generic_detail.html with 200."""
        uri = "http://example.org/unknown-thing"
        client = _make_client([
            # resolve_uri: unknown type
            _type_result(["http://example.org/UnknownClass"]),
            # get_triples_for_uri: returns some triples
            _po_result([
                ("http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "http://example.org/UnknownClass"),
                ("http://www.w3.org/2000/01/rdf-schema#label", "Some Thing"),
            ]),
        ])

        response = client.get(f"/resolve/{uri}")

        assert response.status_code == 200
        body = response.text
        assert "http://example.org/unknown-thing" in body
        assert "Some Thing" in body

    def test_no_type_returns_200_generic(self) -> None:
        """A URI with no rdf:type at all renders generic_detail.html."""
        uri = "http://example.org/orphan"
        client = _make_client([
            # resolve_uri: no types found
            _type_result([]),
            # get_triples_for_uri: no triples
            _po_result([]),
        ])

        response = client.get(f"/resolve/{uri}")

        assert response.status_code == 200
        body = response.text
        assert "http://example.org/orphan" in body
        assert "No triples found" in body
