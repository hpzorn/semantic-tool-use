"""SHACL validation service for RDF instances."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import logging

from rdflib import Graph, Namespace, RDF
from pyshacl import validate

logger = logging.getLogger(__name__)

SH = Namespace("http://www.w3.org/ns/shacl#")


@dataclass
class Violation:
    """A single SHACL validation violation."""

    message: str
    path: str | None = None
    focus_node: str | None = None
    severity: str = "Violation"
    value: str | None = None
    source_shape: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "message": self.message,
            "path": self.path,
            "focus_node": self.focus_node,
            "severity": self.severity,
            "value": self.value,
            "source_shape": self.source_shape,
        }


@dataclass
class ValidationResult:
    """Result of SHACL validation."""

    conforms: bool
    violations: list[Violation] = field(default_factory=list)
    report_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "conforms": self.conforms,
            "violation_count": len(self.violations),
            "violations": [v.to_dict() for v in self.violations],
            "report": self.report_text,
        }


class SHACLValidator:
    """SHACL validation service.

    Validates RDF instances against SHACL shapes.
    Supports loading shapes from files and caching them.
    """

    def __init__(self, shapes_path: Path | None = None):
        """Initialize validator.

        Args:
            shapes_path: Optional path to directory containing SHACL shape files
        """
        self.shapes_path = shapes_path
        self._shapes_cache: dict[str, Graph] = {}
        self._default_shapes: Graph | None = None

    def load_shapes(self, shapes_uri: str | None = None) -> Graph:
        """Load SHACL shapes from file or cache.

        Args:
            shapes_uri: Optional URI/path to specific shapes; if None, loads all

        Returns:
            Graph containing SHACL shapes
        """
        # Return cached shapes if available
        if shapes_uri and shapes_uri in self._shapes_cache:
            return self._shapes_cache[shapes_uri]

        # Load all shapes from directory
        shapes = Graph()

        if self.shapes_path and self.shapes_path.exists():
            for ttl in self.shapes_path.glob("*.ttl"):
                try:
                    shapes.parse(ttl, format="turtle")
                    logger.debug(f"Loaded shapes from {ttl}")
                except Exception as e:
                    logger.error(f"Failed to load shapes from {ttl}: {e}")

        # Cache for future use
        if shapes_uri:
            self._shapes_cache[shapes_uri] = shapes
        else:
            self._default_shapes = shapes

        return shapes

    def load_shapes_from_string(self, shapes_ttl: str) -> Graph:
        """Load SHACL shapes from Turtle string.

        Args:
            shapes_ttl: SHACL shapes as Turtle string

        Returns:
            Graph containing SHACL shapes
        """
        shapes = Graph()
        shapes.parse(data=shapes_ttl, format="turtle")
        return shapes

    def validate(
        self,
        instance_ttl: str,
        shapes_uri: str | None = None,
        shapes_ttl: str | None = None,
        inference: str = "rdfs"
    ) -> ValidationResult:
        """Validate RDF instance against SHACL shapes.

        Args:
            instance_ttl: Turtle string of RDF instance to validate
            shapes_uri: Optional URI to load shapes from cache/file
            shapes_ttl: Optional Turtle string containing shapes (overrides shapes_uri)
            inference: Inference type ('none', 'rdfs', 'owlrl')

        Returns:
            ValidationResult with conformance status and any violations
        """
        # Parse instance data
        try:
            instance = Graph()
            instance.parse(data=instance_ttl, format="turtle")
        except Exception as e:
            return ValidationResult(
                conforms=False,
                violations=[Violation(message=f"Failed to parse instance: {e}")],
                report_text=f"Parse error: {e}"
            )

        # Load shapes
        if shapes_ttl:
            shapes = self.load_shapes_from_string(shapes_ttl)
        elif shapes_uri:
            shapes = self.load_shapes(shapes_uri)
        else:
            shapes = self._default_shapes or self.load_shapes()

        # Check if we have any shapes
        if len(shapes) == 0:
            logger.warning("No SHACL shapes loaded, validation will pass by default")
            return ValidationResult(
                conforms=True,
                violations=[],
                report_text="No shapes to validate against"
            )

        # Perform validation
        try:
            conforms, results_graph, results_text = validate(
                data_graph=instance,
                shacl_graph=shapes,
                inference=inference,
                abort_on_first=False,
                meta_shacl=False,
                advanced=True,
            )
        except Exception as e:
            return ValidationResult(
                conforms=False,
                violations=[Violation(message=f"Validation error: {e}")],
                report_text=f"Validation error: {e}"
            )

        # Extract violations from results graph
        violations = self._extract_violations(results_graph)

        return ValidationResult(
            conforms=conforms,
            violations=violations,
            report_text=results_text
        )

    def _extract_violations(self, results_graph: Graph) -> list[Violation]:
        """Extract violation details from SHACL results graph.

        Args:
            results_graph: Graph containing SHACL validation results

        Returns:
            List of Violation objects
        """
        violations = []

        # Find all validation results
        for result in results_graph.subjects(RDF.type, SH.ValidationResult):
            message = results_graph.value(result, SH.resultMessage)
            path = results_graph.value(result, SH.resultPath)
            focus = results_graph.value(result, SH.focusNode)
            severity = results_graph.value(result, SH.resultSeverity)
            value = results_graph.value(result, SH.value)
            source = results_graph.value(result, SH.sourceShape)

            violations.append(Violation(
                message=str(message) if message else "Unknown validation error",
                path=str(path) if path else None,
                focus_node=str(focus) if focus else None,
                severity=str(severity).split("#")[-1] if severity else "Violation",
                value=str(value) if value else None,
                source_shape=str(source) if source else None,
            ))

        return violations

    def validate_graph(
        self,
        instance: Graph,
        shapes: Graph | None = None,
        inference: str = "rdfs"
    ) -> ValidationResult:
        """Validate RDF Graph directly (without serialization).

        Args:
            instance: RDF Graph to validate
            shapes: Optional shapes Graph; if None, uses default shapes
            inference: Inference type

        Returns:
            ValidationResult
        """
        if shapes is None:
            shapes = self._default_shapes or self.load_shapes()

        if len(shapes) == 0:
            return ValidationResult(
                conforms=True,
                violations=[],
                report_text="No shapes to validate against"
            )

        try:
            conforms, results_graph, results_text = validate(
                data_graph=instance,
                shacl_graph=shapes,
                inference=inference,
                abort_on_first=False,
            )
        except Exception as e:
            return ValidationResult(
                conforms=False,
                violations=[Violation(message=f"Validation error: {e}")],
                report_text=f"Validation error: {e}"
            )

        violations = self._extract_violations(results_graph)

        return ValidationResult(
            conforms=conforms,
            violations=violations,
            report_text=results_text
        )

    def clear_cache(self):
        """Clear cached shapes."""
        self._shapes_cache.clear()
        self._default_shapes = None
