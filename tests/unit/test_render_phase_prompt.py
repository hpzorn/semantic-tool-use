"""Tests for the render_phase_prompt MCP tool (req-130-2-7).

Covers the server-side coarse-default composer in
:mod:`ontology_server.mcp.phase_tools`, the HTTP twin in
:mod:`ontology_server.api.routes.phases`, and the default port
implementation on :class:`tulla.ports.ontology.OntologyPort`.

Canonical section order: Methodology → Tools → Gates → Input Contract →
Output Contract.
"""

from __future__ import annotations

import pytest

from ontology_server.api.routes.phases import handle_render_phase_prompt
from ontology_server.mcp.phase_tools import (
    PHASE_NS,
    PHASE_PROMPT_SECTIONS,
    PHASES_GRAPH,
    render_phase_prompt,
)
from tulla.ports.ontology import OntologyPort


class _MultiSparql:
    """SparqlClient stub that dispatches canned replies by query content."""

    def __init__(self, *, procedure: str, tools: list[str], gates: list[tuple[str, str]],
                 input_rows: list[tuple[str, str, str]],
                 output_rows: list[tuple[str, str, str]],
                 intent_fields: list[str]) -> None:
        self._procedure = procedure
        self._tools = tools
        self._gates = gates
        self._input_rows = input_rows
        self._output_rows = output_rows
        self._intent_fields = intent_fields
        self.queries: list[str] = []

    def sparql_query(self, query: str):
        self.queries.append(query)
        if f"<{PHASE_NS}procedure>" in query and "?proc" in query:
            return {"results": [{"proc": self._procedure}]}
        if f"<{PHASE_NS}requiresTool>" in query and f"<{PHASE_NS}requiresMcp>" in query:
            return {"results": [{"val": v} for v in self._tools]}
        if f"<{PHASE_NS}shaclGate>" in query:
            return {"results": [{"shape": s, "label": l} for s, l in self._gates]}
        if (
            f"<{PHASE_NS}inputContract>" in query
            and f"<{PHASE_NS}emitsIntentField>" not in query
        ):
            return {"results": [
                {"field": f, "type": t, "desc": d} for f, t, d in self._input_rows
            ]}
        if (
            f"<{PHASE_NS}outputContract>" in query
            and f"<{PHASE_NS}emitsIntentField>" in query
        ):
            results: list[dict] = []
            for f, t, d in self._output_rows:
                results.append({"field": f, "type": t, "desc": d})
            for name in self._intent_fields:
                results.append({"intent": name})
            return {"results": results}
        return {"results": []}


def _r3_stub() -> _MultiSparql:
    return _MultiSparql(
        procedure="Verify the structured deliverable against the gates.",
        tools=["Read", "Grep", "mcp__ontology-server__sparql_query"],
        gates=[(f"{PHASE_NS}R3Conformance", "R3 deliverable must conform")],
        input_rows=[("upstream_summary", "string", "Summary from R2")],
        output_rows=[
            ("result_summary", "string", "Short summary"),
            ("evidence_links", "list[str]", ""),
        ],
        intent_fields=["result_summary", "evidence_links", "confidence", "caveats"],
    )


class TestRenderPhasePrompt:
    def test_section_order_matches_canonical_constant(self) -> None:
        assert PHASE_PROMPT_SECTIONS == (
            ("Methodology", "render_methodology"),
            ("Tools", "render_tools"),
            ("Gates", "render_gates"),
            ("Input Contract", "render_input_contract"),
            ("Output Contract", "render_output_contract"),
        )

    def test_r3_output_contains_all_five_h2_sections_in_canonical_order(self) -> None:
        sparql = _r3_stub()
        result = render_phase_prompt(sparql, "r3")

        positions = [
            result.index(f"## {header}")
            for header, _ in PHASE_PROMPT_SECTIONS
        ]
        assert positions == sorted(positions)
        for header, _ in PHASE_PROMPT_SECTIONS:
            assert f"## {header}" in result

    def test_r3_inlines_each_granular_renderer_output(self) -> None:
        sparql = _r3_stub()
        result = render_phase_prompt(sparql, "r3")

        assert "Verify the structured deliverable against the gates." in result
        assert "- Read" in result
        assert "- mcp__ontology-server__sparql_query" in result
        assert "SHACL Gate: phase:R3Conformance — R3 deliverable must conform" in result
        assert "| upstream_summary | string | Summary from R2 |" in result
        assert "| result_summary | string | Short summary |" in result
        assert "## Emits Intent Fields" in result
        for name in ("result_summary", "evidence_links", "confidence", "caveats"):
            assert f"- {name}" in result

    def test_calls_each_granular_renderer_exactly_once(self) -> None:
        sparql = _r3_stub()
        render_phase_prompt(sparql, "r3")
        assert len(sparql.queries) == 5

    def test_each_granular_query_targets_phases_graph(self) -> None:
        sparql = _r3_stub()
        render_phase_prompt(sparql, "r3")
        for q in sparql.queries:
            assert f"GRAPH <{PHASES_GRAPH}>" in q

    def test_empty_granular_bodies_still_emit_header_only_skeleton(self) -> None:
        empty = _MultiSparql(
            procedure="",
            tools=[],
            gates=[],
            input_rows=[],
            output_rows=[],
            intent_fields=[],
        )
        result = render_phase_prompt(empty, "x99")
        for header, _ in PHASE_PROMPT_SECTIONS:
            assert f"## {header}" in result

    def test_missing_phase_id_raises(self) -> None:
        with pytest.raises(ValueError):
            render_phase_prompt(_r3_stub(), "")


class TestHandleRenderPhasePrompt:
    def test_success_returns_200_with_full_skeleton(self) -> None:
        sparql = _r3_stub()
        status, payload = handle_render_phase_prompt(sparql, {"phase_id": "r3"})
        assert status == 200
        assert "markdown" in payload
        md = payload["markdown"]
        for header, _ in PHASE_PROMPT_SECTIONS:
            assert f"## {header}" in md

    def test_missing_phase_id_returns_404(self) -> None:
        sparql = _r3_stub()
        status, payload = handle_render_phase_prompt(sparql, {})
        assert status == 404
        assert payload == {"error": "missing phase_id"}

    def test_none_body_returns_404(self) -> None:
        status, _ = handle_render_phase_prompt(_r3_stub(), None)
        assert status == 404

    def test_non_string_phase_id_returns_404(self) -> None:
        status, _ = handle_render_phase_prompt(_r3_stub(), {"phase_id": 42})
        assert status == 404


class _StubPort(OntologyPort):
    """Minimal OntologyPort whose sparql_query is driven by ``_MultiSparql``."""

    def __init__(self, sparql: _MultiSparql) -> None:
        self._sparql = sparql

    def sparql_query(self, query: str, *, validate: bool = True):  # type: ignore[override]
        return self._sparql.sparql_query(query)

    def query_ideas(self, **_): return {}
    def get_idea(self, idea_id): return {}
    def store_fact(self, subject, predicate, object, **_): return {}
    def forget_fact(self, fact_id): return {}
    def recall_facts(self, **_): return {}
    def sparql_update(self, query, **_): return {}
    def update_idea(self, idea_id, **_): return {}
    def forget_by_context(self, context): return 0
    def set_lifecycle(self, idea_id, new_state, **_): return {}
    def add_triple(self, subject, predicate, object, **_): return {}
    def remove_triples_by_subject(self, subject, **_): return 0
    def validate_instance(self, instance_uri, shape_uri, **_): return {"conforms": True}


class TestOntologyPortRenderPhasePrompt:
    def test_default_implementation_emits_all_five_sections_for_r3(self) -> None:
        port = _StubPort(_r3_stub())
        body = port.render_phase_prompt("r3")
        positions = [
            body.index(f"## {header}")
            for header, _ in PHASE_PROMPT_SECTIONS
        ]
        assert positions == sorted(positions)

    def test_default_implementation_rejects_empty_phase_id(self) -> None:
        port = _StubPort(_r3_stub())
        with pytest.raises(ValueError):
            port.render_phase_prompt("")
