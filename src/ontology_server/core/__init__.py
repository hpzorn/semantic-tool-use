"""Core ontology management components."""

from .store import OntologyStore
from .validation import SHACLValidator, ValidationResult

__all__ = ["OntologyStore", "SHACLValidator", "ValidationResult"]
