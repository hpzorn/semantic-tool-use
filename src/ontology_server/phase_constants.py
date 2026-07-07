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

# --- HITL approval (human review between phases) -------------------------
# Written on the PhaseOutput subject phase:{idea-id}-{phase-id}.
APPROVAL_STATUS_PRED: str = f"{PHASE_NS}approvalStatus"
RECORDED_AT_PRED: str = f"{PHASE_NS}recordedAt"
REVIEW_COMMENT_PRED: str = f"{PHASE_NS}reviewComment"
REVIEWED_AT_PRED: str = f"{PHASE_NS}reviewedAt"
REVIEWED_BY_PRED: str = f"{PHASE_NS}reviewedBy"
EDITED_BY_REVIEWER_PRED: str = f"{PHASE_NS}editedByReviewer"
# Written on the phase definition subject phase:{phase-id}.
REQUIRES_APPROVAL_PRED: str = f"{PHASE_NS}requiresApproval"

APPROVAL_PENDING: str = "pending"
APPROVAL_APPROVED: str = "approved"
APPROVAL_REJECTED: str = "rejected"
# Absence of an approvalStatus triple means "approved" (legacy outputs
# recorded before HITL existed). Completion queries must therefore use
# FILTER NOT EXISTS { ?o phase:approvalStatus ?st .
#                     FILTER(?st IN ("pending","rejected")) }
# rather than requiring status = "approved".
