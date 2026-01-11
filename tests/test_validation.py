"""Tests for the SHACL validator."""

import pytest

from ontology_server.core.validation import SHACLValidator, ValidationResult


class TestSHACLValidator:
    """Test suite for SHACLValidator."""

    def test_validate_valid_instance(self, validator: SHACLValidator, valid_instance_ttl: str):
        """Test validating a valid RDF instance."""
        # Without shapes, validation passes by default
        result = validator.validate(valid_instance_ttl)
        assert isinstance(result, ValidationResult)
        assert result.conforms is True
        assert len(result.violations) == 0

    def test_validate_invalid_syntax(self, validator: SHACLValidator, invalid_instance_ttl: str):
        """Test validating malformed RDF."""
        result = validator.validate(invalid_instance_ttl)
        assert result.conforms is False
        assert len(result.violations) > 0
        assert "parse" in result.violations[0].message.lower() or "error" in result.violations[0].message.lower()

    def test_validate_with_inline_shapes(self, validator: SHACLValidator):
        """Test validation with inline SHACL shapes."""
        shapes = """
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ex: <http://example.org/test#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

ex:PersonShape a sh:NodeShape ;
    sh:targetClass ex:Person ;
    sh:property [
        sh:path ex:name ;
        sh:minCount 1 ;
        sh:datatype xsd:string ;
        sh:message "Person must have a name"
    ] .
"""

        # Valid instance
        valid = """
@prefix ex: <http://example.org/test#> .
ex:Alice a ex:Person ;
    ex:name "Alice" .
"""
        result = validator.validate(valid, shapes_ttl=shapes)
        assert result.conforms is True

        # Invalid instance (missing name)
        invalid = """
@prefix ex: <http://example.org/test#> .
ex:Bob a ex:Person .
"""
        result = validator.validate(invalid, shapes_ttl=shapes)
        assert result.conforms is False
        assert len(result.violations) > 0

    def test_result_to_dict(self, validator: SHACLValidator, valid_instance_ttl: str):
        """Test ValidationResult.to_dict() method."""
        result = validator.validate(valid_instance_ttl)
        d = result.to_dict()

        assert "conforms" in d
        assert "violation_count" in d
        assert "violations" in d
        assert "report" in d
        assert isinstance(d["violations"], list)

    def test_validate_empty_string(self, validator: SHACLValidator):
        """Test validating empty string."""
        result = validator.validate("")
        # Empty graph is valid (no violations)
        assert result.conforms is True

    def test_load_shapes_from_string(self, validator: SHACLValidator):
        """Test loading shapes from string."""
        shapes_ttl = """
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ex: <http://example.org/> .

ex:TestShape a sh:NodeShape ;
    sh:targetClass ex:Test .
"""
        shapes = validator.load_shapes_from_string(shapes_ttl)
        assert len(shapes) > 0

    def test_clear_cache(self, validator: SHACLValidator):
        """Test clearing shapes cache."""
        # Load some shapes
        shapes_ttl = """
@prefix sh: <http://www.w3.org/ns/shacl#> .
ex:Shape a sh:NodeShape .
"""
        validator.load_shapes_from_string(shapes_ttl)
        validator.clear_cache()
        # Should not raise
        assert validator._shapes_cache == {}


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_validation_result_defaults(self):
        """Test ValidationResult default values."""
        result = ValidationResult(conforms=True)
        assert result.conforms is True
        assert result.violations == []
        assert result.report_text == ""

    def test_validation_result_to_dict(self):
        """Test full ValidationResult serialization."""
        from ontology_server.core.validation import Violation

        result = ValidationResult(
            conforms=False,
            violations=[
                Violation(
                    message="Test violation",
                    path="http://example.org/prop",
                    focus_node="http://example.org/node",
                    severity="Violation"
                )
            ],
            report_text="Detailed report"
        )

        d = result.to_dict()
        assert d["conforms"] is False
        assert d["violation_count"] == 1
        assert len(d["violations"]) == 1
        assert d["violations"][0]["message"] == "Test violation"
        assert d["report"] == "Detailed report"
