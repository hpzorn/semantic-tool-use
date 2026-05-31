"""Tests for the render_input_contract MCP tool (req-130-2-5).

Covers the server-side function in :mod:`mcp.phase_tools`, the HTTP twin
in :mod:`api.routes.phases`, and the default port implementation on
:class:`tulla.ports.ontology.OntologyPort`.
"""

from __future__ import annotations

import pytest

from api.routes.phases import handle_render_input_contract
from mcp.phase_tools import (
    PHASES_GRAPH,
    _build_input_contract_query,
    render_input_contract,
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
    """Canonical R3 input-contract bindings (two fields, one with a desc)."""
    return {"results": [
        {"field": "idea_id", "type": "string", "desc": "Target idea id"},
        {"field": "phase_id", "type": "string"},
    ]}


class TestRenderInputContract:
    def test_query_targets_phases_graph_with_optional_desc(self) -> None:
        query = _build_input_contract_query("r3")
        assert f"GRAPH <{PHASES_GRAPH}>" in query
        assert "SELECT ?field ?type ?desc" in query
        assert "inputContract" in query
        assert "requiresField" in query
        assert "fieldType" in query
        assert "OPTIONAL" in query
        assert "fieldDescription" in query

    def test_r3_renders_markdown_table(self) -> None:
        sparql = _RecordingSparql(_r3_bindings())

        result = render_input_contract(sparql, "r3")

        # Verification criterion: returns a table listing input contract fields
        lines = result.split("\n")
        assert lines[0] == "| Field | Type | Description |"
        assert lines[1].startswith("|") and "---" in lines[1]
        # Both fields appear, lexically sorted (idea_id < phase_id)
        assert "| idea_id | string | Target idea id |" in result
        assert "| phase_id | string |  |" in result

    def test_missing_phase_id_raises(self) -> None:
        with pytest.raises(ValueError):
            render_input_contract(_RecordingSparql({"results": []}), "")

    def test_no_bindings_returns_empty_string(self) -> None:
        sparql = _RecordingSparql({"results": []})
        assert render_input_contract(sparql, "x99") == ""

    def test_sparql_failure_returns_empty(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        sparql = _RecordingSparql(RuntimeError("backend down"))
        with caplog.at_level("WARNING", logger="mcp.phase_tools"):
            assert render_input_contract(sparql, "r3") == ""


class TestHandleRenderInputContract:
    def test_success_returns_200_with_markdown(self) -> None:
        sparql = _RecordingSparql(_r3_bindings())
        status, payload = handle_render_input_contract(
            sparql, {"phase_id": "r3"},
        )
        assert status == 200
        assert "markdown" in payload
        assert payload["markdown"].startswith("| Field | Type | Description |")

    def test_missing_phase_id_returns_404(self) -> None:
        sparql = _RecordingSparql({"results": []})
        status, payload = handle_render_input_contract(sparql, {})
        assert status == 404
        assert payload == {"error": "missing phase_id"}

    def test_none_body_returns_404(self) -> None:
        status, _ = handle_render_input_contract(
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


class TestOntologyPortRenderInputContract:
    def test_default_implementation_returns_table(self) -> None:
        port = _StubPort(_r3_bindings())
        body = port.render_input_contract("r3")
        assert body.startswith("| Field | Type | Description |")
        assert "| idea_id | string | Target idea id |" in body
        assert "inputContract" in (port.last_query or "")
        assert "requiresField" in (port.last_query or "")

    def test_default_implementation_rejects_empty_phase_id(self) -> None:
        port = _StubPort({"results": []})
        with pytest.raises(ValueError):
            port.render_input_contract("")
