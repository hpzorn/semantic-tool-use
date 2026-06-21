"""Tests for the render_gates MCP tool (req-130-2-4).

Covers the server-side function in :mod:`ontology_server.mcp.phase_tools`, the
HTTP twin in :mod:`ontology_server.api.routes.phases`, and the default port
implementation on :class:`tulla.ports.ontology.OntologyPort`.
"""

from __future__ import annotations

import pytest

from ontology_server.api.routes.phases import handle_render_gates
from ontology_server.mcp.phase_tools import (
    PHASE_NS,
    PHASES_GRAPH,
    _build_gates_query,
    render_gates,
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


def _r3_bindings(label: str = "R3 output gate") -> dict:
    """Canonical R3 gate binding (single SHACL shape with a label)."""
    return {"results": [
        {"shape": f"{PHASE_NS}R3OutputShape", "label": label},
    ]}


class TestRenderGates:
    def test_query_targets_phases_graph_with_optional_label(self) -> None:
        query = _build_gates_query("r3")
        assert f"GRAPH <{PHASES_GRAPH}>" in query
        assert "SELECT ?shape ?label" in query
        assert f"<{PHASE_NS}shaclGate>" in query
        assert "OPTIONAL" in query
        assert "rdf-schema#label" in query

    def test_r3_renders_shacl_gate_line(self) -> None:
        sparql = _RecordingSparql(_r3_bindings("R3 output gate"))

        result = render_gates(sparql, "r3")

        assert result.startswith("SHACL Gate: phase:R3OutputShape — ")
        assert "R3 output gate" in result

    def test_multiple_gates_one_line_each(self) -> None:
        sparql = _RecordingSparql({"results": [
            {"shape": f"{PHASE_NS}R3OutputShape", "label": "primary"},
            {"shape": f"{PHASE_NS}AuxShape", "label": "secondary"},
        ]})

        result = render_gates(sparql, "r3")

        lines = result.split("\n")
        assert len(lines) == 2
        assert all(line.startswith("SHACL Gate: ") for line in lines)
        assert any("phase:R3OutputShape — primary" in line for line in lines)
        assert any("phase:AuxShape — secondary" in line for line in lines)

    def test_missing_label_renders_empty_label_segment(self) -> None:
        sparql = _RecordingSparql({"results": [
            {"shape": f"{PHASE_NS}R3OutputShape"},
        ]})

        result = render_gates(sparql, "r3")
        assert result == "SHACL Gate: phase:R3OutputShape — "

    def test_missing_phase_id_raises(self) -> None:
        with pytest.raises(ValueError):
            render_gates(_RecordingSparql({"results": []}), "")

    def test_no_bindings_returns_empty_string(self) -> None:
        sparql = _RecordingSparql({"results": []})
        result = render_gates(sparql, "x99")
        assert result == ""

    def test_sparql_failure_returns_empty(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        sparql = _RecordingSparql(RuntimeError("backend down"))
        with caplog.at_level("WARNING", logger="ontology_server.mcp.phase_tools"):
            result = render_gates(sparql, "r3")
        assert result == ""


class TestHandleRenderGates:
    def test_success_returns_200_with_markdown(self) -> None:
        sparql = _RecordingSparql(_r3_bindings())
        status, payload = handle_render_gates(sparql, {"phase_id": "r3"})
        assert status == 200
        assert "markdown" in payload
        assert payload["markdown"].startswith("SHACL Gate: phase:R3OutputShape — ")

    def test_missing_phase_id_returns_404(self) -> None:
        sparql = _RecordingSparql({"results": []})
        status, payload = handle_render_gates(sparql, {})
        assert status == 404
        assert payload == {"error": "missing phase_id"}

    def test_none_body_returns_404(self) -> None:
        status, payload = handle_render_gates(_RecordingSparql({"results": []}), None)
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


class TestOntologyPortRenderGates:
    def test_default_implementation_returns_gate_line(self) -> None:
        port = _StubPort(_r3_bindings("R3 output gate"))
        body = port.render_gates("r3")
        assert body.startswith("SHACL Gate: phase:R3OutputShape — ")
        assert "R3 output gate" in body
        assert "r3" in (port.last_query or "")
        assert "shaclGate" in (port.last_query or "")

    def test_default_implementation_rejects_empty_phase_id(self) -> None:
        port = _StubPort({"results": []})
        with pytest.raises(ValueError):
            port.render_gates("")
