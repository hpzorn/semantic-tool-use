"""Tests for the ontology store."""

import pytest
from rdflib import Graph, URIRef, Literal, RDF, RDFS, OWL

from ..core.store import OntologyStore


@pytest.fixture
def store():
    """Create a fresh store for each test."""
    return OntologyStore()


@pytest.fixture
def sample_ontology_ttl():
    """Sample ontology in Turtle format."""
    return """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .

    ex:TestOntology a owl:Ontology ;
        rdfs:label "Test Ontology" ;
        owl:versionInfo "1.0.0" .

    ex:Person a owl:Class ;
        rdfs:label "Person" ;
        rdfs:comment "A human being" .

    ex:Organization a owl:Class ;
        rdfs:label "Organization" ;
        rdfs:comment "A formal group of people" .

    ex:worksFor a owl:ObjectProperty ;
        rdfs:label "works for" ;
        rdfs:domain ex:Person ;
        rdfs:range ex:Organization .

    ex:hasName a owl:DatatypeProperty ;
        rdfs:label "has name" ;
        rdfs:domain ex:Person ;
        rdfs:range rdfs:Literal .
    """


def test_store_initialization(store):
    """Test store initializes correctly."""
    assert store is not None
    assert len(store._graphs) == 0


def test_load_ontology_from_string(store, sample_ontology_ttl):
    """Test loading ontology from TTL string."""
    uri = "ontology://test/sample"
    success = store.load_ontology_from_string(sample_ontology_ttl, uri)
    assert success is True
    assert uri in store._graphs


def test_list_ontologies(store, sample_ontology_ttl):
    """Test listing loaded ontologies."""
    uri = "ontology://test/sample"
    store.load_ontology_from_string(sample_ontology_ttl, uri)

    ontologies = store.list_ontologies()
    assert len(ontologies) == 1
    assert ontologies[0]["uri"] == uri


def test_get_ontology_ttl(store, sample_ontology_ttl):
    """Test retrieving ontology as Turtle."""
    uri = "ontology://test/sample"
    store.load_ontology_from_string(sample_ontology_ttl, uri)

    ttl = store.get_ontology_ttl(uri)
    assert ttl is not None
    assert "ex:Person" in ttl or "Person" in ttl


def test_get_ontology_ttl_not_found(store):
    """Test getting non-existent ontology returns None."""
    ttl = store.get_ontology_ttl("ontology://nonexistent")
    assert ttl is None


def test_get_classes(store, sample_ontology_ttl):
    """Test getting OWL classes from ontology."""
    uri = "ontology://test/sample"
    store.load_ontology_from_string(sample_ontology_ttl, uri)

    classes = store.get_classes(uri)
    assert len(classes) >= 2  # Person and Organization

    class_uris = [c["uri"] for c in classes]
    assert any("Person" in uri for uri in class_uris)
    assert any("Organization" in uri for uri in class_uris)


def test_get_properties(store, sample_ontology_ttl):
    """Test getting OWL properties from ontology."""
    uri = "ontology://test/sample"
    store.load_ontology_from_string(sample_ontology_ttl, uri)

    props = store.get_properties(uri)
    assert len(props) >= 2  # worksFor and hasName

    prop_uris = [p["uri"] for p in props]
    assert any("worksFor" in uri for uri in prop_uris)
    assert any("hasName" in uri for uri in prop_uris)


def test_query_select(store, sample_ontology_ttl):
    """Test SPARQL SELECT query."""
    uri = "ontology://test/sample"
    store.load_ontology_from_string(sample_ontology_ttl, uri)

    query = """
    SELECT ?class ?label WHERE {
        ?class a owl:Class .
        ?class rdfs:label ?label .
    }
    """
    results = list(store.query(query, uri))
    assert len(results) >= 2


def test_query_across_all(store, sample_ontology_ttl):
    """Test querying across all ontologies."""
    store.load_ontology_from_string(sample_ontology_ttl, "ontology://test/one")
    store.load_ontology_from_string(sample_ontology_ttl, "ontology://test/two")

    query = "SELECT ?class WHERE { ?class a owl:Class }"
    results = list(store.query(query))
    # When combining graphs with identical triples, duplicates are deduplicated
    # So we get 2 distinct classes (Person, Organization), not 4
    assert len(results) >= 2


def test_add_triple(store, sample_ontology_ttl):
    """Test adding a triple to an ontology."""
    uri = "ontology://test/sample"
    store.load_ontology_from_string(sample_ontology_ttl, uri)

    success = store.add_triple(
        uri,
        "http://example.org/NewClass",
        str(RDF.type),
        str(OWL.Class)
    )
    assert success is True

    # Verify triple was added
    classes = store.get_classes(uri)
    class_uris = [c["uri"] for c in classes]
    assert any("NewClass" in uri for uri in class_uris)


def test_add_literal_triple(store, sample_ontology_ttl):
    """Test adding a literal triple to an ontology."""
    uri = "ontology://test/sample"
    store.load_ontology_from_string(sample_ontology_ttl, uri)

    success = store.add_triple(
        uri,
        "http://example.org/Person",
        str(RDFS.comment),
        "Updated comment",
        is_literal=True
    )
    assert success is True


def test_combined_graph(store, sample_ontology_ttl):
    """Test getting combined graph from all ontologies."""
    store.load_ontology_from_string(sample_ontology_ttl, "ontology://test/one")
    store.load_ontology_from_string(sample_ontology_ttl, "ontology://test/two")

    combined = store.get_combined_graph()
    assert combined is not None
    # Combined graph should have triples from both
    assert len(combined) > 0
