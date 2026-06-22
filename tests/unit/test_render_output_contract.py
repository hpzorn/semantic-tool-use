"""Tests for the render_output_contract MCP tool (req-130-2-6).

Covers the server-side function in :mod:`ontology_server.mcp.phase_tools`, the
HTTP twin in :mod:`ontology_server.api.routes.phases`, and the default port
implementation on :class:`tulla.ports.ontology.OntologyPort`.
"""

from __future__ import annotations

import pytest

from ontology_server.api.routes.phases import handle_render_output_contract
from ontology_server.mcp.phase_tools import (
    PHASE_NS,
    PHASES_GRAPH,
    PipelineDataError,
    _build_output_contract_query,
    render_output_contract,
)
from tulla.ports.ontology import OntologyPort


class _RecordingSparql:
    """SparqlClient stub that records the query and returns a canned reply."""

    def __init__(self, reply: dict | Exception):
        self.reply = reply
        self.last_query: str | None = None

    def sparql_query(self, query: str):
        self.last_query = query
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def _r3_bindings() -> dict:
    """Canonical R3 output-contract + emits-intent-field bindings."""
    return {"results": [
        {"field": "result_summary", "type": "string", "desc": "Short summary"},
        {"field": "evidence_links", "type": "list[str]"},
        {"intent": "result_summary"},
        {"intent": "evidence_links"},
        {"intent": "confidence"},
        {"intent": "caveats"},
    ]}


class TestRenderOutputContract:
    def test_query_targets_phases_graph_with_union_for_intent(self) -> None:
        query = _build_output_contract_query("r3")
        assert f"GRAPH <{PHASES_GRAPH}>" in query
        assert "SELECT ?field ?type ?desc ?intent" in query
        assert f"<{PHASE_NS}outputContract>" in query
        assert f"<{PHASE_NS}requiresField>" in query
        assert f"<{PHASE_NS}fieldType>" in query
        assert "OPTIONAL" in query
        assert f"<{PHASE_NS}fieldDescription>" in query
        assert "UNION" in query
        assert f"<{PHASE_NS}emitsIntentField>" in query

    def test_r3_renders_table_and_intent_block(self) -> None:
        sparql = _RecordingSparql(_r3_bindings())

        result = render_output_contract(sparql, "r3")

        assert "| Field | Type | Description |" in result
        assert "|-------|------|-------------|" in result
        assert "| evidence_links | list[str] |  |" in result
        assert "| result_summary | string | Short summary |" in result

        assert "## Emits Intent Fields" in result
        for name in ("result_summary", "evidence_links", "confidence", "caveats"):
            assert f"- {name}" in result

    def test_intent_fields_preserve_pydantic_order(self) -> None:
        sparql = _RecordingSparql(_r3_bindings())
        result = render_output_contract(sparql, "r3")

        intent_block = result.split("## Emits Intent Fields", 1)[1]
        positions = [
            intent_block.index(f"- {name}")
            for name in ("result_summary", "evidence_links", "confidence", "caveats")
        ]
        assert positions == sorted(positions)

    def test_no_contract_only_intent_fields_renders_just_block(self) -> None:
        sparql = _RecordingSparql({"results": [
            {"intent": "alpha"},
            {"intent": "beta"},
        ]})
        result = render_output_contract(sparql, "r3")
        assert "## Emits Intent Fields" in result
        assert "- alpha" in result
        assert "- beta" in result
        assert "| Field | Type | Description |" not in result

    def test_contract_only_no_intent_fields_renders_just_table(self) -> None:
        sparql = _RecordingSparql({"results": [
            {"field": "result_summary", "type": "string", "desc": "Short"},
        ]})
        result = render_output_contract(sparql, "r3")
        assert "| Field | Type | Description |" in result
        assert "## Emits Intent Fields" not in result

    def test_intent_fields_are_deduplicated_preserving_first_seen_order(self) -> None:
        sparql = _RecordingSparql({"results": [
            {"intent": "alpha"},
            {"intent": "beta"},
            {"intent": "alpha"},
            {"intent": "gamma"},
        ]})
        result = render_output_contract(sparql, "r3")
        intent_block = result.split("## Emits Intent Fields", 1)[1]
        assert intent_block.count("- alpha") == 1
        positions = [
            intent_block.index(f"- {name}") for name in ("alpha", "beta", "gamma")
        ]
        assert positions == sorted(positions)

    def test_missing_phase_id_raises(self) -> None:
        with pytest.raises(ValueError):
            render_output_contract(_RecordingSparql({"results": []}), "")

    def test_no_bindings_returns_empty_string(self) -> None:
        sparql = _RecordingSparql({"results": []})
        assert render_output_contract(sparql, "x99") == ""

    def test_sparql_failure_raises_pipeline_error(self) -> None:
        sparql = _RecordingSparql(RuntimeError("backend down"))
        with pytest.raises(PipelineDataError, match="backend down"):
            render_output_contract(sparql, "r3")


class TestHandleRenderOutputContract:
    def test_success_returns_200_with_markdown(self) -> None:
        sparql = _RecordingSparql(_r3_bindings())
        status, payload = handle_render_output_contract(
            sparql, {"phase_id": "r3"},
        )
        assert status == 200
        assert "markdown" in payload
        md = payload["markdown"]
        assert "| Field | Type | Description |" in md
        assert "## Emits Intent Fields" in md

    def test_missing_phase_id_returns_404(self) -> None:
        sparql = _RecordingSparql({"results": []})
        status, payload = handle_render_output_contract(sparql, {})
        assert status == 404
        assert payload == {"error": "missing phase_id"}

    def test_none_body_returns_404(self) -> None:
        status, _ = handle_render_output_contract(
            _RecordingSparql({"results": []}), None,
        )
        assert status == 404


class _StubPort(OntologyPort):
    """Minimal OntologyPort whose sparql_query returns canned data."""

    def __init__(self, reply: dict) -> None:
        self.reply = reply
        self.last_query: str | None = None

    def sparql_query(self, query: str, *, validate: bool = True):  # type: ignore[override]
        self.last_query = query
        return self.reply

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


class TestOntologyPortRenderOutputContract:
    def test_default_implementation_returns_table_and_intent_block(self) -> None:
        port = _StubPort(_r3_bindings())
        body = port.render_output_contract("r3")
        assert "| Field | Type | Description |" in body
        assert "## Emits Intent Fields" in body
        intent_block = body.split("## Emits Intent Fields", 1)[1]
        positions = [
            intent_block.index(f"- {name}")
            for name in ("result_summary", "evidence_links", "confidence", "caveats")
        ]
        assert positions == sorted(positions)
        assert "outputContract" in (port.last_query or "")
        assert "emitsIntentField" in (port.last_query or "")

    def test_default_implementation_rejects_empty_phase_id(self) -> None:
        port = _StubPort({"results": []})
        with pytest.raises(ValueError):
            port.render_output_contract("")
