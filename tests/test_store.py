"""Tests for the OntologyStore."""

import pytest
from pathlib import Path

from ontology_server.core.store import OntologyStore


class TestOntologyStore:
    """Test suite for OntologyStore."""

    def test_load_ontology(self, store: OntologyStore):
        """Test that ontology loads correctly."""
        ontologies = store.list_ontologies()
        assert len(ontologies) == 1
        assert ontologies[0]["uri"] == "ontology://test/sample"
        assert ontologies[0]["triple_count"] > 0

    def test_list_ontologies_metadata(self, store: OntologyStore):
        """Test that metadata is collected correctly."""
        ontologies = store.list_ontologies()
        meta = ontologies[0]

        assert "path" in meta
        assert "triple_count" in meta
        assert "class_count" in meta
        assert meta["class_count"] == 3  # Person, Organization, Project

    def test_get_ontology(self, store: OntologyStore):
        """Test getting ontology by URI."""
        graph = store.get_ontology("ontology://test/sample")
        assert graph is not None
        assert len(graph) > 0

    def test_get_ontology_not_found(self, store: OntologyStore):
        """Test getting non-existent ontology."""
        graph = store.get_ontology("ontology://nonexistent")
        assert graph is None

    def test_get_ontology_ttl(self, store: OntologyStore):
        """Test serializing ontology to Turtle."""
        ttl = store.get_ontology_ttl("ontology://test/sample")
        assert ttl is not None
        assert "@prefix" in ttl
        assert "Person" in ttl

    def test_sparql_query(self, store: OntologyStore):
        """Test SPARQL SELECT query."""
        results = list(store.query(
            "SELECT ?class WHERE { ?class a owl:Class }"
        ))
        assert len(results) == 3  # Person, Organization, Project

    def test_sparql_query_specific_ontology(self, store: OntologyStore):
        """Test SPARQL query on specific ontology."""
        results = list(store.query(
            "SELECT ?s WHERE { ?s a owl:Class }",
            ontology_uri="ontology://test/sample"
        ))
        assert len(results) == 3

    def test_sparql_query_not_found(self, store: OntologyStore):
        """Test SPARQL query on non-existent ontology."""
        with pytest.raises(ValueError, match="Ontology not found"):
            store.query("SELECT ?s WHERE { ?s ?p ?o }", ontology_uri="ontology://nonexistent")

    def test_get_classes(self, store: OntologyStore):
        """Test getting all classes."""
        classes = store.get_classes()
        assert len(classes) == 3
        labels = [c["label"] for c in classes if c["label"]]
        assert "Person" in labels
        assert "Organization" in labels
        assert "Project" in labels

    def test_get_properties(self, store: OntologyStore):
        """Test getting all properties."""
        props = store.get_properties()
        assert len(props) >= 4  # worksFor, manages, name, age

    def test_add_triple(self, store: OntologyStore):
        """Test adding a triple."""
        before = len(store)
        success = store.add_triple(
            "ontology://test/sample",
            "http://example.org/test#NewClass",
            "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
            "http://www.w3.org/2002/07/owl#Class"
        )
        assert success
        assert len(store) == before + 1

    def test_add_triple_not_found(self, store: OntologyStore):
        """Test adding triple to non-existent ontology."""
        success = store.add_triple(
            "ontology://nonexistent",
            "http://example.org/s",
            "http://example.org/p",
            "http://example.org/o"
        )
        assert not success

    def test_add_literal_triple(self, store: OntologyStore):
        """Test adding triple with literal value."""
        success = store.add_triple(
            "ontology://test/sample",
            "http://example.org/test#Alice",
            "http://www.w3.org/2000/01/rdf-schema#comment",
            "A test person",
            is_literal=True
        )
        assert success

    def test_remove_triple(self, store: OntologyStore):
        """Test removing triples."""
        # First add a triple
        store.add_triple(
            "ontology://test/sample",
            "http://example.org/test#ToRemove",
            "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
            "http://www.w3.org/2002/07/owl#Class"
        )
        before = len(store)

        # Remove it
        removed = store.remove_triple(
            "ontology://test/sample",
            "http://example.org/test#ToRemove",
            "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
            "http://www.w3.org/2002/07/owl#Class"
        )
        assert removed == 1
        assert len(store) == before - 1

    def test_contains(self, store: OntologyStore):
        """Test __contains__ method."""
        assert "ontology://test/sample" in store
        assert "ontology://nonexistent" not in store

    def test_len(self, store: OntologyStore):
        """Test __len__ method."""
        total = len(store)
        assert total > 0


class TestEmptyStore:
    """Tests for empty store behavior."""

    def test_empty_list(self, empty_store: OntologyStore):
        """Test empty store returns empty list."""
        assert empty_store.list_ontologies() == []

    def test_empty_len(self, empty_store: OntologyStore):
        """Test empty store has zero length."""
        assert len(empty_store) == 0

    def test_load_directory_nonexistent(self, empty_store: OntologyStore):
        """Test loading from non-existent directory."""
        count = empty_store.load_directory(Path("/nonexistent/path"))
        assert count == 0
