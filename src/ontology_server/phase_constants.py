"""Shared namespace constants for phase-pipeline SPARQL queries.

These constants are used by:
- src/ontology_server/mcp/phase_tools.py
- src/ontology_server/dashboard/services.py
- src/ontology_server/api/routes/phases.py

Centralised here to avoid silent divergence between duplicate definitions.
"""

PHASE_NS: str = "http://tulla.dev/phase#"
TRACE_NS: str = "http://tulla.dev/trace#"
PRD_NS: str = "http://tulla.dev/prd#"
PHASES_GRAPH: str = "http://semantic-tool-use.org/graphs/phases"
_PRESERVES_PREFIX: str = f"{PHASE_NS}preserves-"
