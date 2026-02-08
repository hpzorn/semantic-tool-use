"""Integration tests for the /resolve/{uri:path} route handler."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from ontology_server.dashboard import create_dashboard_app

PHASE_NS = "http://impl-ralph.io/phase#"
PRD_NS = "http://impl-ralph.io/prd#"


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

    def test_phase_output_uri_returns_302(self) -> None:
        """A phase:PhaseOutput URI triggers a 302 redirect to phase_detail."""
        # Use a slash-based URI (not hash URI) to avoid fragment stripping
        uri = "http://impl-ralph.io/phase/idea50-d1"
        client = _make_client([
            # resolve_uri: returns phase_detail
            _type_result([f"{PHASE_NS}PhaseOutput"]),
        ])

        response = client.get(f"/resolve/{uri}")

        assert response.status_code == 302
        location = response.headers["location"]
        assert "/phases/idea50/d1" in location

    def test_prd_project_uri_returns_302(self) -> None:
        """A prd:Project URI triggers a 302 redirect to project_detail."""
        # URL-encode the '#' to prevent fragment stripping by the HTTP client
        uri = "http://impl-ralph.io/prd%23project-ralph"
        client = _make_client([
            _type_result([f"{PRD_NS}Project"]),
        ])

        response = client.get(f"/resolve/{uri}")

        assert response.status_code == 302
        location = response.headers["location"]
        assert "/projects/project-ralph" in location


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

    def test_generic_detail_uri_objects_are_clickable(self) -> None:
        """URI objects should render as clickable links to resolve endpoint."""
        uri = "http://example.org/resource"
        object_uri = "http://example.org/related-resource"
        client = _make_client([
            # resolve_uri: unknown type
            _type_result(["http://example.org/SomeClass"]),
            # get_triples_for_uri: returns triples with URI object
            _po_result([
                ("http://www.w3.org/2000/01/rdf-schema#seeAlso", object_uri),
                ("http://www.w3.org/2000/01/rdf-schema#label", "Resource Label"),
            ]),
        ])

        response = client.get(f"/resolve/{uri}")

        assert response.status_code == 200
        body = response.text
        # Verify predicate uses short_uri filter
        assert "rdfs:seeAlso" in body
        assert "rdfs:label" in body
        # Verify URI object is a clickable link to resolve endpoint (urlencode encodes : but not /)
        assert '/dashboard/resolve/http%3A//example.org/related-resource' in body
        # Verify literal object is NOT wrapped in a link (appears outside anchor tags)
        assert "Resource Label" in body
        assert '<a href="/dashboard/resolve/' not in body.split("Resource Label")[0].split("rdfs:label")[-1]

    def test_generic_detail_displays_full_uri_and_prefixed_title(self) -> None:
        """Page should show full URI in title and code block (hash URIs have fragment stripped by browser)."""
        # Use a slash-based URI (not hash) to avoid fragment stripping
        uri = "http://semantic-tool-use.org/ontology/tool-use/MyClass"
        client = _make_client([
            # resolve_uri: unknown type
            _type_result([]),
            # get_triples_for_uri: no triples
            _po_result([]),
        ])

        response = client.get(f"/resolve/{uri}")

        assert response.status_code == 200
        body = response.text
        # Verify URI is shown in both h1 and code block
        assert "<h1>" in body
        assert f"<code>{uri}</code>" in body
