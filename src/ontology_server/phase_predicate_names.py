"""Mapping of phase IDs to their allowed intent-field predicate names.

Derived from the phase:emitsIntentField triples in
tulla/ontologies/phase-content.trig (single source of truth).
"""
from __future__ import annotations

PHASE_PREDICATE_NAMES: dict[str, frozenset[str]] = {
    # Discovery track
    "d1": frozenset({
        "key_capabilities", "ecosystem_context", "reuse_opportunities",
        "idea_verbatim_features",
        "summary", "lifecycle", "blocked_by", "blocks",
        "related_ideas", "existing_systems", "current_gaps",
        "prior_work_refs",
    }),
    "d2": frozenset({
        "personas", "non_negotiable_needs", "primary_persona_jtbd",
        "persona_count", "primary_persona", "conflicting_needs",
    }),
    "d3": frozenset({
        "quadrant", "strategic_constraints", "verdict", "complexity_tier",
        "user_value_score", "business_value_score", "technical_value_score",
        "total_value_score", "max_score", "effort", "impact",
        "roi_verdict", "priority_recommendation", "confidence",
        "value_dimensions", "proceed",
    }),
    "d4": frozenset({
        "blockers", "root_blocker", "recommended_next_steps",
        "gaps_found", "p0_gaps", "gaps", "quality_attribute_gaps",
        "knowledge_gaps_as_research_questions", "recommendation",
    }),
    "d5": frozenset({
        "mode", "recommendation", "northstar", "mandatory_features", "key_constraints",
        "priority_score", "research_questions", "constraints", "prior_research_status",
    }),
    # Research track
    "r1": frozenset({
        "research_questions", "questions_refined",
        "execution_batches", "critical_path",
    }),
    "r2": frozenset({
        "source_map", "source_gaps", "sources_identified",
        "sources_by_rq", "codebase_patterns", "total_by_type",
    }),
    "r3": frozenset({
        "rq_answers", "remaining_unknowns", "research_questions",
        "findings", "experiments_run", "key_insights", "open_questions",
    }),
    "r4": frozenset({
        "key_findings", "papers_reviewed", "rqs_addressed",
        "synthesis_complete", "rq_conclusions", "cross_cutting_themes",
        "conflicting_evidence", "open_items_for_r5",
    }),
    "r5": frozenset({
        "experiment_results", "impl_implications", "experiments_run", "experiments_passed",
        "experiments", "key_findings", "falsified_hypotheses",
    }),
    "r6": frozenset({
        "synthesised_answers", "recommendation", "risks", "findings_count",
        "confidence", "proceed", "rq_answers", "key_findings",
        "implementation_prerequisites",
    }),
    # Planning track
    "p1": frozenset({
        "discovery_summary",
        "feature_scope", "non_negotiable_constraints", "success_metrics",
        "jtbd_traceability", "scope_boundaries",
    }),
    "p2": frozenset({
        "codebase_summary",
        "relevant_modules", "architecture_patterns", "integration_points",
        "test_coverage", "tech_debt_hotspots",
    }),
    "p3": frozenset({
        "architecture_decisions", "quality_goals",
        "total_dependencies", "circular_dependencies",
        "file_structure", "adr_count", "shacl_gate", "p0_outstanding_deliverable",
    }),
    "p4": frozenset({
        "tasks", "task_count", "p0_count", "p1_count", "p2_count",
        "critical_path", "blocked_tasks",
    }),
    "p5": frozenset({
        "research_requests",
        "status", "blocking_gaps", "risks", "readiness_verdict", "readiness_rationale",
    }),
    "p6": frozenset({
        "requirement_count", "prd_file",
        "prd_context", "requirements_exported",
        "p0_count", "p1_count", "p2_count",
    }),
    # Implementation track
    "i1": frozenset({
        "status", "tasks_completed", "tasks_failed",
        "pr_url", "commits", "test_results", "outstanding_items",
    }),
    # Change-agent tracks (unchanged)
    "intake": frozenset({"change_type", "affected_files", "scope", "lightweight_eligible"}),
    "context-scan": frozenset({"conformance_assertion", "patterns_found", "test_coverage_note"}),
    "plan": frozenset({"plan_summary", "plan_steps", "files_to_modify", "risk_notes"}),
    "execute": frozenset({"changes_summary", "files_modified", "commit_ref", "execution_notes"}),
    "trace": frozenset({
        "change_type", "affected_files", "conformance_assertion", "commit_ref",
        "change_summary", "timestamp", "issue_ref", "sprint_id", "story_points",
    }),
}


# Maps each consuming phase to the set of upstream field names it needs.
# collect_upstream_facts_tool(idea_id, consuming_phase_id=X) will restrict
# its output to only these fields, reducing context window size.
PHASE_CONSUMED_FIELDS: dict[str, frozenset[str]] = {
    # D-track: each phase builds on the previous
    "d2": frozenset({
        "key_capabilities", "ecosystem_context", "reuse_opportunities",
        "summary", "lifecycle", "existing_systems", "current_gaps",
    }),
    "d3": frozenset({
        "key_capabilities", "ecosystem_context",
        "personas", "non_negotiable_needs", "primary_persona_jtbd",
        "persona_count",
    }),
    "d4": frozenset({
        "key_capabilities", "ecosystem_context", "existing_systems",
        "personas", "primary_persona", "non_negotiable_needs",
        "quadrant", "verdict", "effort", "impact", "complexity_tier",
    }),
    "d5": frozenset({
        "quadrant", "verdict", "effort", "impact",
        "blockers", "root_blocker", "recommendation",
        "personas", "idea_verbatim_features",
    }),
    # R-track
    "r1": frozenset({
        "northstar", "mandatory_features", "key_constraints",
        "mode", "recommendation",
        "blockers", "root_blocker",
        "research_questions",
    }),
    "r2": frozenset({
        "research_questions",
        "northstar", "mandatory_features",
    }),
    "r3": frozenset({
        "research_questions",
        "sources_identified", "sources_by_rq",
    }),
    "r4": frozenset({
        "research_questions",
        "findings", "experiments_run",
    }),
    "r5": frozenset({
        "research_questions",
        "rq_conclusions", "open_items_for_r5",
    }),
    "r6": frozenset({
        "research_questions",
        "rq_conclusions", "experiments", "key_findings",
        "open_items_for_r5",
    }),
    # P-track
    "p1": frozenset({
        # from D5
        "northstar", "mandatory_features", "key_constraints",
        "mode", "recommendation",
        # from R6
        "rq_answers", "key_findings", "implementation_prerequisites",
        "risks", "proceed", "confidence",
        # from D4
        "blockers", "root_blocker",
        # from D1 — verbatim feature list as a secondary anti-drift check
        "idea_verbatim_features",
    }),
    "p2": frozenset({
        # from P1
        "feature_scope", "non_negotiable_constraints",
        "success_metrics", "scope_boundaries",
        "discovery_summary",
    }),
    "p3": frozenset({
        # from P1
        "feature_scope", "non_negotiable_constraints",
        "success_metrics",
        # from P2
        "relevant_modules", "architecture_patterns",
        "integration_points", "tech_debt_hotspots",
        "codebase_summary",
        # from D3 — scales architectural ceremony to idea complexity
        "complexity_tier",
    }),
    "p4": frozenset({
        # from P1
        "feature_scope",
        # from P2
        "relevant_modules", "integration_points",
        # from P3
        "architecture_decisions", "quality_goals",
        "file_structure", "adr_count",
        "shacl_gate", "p0_outstanding_deliverable",
    }),
    "p5": frozenset({
        # from P3+P4
        "architecture_decisions", "quality_goals",
        "tasks", "task_count", "critical_path", "blocked_tasks",
        "p0_count", "p1_count",
        "feature_scope",
    }),
    "p6": frozenset({
        # from P4 — the full task list is what P6 needs most
        "tasks", "task_count", "p0_count", "p1_count", "p2_count",
        "critical_path",
        # from P1 — scope context for PRD framing
        "feature_scope", "success_metrics", "non_negotiable_constraints",
    }),
    "i1": frozenset({
        # from P6
        "requirement_count", "prd_file", "prd_context",
        "requirements_exported",
        # from P4
        "tasks", "critical_path",
    }),
}


def get_predicates_for_phase(phase_id: str) -> frozenset[str]:
    """Return the allowed intent-field names for *phase_id*.

    Returns an empty frozenset for unknown phase IDs so callers can
    iterate safely without branching on None.
    """
    return PHASE_PREDICATE_NAMES.get(phase_id, frozenset())
