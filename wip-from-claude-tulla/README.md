# Salvage from claude-tulla idea-130 implementation

These files were produced by tulla's implement-phase during the idea-130
implementation run on 2026-05-19. Due to a cross-repo bug in tulla
(the implement/commit/verify loop doesn't understand cross-repo PRDs),
they were placed under `/Users/sandboxuser/claude-tulla/` instead of
the ontology-server repo where they belong.

## Why they're in `wip-from-claude-tulla/` instead of `src/`

The two locations have **incompatible architectures**:

- `claude-tulla/mcp/phase_tools.py` uses a `SparqlClient` Protocol
  injected by the caller. Self-contained. 1173 lines of correct
  phase-fact logic, dependency-free.
- `src/ontology_server/mcp/phase_tools.py` (the live skeleton on
  `main`) uses FastMCP `@mcp.tool()` decorators and imports
  `from knowledge_graph.core.store import GRAPH_PHASES`.

A direct copy would not work; the API surfaces differ. The work needs
porting (FastMCP decoration + `KnowledgeGraphStore` injection)
before it can replace the live skeleton.

## What to do with this

1. Read `mcp/phase_tools.py` for the logic of:
   - `render_phase_prompt(phase_id)` (coarse default)
   - `render_methodology`, `render_tools`, `render_gates`,
     `render_input_contract`, `render_output_contract` (granular)
   - `list_pipeline(agent_family)` (DAG topo sort)
   - `next_phase(agent_family, current_id, verdict)`
   - `collect_upstream_facts(idea_id)`
   - `record_phase_result(phase_id, idea_id, artifact_path, result_json)`
     (SHACL-gated 8-step persist sequence per ADR-130-7)
2. Port each function into FastMCP-decorated form against
   `src/ontology_server/mcp/phase_tools.py`'s pattern.
3. Port the tests in `tests/` similarly.
4. Delete this `wip-from-claude-tulla/` directory once the live
   `src/ontology_server/mcp/phase_tools.py` is complete.

## Provenance

- Source repo: `claude-tulla` at branch
  `feat/idea-130-subagent-tulla` (recovery commit `086dd14`, reverted
  in a subsequent commit on the same branch).
- Idea: `idea-130` ("Subagent-tulla as a lean parallel fork").
- ADRs referenced in the salvaged code: `arch:adr-73-1`,
  `arch:adr-73-5`, `arch:adr-130-7`.
