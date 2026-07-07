# ADR-001: HITL approval as graph facts with a long-poll wait model

Status: accepted (2026-07-07)

## Context

The phase pipeline had no human checkpoint: an output counted as complete
the moment `record_phase_result` passed its SHACL gate and wrote
`phase:producedBy`. The dashboard was read-only. We want a human to be able
to review, edit, approve, or reject key phase outputs (research brief, PRD,
implementation plan) before downstream phases consume them — without
babysitting the orchestrator.

## Decision

1. **Approval state lives in the phases graph**, on the PhaseOutput subject
   (`phase:approvalStatus` pending/approved/rejected, `phase:recordedAt`,
   `phase:reviewComment`, `phase:reviewedAt/By`, `phase:editedByReviewer`).
   Runtime alternatives (omnigent policy ASK verdicts, orchestrator-local
   state) were rejected because approval must be durable, queryable, and
   transport-agnostic (MCP + REST share the same core functions).
2. **Absence of a status means approved.** Completion queries use
   `FILTER NOT EXISTS { ?o phase:approvalStatus ?st .
   FILTER(?st IN ("pending","rejected")) }`, so outputs recorded before HITL
   existed need no migration.
3. **Gate points are ontology flags** (`phase:requiresApproval` on the phase
   definition; ship defaults d5/p1/p6), toggleable from the dashboard. The
   flag lives on a trig-declared subject, so a phase-content re-seed restores
   ship defaults — accepted trade-off over a second source of truth. The
   seeding idempotency probe (`phase_tools._SEED_PROBE_*`) must be bumped
   whenever the trig gains triples deployed stores must receive.
4. **Rejected outputs stay in the graph** (status + comment) so the
   orchestrator can read the feedback and re-dispatch the phase agent with
   `reviewer_feedback`; the re-run's idempotent cleanup replaces the subject.
5. **The orchestrator waits via a server-side long-poll**
   (`await_approval(idea_id, phase_id, timeout_s≤110)`), because each
   orchestrator tool round-trip is an LLM turn — raw SPARQL polling would
   burn one inference per probe during a review that may take an hour.
6. **Approve/reject are never MCP tools.** Only the dashboard and REST
   (`POST /phase/approve|reject`) can decide, so agents cannot approve their
   own output. Edited fields are re-validated against the phase's SHACL gate
   before an approval lands; a violating edit restores the original literals
   per-predicate and leaves the output pending.
7. **Ablation mode (`ONTOLOGY_DISABLE_GATES`) always auto-approves** —
   approval is part of gating, and SDLC-bench arm b must stay a
   single-variable change.

## Consequences

- The pipeline pauses hands-free at gate points and resumes on dashboard
  approval; past the orchestrator's poll bound it reports WAITING_APPROVAL.
- Reviews are auditable graph history (who, when, what comment, whether
  edited).
- Deploy note: server (Query-A semantics change via new status triples) and
  fleet (Query A filter) must ship together — an old orchestrator counts
  pending outputs as complete.
