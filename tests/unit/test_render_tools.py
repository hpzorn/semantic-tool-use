"""Tests for the render_tools MCP tool (req-130-2-3).

Covers the server-side function in :mod:`ontology_server.mcp.phase_tools`, the
HTTP twin in :mod:`ontology_server.api.routes.phases`, and the default port
implementation on :class:`tulla.ports.ontology.OntologyPort`.
"""

from __future__ import annotations

import pytest

from ontology_server.api.routes.phases import handle_render_tools
from ontology_server.mcp.phase_tools import (
    PHASE_NS,
    PHASES_GRAPH,
    _build_tools_query,
    render_tools,
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
    """Canonical R3 binding set drawn from phase_content_curated.ttl."""
    return {"results": [
        {"val": "Read"},
        {"val": "Write"},
        {"val": "Glob"},
        {"val": "Grep"},
        {"val": "mcp__ontology-server__query_ontology"},
    ]}


class TestRenderTools:
    def test_query_targets_phases_graph_with_union(self) -> None:
        query = _build_tools_query("r3")
        assert f"GRAPH <{PHASES_GRAPH}>" in query
        assert "SELECT ?val" in query
        assert "UNION" in query
        assert f"<{PHASE_NS}requiresTool>" in query
        assert f"<{PHASE_NS}requiresMcp>" in query

    def test_r3_returns_two_section_bullet_list(self) -> None:
        sparql = _RecordingSparql(_r3_bindings())

        result = render_tools(sparql, "r3")

        assert "## Tools" in result
        assert "## MCP Tools" in result
        for tool in ("Read", "Write", "Glob", "Grep"):
            assert f"- {tool}" in result
        assert "- mcp__ontology-server__query_ontology" in result

        tools_section, _, mcp_section = result.partition("## MCP Tools")
        assert "mcp__" not in tools_section
        assert "- mcp__ontology-server__query_ontology" in mcp_section

    def test_tools_are_sorted_within_section(self) -> None:
        sparql = _RecordingSparql(_r3_bindings())
        result = render_tools(sparql, "r3")
        tools_section = result.split("## MCP Tools")[0]
        positions = [tools_section.index(f"- {name}") for name in ("Glob", "Grep", "Read", "Write")]
        assert positions == sorted(positions)

    def test_missing_phase_id_raises(self) -> None:
        with pytest.raises(ValueError):
            render_tools(_RecordingSparql({"results": []}), "")

    def test_no_bindings_returns_empty_sections(self) -> None:
        sparql = _RecordingSparql({"results": []})
        result = render_tools(sparql, "x99")
        assert "## Tools" in result
        assert "## MCP Tools" in result
        assert "- " not in result

    def test_sparql_failure_returns_empty_sections(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        sparql = _RecordingSparql(RuntimeError("backend down"))
        with caplog.at_level("WARNING", logger="ontology_server.mcp.phase_tools"):
            result = render_tools(sparql, "r3")
        assert "## Tools" in result and "## MCP Tools" in result


class TestHandleRenderTools:
    def test_success_returns_200_with_markdown(self) -> None:
        sparql = _RecordingSparql(_r3_bindings())
        status, payload = handle_render_tools(sparql, {"phase_id": "r3"})
        assert status == 200
        assert "markdown" in payload
        assert "- Read" in payload["markdown"]
        assert "- mcp__ontology-server__query_ontology" in payload["markdown"]

    def test_missing_phase_id_returns_404(self) -> None:
        sparql = _RecordingSparql({"results": []})
        status, payload = handle_render_tools(sparql, {})
        assert status == 404
        assert payload == {"error": "missing phase_id"}

    def test_none_body_returns_404(self) -> None:
        status, payload = handle_render_tools(_RecordingSparql({"results": []}), None)
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


class TestOntologyPortRenderTools:
    def test_default_implementation_returns_two_sections(self) -> None:
        port = _StubPort(_r3_bindings())
        body = port.render_tools("r3")
        assert "## Tools" in body
        assert "## MCP Tools" in body
        assert "- Read" in body
        assert "- mcp__ontology-server__query_ontology" in body
        assert "r3" in (port.last_query or "")

    def test_default_implementation_rejects_empty_phase_id(self) -> None:
        port = _StubPort({"results": []})
        with pytest.raises(ValueError):
            port.render_tools("")
