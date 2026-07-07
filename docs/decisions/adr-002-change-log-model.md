# ADR-002: Editable dashboard with a reified change log

Status: accepted (2026-07-07)

## Context

ADR-001 made pending phase outputs reviewable. The next step: the dashboard
becomes a live workbench — ideas, memory facts (incl. PRD requirements), and
phase outputs at ANY approval status are editable in place. Every human edit
must be traceable: who changed what, when, from which value to which, and
why.

## Decision

1. **Reified change log, own named graph**
   (`http://semantic-tool-use.org/graphs/changes`, namespace
   `change: <http://semantic-tool-use.org/change/>`): one `change:Change`
   per field edit with `targetSubject`, `targetGraph`, `entityKind`
   (`phase_output|idea|fact`), `field`, `oldValue` (omitted when absent
   before), `newValue` (verbatim), `batch` (shared per submit),
   `prov:wasAttributedTo`, `prov:atTime`, optional `reason`. Plain SPARQL,
   no RDF-star — matches the `memory:Fact` reification style and stays
   queryable by fleet and dashboard alike. Living in its own graph, history
   survives phase re-records (which wipe the output subject).
2. **Only human edits are logged** (dashboard + REST edit endpoints). Agent
   writes (`record_phase_result`, MCP `update_idea`, `store_facts`) are not
   — their provenance lives on the entities themselves.
3. **Edit semantics per entity**:
   - *Phase outputs* (`edit_phase_output`): allowed at any approval status;
     SHACL-gate revalidated; a violating edit restores the original literals
     per-predicate and records nothing; `approvalStatus` never changes.
     Instead the result reports `stale_phases` — consumers (per
     `PHASE_CONSUMED_FIELDS`) that already recorded outputs for the idea.
     Re-running them is the human's call; nothing auto-invalidates.
   - *Ideas* (`IdeasStore.update_idea_fields`): targeted per-predicate
     rewrite (never the full-object `update_idea` round-trip), stamps
     `dcterms:modified`. Lifecycle is excluded — it stays on the
     `LifecycleManager` state machine (changelog for lifecycle transitions
     is a follow-up).
   - *Facts* (`AgentMemory.update_fact`): update-in-place on the existing
     fact URI (identity, `memory:timestamp`, and the original
     `prov:wasAttributedTo` preserved; editor identity lives on the change
     record); stamps `memory:updatedAt`. PRD requirement fields are facts,
     so this is the PRD edit path; multi-valued predicates are separate
     facts edited per row.
4. **T-Box instance browser stays read-only** — the rdflib ontology store
   is not persisted at runtime; UI edits there would silently die on
   restart.
5. **UI**: click-to-edit HTMX partials (ideas, fact rows), a full-page
   phase editor with consumed-by captions + staleness banner, per-entity
   History sections, and a global `/dashboard/changes` feed.

## Consequences

- The knowledge graph carries a complete, queryable audit trail of human
  intervention — usable for future features (revert, review of reviews,
  drift analysis of human vs agent values).
- Editing an approved output does not pause the pipeline; the staleness
  report is advisory. If stronger semantics are wanted later, flipping
  status back to pending is a one-line change in `edit_phase_output`.
- REST `POST /ideas/{id}/update` now logs changes attributed to "api";
  agents using MCP `update_idea` remain unlogged by design.
