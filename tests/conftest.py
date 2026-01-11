"""Pytest configuration and fixtures for ontology server tests."""

import pytest
from pathlib import Path
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ontology_server.config import Settings
from ontology_server.core.store import OntologyStore
from ontology_server.core.validation import SHACLValidator


@pytest.fixture
def fixtures_path() -> Path:
    """Path to test fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_ttl_path(fixtures_path: Path) -> Path:
    """Path to sample.ttl test ontology."""
    return fixtures_path / "sample.ttl"


@pytest.fixture
def sample_ttl(sample_ttl_path: Path) -> str:
    """Sample ontology as string."""
    return sample_ttl_path.read_text()


@pytest.fixture
def store(sample_ttl_path: Path) -> OntologyStore:
    """OntologyStore with sample ontology loaded."""
    s = OntologyStore()
    s.load_ontology("ontology://test/sample", sample_ttl_path)
    return s


@pytest.fixture
def empty_store() -> OntologyStore:
    """Empty OntologyStore."""
    return OntologyStore()


@pytest.fixture
def validator(fixtures_path: Path) -> SHACLValidator:
    """SHACL validator with no shapes loaded."""
    return SHACLValidator(fixtures_path / "shapes")


@pytest.fixture
def settings(fixtures_path: Path) -> Settings:
    """Test settings."""
    return Settings(
        ontology_path=fixtures_path,
        shapes_path=fixtures_path / "shapes",
        port=8421,  # Different port for tests
        log_level="DEBUG",
    )


@pytest.fixture
def valid_instance_ttl() -> str:
    """Valid RDF instance for testing."""
    return """
@prefix ex: <http://example.org/test#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

ex:Charlie a ex:Person ;
    rdfs:label "Charlie" ;
    ex:name "Charlie Brown" ;
    ex:age 35 .
"""


@pytest.fixture
def invalid_instance_ttl() -> str:
    """Invalid RDF instance (malformed) for testing."""
    return '''
@prefix ex: <http://example.org/test#> .

ex:Invalid a ex:Person ;
    ex:name "Missing closing quote
'''
