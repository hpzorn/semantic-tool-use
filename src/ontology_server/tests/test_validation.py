"""Tests for SHACL validation."""

import pytest
from pathlib import Path

from ..core.validation import SHACLValidator, ValidationResult, Violation


@pytest.fixture
def validator():
    """Create validator with bundled shapes."""
    return SHACLValidator()


@pytest.fixture
def well_formed_ontology():
    """A well-formed ontology following best practices."""
    return """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix dc: <http://purl.org/dc/terms/> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    @prefix ex: <http://example.org/> .

    ex:GoodOntology a owl:Ontology ;
        rdfs:label "Good Ontology" ;
        rdfs:comment "A well-documented ontology" ;
        owl:versionInfo "1.0.0"^^xsd:string ;
        dc:creator "Test Author" .

    ex:Person a owl:Class ;
        rdfs:label "Person" ;
        rdfs:comment "A human being" .

    ex:hasName a owl:DatatypeProperty ;
        rdfs:label "has name" ;
        rdfs:domain ex:Person ;
        rdfs:range xsd:string .

    ex:knows a owl:ObjectProperty ;
        rdfs:label "knows" ;
        rdfs:domain ex:Person ;
        rdfs:range ex:Person .
    """


@pytest.fixture
def poorly_formed_ontology():
    """An ontology missing best practices."""
    return """
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix ex: <http://example.org/> .

    ex:BadOntology a owl:Ontology .

    ex:Person a owl:Class .

    ex:hasName a owl:DatatypeProperty .

    ex:knows a owl:ObjectProperty .
    """


class TestSHACLValidator:
    """Tests for SHACLValidator class."""

    def test_validator_initialization(self, validator):
        """Test validator initializes correctly."""
        assert validator is not None
        assert validator._shapes_cache == {}

    def test_bundled_shapes_path_exists(self):
        """Test bundled shapes directory exists."""
        shapes_path = SHACLValidator.get_bundled_shapes_path()
        assert shapes_path.exists()

    def test_list_bundled_shapes(self):
        """Test listing bundled shape sets."""
        shapes = SHACLValidator.list_bundled_shapes()
        assert len(shapes) >= 2

        shape_names = [s["name"] for s in shapes]
        assert "owl-shapes" in shape_names
        assert "ontology-metadata-shapes" in shape_names

    def test_load_bundled_shapes_owl(self):
        """Test loading OWL shapes."""
        shapes = SHACLValidator.load_bundled_shapes("owl-shapes")
        assert shapes is not None
        assert len(shapes) > 0

    def test_load_bundled_shapes_metadata(self):
        """Test loading metadata shapes."""
        shapes = SHACLValidator.load_bundled_shapes("ontology-metadata-shapes")
        assert shapes is not None
        assert len(shapes) > 0

    def test_load_bundled_shapes_not_found(self):
        """Test loading non-existent shapes returns None."""
        shapes = SHACLValidator.load_bundled_shapes("nonexistent-shapes")
        assert shapes is None

    def test_load_all_bundled_shapes(self):
        """Test loading all bundled shapes."""
        shapes = SHACLValidator.load_all_bundled_shapes()
        assert shapes is not None
        assert len(shapes) > 0


class TestOntologyQualityValidation:
    """Tests for upper ontology quality validation."""

    def test_validate_well_formed_ontology(self, validator, well_formed_ontology):
        """Test validation of well-formed ontology has fewer issues."""
        result = validator.validate_ontology_quality(well_formed_ontology)
        assert isinstance(result, ValidationResult)
        # Well-formed ontology should have fewer violations
        violations = [v for v in result.violations if v.severity == "Violation"]
        assert len(violations) == 0

    def test_validate_poorly_formed_ontology(self, validator, poorly_formed_ontology):
        """Test validation catches missing best practices."""
        result = validator.validate_ontology_quality(poorly_formed_ontology)
        assert isinstance(result, ValidationResult)
        # Poorly formed ontology should have warnings
        assert len(result.violations) > 0

        # Should have warnings about missing labels
        messages = [v.message for v in result.violations]
        assert any("label" in m.lower() for m in messages)

    def test_validate_with_specific_shape_set(self, validator, well_formed_ontology):
        """Test validation with specific shape set."""
        result = validator.validate_ontology_quality(
            well_formed_ontology,
            shape_sets=["owl-shapes"]
        )
        assert isinstance(result, ValidationResult)

    def test_validate_invalid_ttl(self, validator):
        """Test validation handles invalid Turtle."""
        result = validator.validate_ontology_quality("invalid turtle content {{{")
        assert result.conforms is False
        assert len(result.violations) > 0
        assert "parse" in result.violations[0].message.lower() or "error" in result.violations[0].message.lower()

    def test_validation_result_to_dict(self, validator, well_formed_ontology):
        """Test ValidationResult.to_dict() method."""
        result = validator.validate_ontology_quality(well_formed_ontology)
        result_dict = result.to_dict()

        assert "conforms" in result_dict
        assert "violation_count" in result_dict
        assert "violations" in result_dict
        assert "report" in result_dict
        assert isinstance(result_dict["violations"], list)


class TestInstanceValidation:
    """Tests for SHACL instance validation."""

    def test_validate_valid_instance(self, validator):
        """Test validation of a conforming instance."""
        shapes_ttl = """
        @prefix sh: <http://www.w3.org/ns/shacl#> .
        @prefix ex: <http://example.org/> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        ex:PersonShape a sh:NodeShape ;
            sh:targetClass ex:Person ;
            sh:property [
                sh:path ex:hasName ;
                sh:minCount 1 ;
                sh:datatype xsd:string
            ] .
        """

        instance_ttl = """
        @prefix ex: <http://example.org/> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        ex:John a ex:Person ;
            ex:hasName "John Doe"^^xsd:string .
        """

        result = validator.validate(instance_ttl, shapes_ttl=shapes_ttl)
        assert result.conforms is True

    def test_validate_invalid_instance(self, validator):
        """Test validation catches violations."""
        shapes_ttl = """
        @prefix sh: <http://www.w3.org/ns/shacl#> .
        @prefix ex: <http://example.org/> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        ex:PersonShape a sh:NodeShape ;
            sh:targetClass ex:Person ;
            sh:property [
                sh:path ex:hasName ;
                sh:minCount 1 ;
                sh:datatype xsd:string ;
                sh:message "Person must have a name"
            ] .
        """

        instance_ttl = """
        @prefix ex: <http://example.org/> .

        ex:John a ex:Person .
        """

        result = validator.validate(instance_ttl, shapes_ttl=shapes_ttl)
        assert result.conforms is False
        assert len(result.violations) > 0

    def test_validate_no_shapes(self, validator):
        """Test validation with no shapes passes by default."""
        instance_ttl = """
        @prefix ex: <http://example.org/> .
        ex:Something ex:hasValue "test" .
        """
        # Create a new validator with no shapes
        empty_validator = SHACLValidator()
        result = empty_validator.validate(instance_ttl)
        assert result.conforms is True


class TestViolation:
    """Tests for Violation dataclass."""

    def test_violation_creation(self):
        """Test creating a Violation."""
        v = Violation(
            message="Test error",
            path="http://example.org/prop",
            focus_node="http://example.org/node",
            severity="Warning",
            value="bad value"
        )
        assert v.message == "Test error"
        assert v.severity == "Warning"

    def test_violation_to_dict(self):
        """Test Violation.to_dict() method."""
        v = Violation(message="Test", severity="Info")
        d = v.to_dict()
        assert d["message"] == "Test"
        assert d["severity"] == "Info"
        assert "path" in d
        assert "focus_node" in d


class TestCacheManagement:
    """Tests for validator cache management."""

    def test_clear_cache(self, validator):
        """Test clearing the shapes cache."""
        # Load some shapes first
        validator.load_shapes()
        validator.clear_cache()
        assert validator._shapes_cache == {}
        assert validator._default_shapes is None
