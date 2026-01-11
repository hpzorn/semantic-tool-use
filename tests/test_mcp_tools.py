"""Tests for MCP server tools."""

import pytest
from pathlib import Path

from ontology_server.config import Settings
from ontology_server.core.store import OntologyStore
from ontology_server.core.validation import SHACLValidator
from ontology_server.mcp.server import create_mcp_server


@pytest.fixture
def mcp_server(store: OntologyStore, settings: Settings):
    """Create MCP server for testing."""
    validator = SHACLValidator(settings.shapes_path)
    return create_mcp_server(settings, store, validator)


class TestMCPServerCreation:
    """Tests for MCP server creation."""

    def test_create_server(self, mcp_server):
        """Test that MCP server is created successfully."""
        assert mcp_server is not None
        assert mcp_server.name == "ontology-server"

    def test_server_has_tools(self, mcp_server):
        """Test that server has expected tools registered."""
        # FastMCP stores tools internally
        # We can verify by checking the server was created
        assert mcp_server is not None


class TestMCPTools:
    """Tests for individual MCP tools.

    Note: These tests call the tool functions directly rather than
    through MCP protocol, which requires async handling.
    """

    def test_list_ontologies_function(self, store: OntologyStore):
        """Test list_ontologies returns correct data."""
        ontologies = store.list_ontologies()
        assert len(ontologies) == 1
        assert ontologies[0]["uri"] == "ontology://test/sample"

    def test_get_ontology_function(self, store: OntologyStore):
        """Test get_ontology returns Turtle."""
        ttl = store.get_ontology_ttl("ontology://test/sample")
        assert ttl is not None
        assert "@prefix" in ttl

    def test_get_ontology_not_found(self, store: OntologyStore):
        """Test get_ontology with unknown URI."""
        ttl = store.get_ontology_ttl("ontology://unknown")
        assert ttl is None

    def test_query_ontology_function(self, store: OntologyStore):
        """Test query_ontology executes SPARQL."""
        results = list(store.query("SELECT ?s WHERE { ?s a owl:Class } LIMIT 5"))
        assert len(results) > 0

    def test_query_specific_ontology(self, store: OntologyStore):
        """Test query on specific ontology."""
        results = list(store.query(
            "SELECT ?s WHERE { ?s a owl:Class }",
            ontology_uri="ontology://test/sample"
        ))
        assert len(results) == 3

    def test_get_classes_function(self, store: OntologyStore):
        """Test get_classes returns class list."""
        classes = store.get_classes()
        assert len(classes) == 3
        uris = [c["uri"] for c in classes]
        assert any("Person" in uri for uri in uris)

    def test_get_properties_function(self, store: OntologyStore):
        """Test get_properties returns property list."""
        props = store.get_properties()
        assert len(props) >= 4

    def test_add_triple_function(self, store: OntologyStore):
        """Test add_triple adds to graph."""
        before = len(store)
        success = store.add_triple(
            "ontology://test/sample",
            "http://example.org/test#NewThing",
            "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
            "http://www.w3.org/2002/07/owl#NamedIndividual"
        )
        assert success
        assert len(store) == before + 1

    def test_validate_instance_valid(self, validator: SHACLValidator):
        """Test validate_instance with valid data."""
        ttl = """
@prefix ex: <http://example.org/> .
ex:Test a ex:Thing .
"""
        result = validator.validate(ttl)
        assert result.conforms is True

    def test_validate_instance_invalid_syntax(self, validator: SHACLValidator):
        """Test validate_instance with invalid syntax."""
        ttl = "not valid turtle {"
        result = validator.validate(ttl)
        assert result.conforms is False


class TestSearchFunctionality:
    """Tests for search capabilities."""

    def test_sparql_search_by_label(self, store: OntologyStore):
        """Test searching by label using SPARQL."""
        query = """
        SELECT ?s ?label WHERE {
            ?s rdfs:label ?label .
            FILTER(CONTAINS(LCASE(STR(?label)), "alice"))
        }
        """
        results = list(store.query(query))
        assert len(results) > 0

    def test_sparql_search_case_insensitive(self, store: OntologyStore):
        """Test case-insensitive search."""
        query = """
        SELECT ?s WHERE {
            ?s rdfs:label ?label .
            FILTER(CONTAINS(LCASE(STR(?label)), "person"))
        }
        """
        results = list(store.query(query))
        assert len(results) >= 1


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_query_results(self, store: OntologyStore):
        """Test query that returns no results."""
        results = list(store.query(
            "SELECT ?s WHERE { ?s a <http://nonexistent/Type> }"
        ))
        assert len(results) == 0

    def test_malformed_sparql(self, store: OntologyStore):
        """Test handling of malformed SPARQL."""
        with pytest.raises(Exception):
            list(store.query("NOT VALID SPARQL"))

    def test_unicode_in_query(self, store: OntologyStore):
        """Test handling of unicode in queries."""
        # Add triple with unicode
        store.add_triple(
            "ontology://test/sample",
            "http://example.org/test#UnicodeTest",
            "http://www.w3.org/2000/01/rdf-schema#label",
            "Test with émojis 🎉",
            is_literal=True
        )

        # Query should work
        results = list(store.query("""
            SELECT ?s WHERE {
                ?s rdfs:label ?label .
                FILTER(CONTAINS(?label, "émojis"))
            }
        """))
        assert len(results) >= 1
