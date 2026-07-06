"""Pytest configuration and fixtures for ontology server tests."""

import pytest
from pathlib import Path
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Add tulla src to path for tulla package imports (phase_predicate_names, ports.ontology).
# Preferred: the sibling checkout in the same workspace (<workspace>/tulla/src);
# fallback: the legacy location two levels further up. Guard stat errors —
# sandboxed environments raise PermissionError instead of returning False.
for _tulla_src in (
    Path(__file__).parent.parent.parent / "tulla" / "src",
    Path(__file__).parent.parent.parent.parent / "tulla" / "src",
):
    try:
        if _tulla_src.exists():
            sys.path.insert(0, str(_tulla_src))
            break
    except OSError:
        continue

from ontology_server.config import Settings
from ontology_server.core.store import OntologyStore
from ontology_server.core.validation import SHACLValidator


def _tulla_port_has_default_impls() -> bool:
    """True when tulla's OntologyPort still ships default phase-tool methods.

    The tulla branch ``feat/decouple-port-rest`` replaces the port's default
    implementations with ``NotImplementedError`` stubs; the ``TestOntologyPort*``
    classes test exactly those removed defaults and must be skipped against it.
    """
    try:
        import inspect

        from tulla.ports.ontology import OntologyPort

        return "NotImplementedError" not in inspect.getsource(OntologyPort.render_gates)
    except Exception:
        return False


def pytest_collection_modifyitems(config, items):
    if _tulla_port_has_default_impls():
        return
    skip = pytest.mark.skip(
        reason="tulla OntologyPort has no default phase-tool implementations "
        "on this branch (feat/decouple-port-rest)"
    )
    for item in items:
        cls = getattr(item, "cls", None)
        if cls is not None and cls.__name__.startswith("TestOntologyPort"):
            item.add_marker(skip)


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
