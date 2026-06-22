"""Tests for the list_pipeline MCP tool (req-130-2-8).

Covers the server-side SPARQL transitive-closure helper in
:mod:`ontology_server.mcp.phase_tools`, the HTTP twin in
:mod:`ontology_server.api.routes.phases`, and the default port
implementation on :class:`tulla.ports.ontology.OntologyPort`.
"""

from __future__ import annotations

import pytest

from ontology_server.api.routes.phases import handle_list_pipeline
from ontology_server.mcp.phase_tools import (
    PHASE_NS,
    PHASES_GRAPH,
    PipelineDataError,
    _build_list_pipeline_query,
    list_pipeline,
)
from tulla.ports.ontology import OntologyPort


_RESEARCH_PIPELINE: tuple[str, ...] = (
    "r1-discovery-fed",
    "r1-groundwork",
    "r1-spike",
    "r2",
    "r3",
    "r4",
    "r5",
    "r5-retry",
    "r6",
)


class _RecordingSparql:
    """SparqlClient stub that records the query and returns a canned reply."""

    def __init__(self, reply):
        self.reply = reply
        self.last_query: str | None = None

    def sparql_query(self, query: str):
        self.last_query = query
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def _research_reply() -> dict:
    """Return a SPARQL reply mimicking the depth-sorted research pipeline."""
    return {
        "results": [
            {"phaseId": phase_id, "depth": str(depth)}
            for depth, phase_id in enumerate(_RESEARCH_PIPELINE)
        ]
    }


# ---------------------------------------------------------------------------
# list_pipeline (mcp/phase_tools.py)
# ---------------------------------------------------------------------------


class TestListPipeline:
    def test_research_family_returns_ordered_phase_ids(self) -> None:
        sparql = _RecordingSparql(_research_reply())
        result = list_pipeline(sparql, "research")
        assert result == list(_RESEARCH_PIPELINE)

    def test_query_targets_phases_graph_and_uses_transitive_closure(self) -> None:
        query = _build_list_pipeline_query("research")
        assert f"GRAPH <{PHASES_GRAPH}>" in query
        assert f"<{PHASE_NS}upstreamPhase>+" in query
        assert f'<{PHASE_NS}agentFamily> "research"' in query
        assert "COUNT(?ancestor)" in query
        assert "ORDER BY ?depth" in query

    def test_query_substitutes_agent_family_literal(self) -> None:
        query = _build_list_pipeline_query("planning")
        assert '"planning"' in query
        assert '"research"' not in query

    def test_empty_family_returns_empty_list(self) -> None:
        sparql = _RecordingSparql({"results": []})
        assert list_pipeline(sparql, "nonexistent-family") == []

    def test_sparql_failure_raises_pipeline_error(self) -> None:
        sparql = _RecordingSparql(RuntimeError("boom"))
        with pytest.raises(PipelineDataError, match="boom"):
            list_pipeline(sparql, "research")

    def test_skips_empty_phase_id_bindings(self) -> None:
        sparql = _RecordingSparql({"results": [
            {"phaseId": "r1-discovery-fed", "depth": "0"},
            {"phaseId": "", "depth": "1"},
            {"phaseId": "r2", "depth": "2"},
        ]})
        assert list_pipeline(sparql, "research") == ["r1-discovery-fed", "r2"]

    def test_missing_agent_family_raises(self) -> None:
        with pytest.raises(ValueError):
            list_pipeline(_RecordingSparql({"results": []}), "")


# ---------------------------------------------------------------------------
# HTTP twin (api/routes/phases.py)
# ---------------------------------------------------------------------------


class TestHandleListPipeline:
    def test_success_returns_200_with_pipeline(self) -> None:
        sparql = _RecordingSparql(_research_reply())
        status, payload = handle_list_pipeline(sparql, {"agent_family": "research"})
        assert status == 200
        assert payload == {"pipeline": list(_RESEARCH_PIPELINE)}

    def test_empty_family_returns_200_with_empty_pipeline(self) -> None:
        sparql = _RecordingSparql({"results": []})
        status, payload = handle_list_pipeline(sparql, {"agent_family": "ghost"})
        assert status == 200
        assert payload == {"pipeline": []}

    def test_missing_agent_family_returns_404(self) -> None:
        sparql = _RecordingSparql({"results": []})
        status, payload = handle_list_pipeline(sparql, {})
        assert status == 404
        assert payload == {"error": "missing agent_family"}

    def test_none_body_returns_404(self) -> None:
        status, payload = handle_list_pipeline(_RecordingSparql({"results": []}), None)
        assert status == 404
        assert payload == {"error": "missing agent_family"}

    def test_non_string_agent_family_returns_404(self) -> None:
        status, payload = handle_list_pipeline(
            _RecordingSparql({"results": []}), {"agent_family": 42},
        )
        assert status == 404
        assert payload == {"error": "missing agent_family"}


# ---------------------------------------------------------------------------
# OntologyPort default implementation
# ---------------------------------------------------------------------------


class _StubPort(OntologyPort):
    """Minimal OntologyPort whose sparql_query is driven by a recorded reply."""

    def __init__(self, sparql: _RecordingSparql) -> None:
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


class TestOntologyPortListPipeline:
    def test_default_implementation_returns_research_pipeline(self) -> None:
        port = _StubPort(_RecordingSparql(_research_reply()))
        assert port.list_pipeline("research") == list(_RESEARCH_PIPELINE)

    def test_default_implementation_query_targets_phases_graph(self) -> None:
        sparql = _RecordingSparql(_research_reply())
        port = _StubPort(sparql)
        port.list_pipeline("research")
        assert sparql.last_query is not None
        assert f"GRAPH <{PHASES_GRAPH}>" in sparql.last_query
        assert f"<{PHASE_NS}upstreamPhase>+" in sparql.last_query

    def test_default_implementation_empty_family(self) -> None:
        port = _StubPort(_RecordingSparql({"results": []}))
        assert port.list_pipeline("nonexistent") == []

    def test_default_implementation_rejects_empty_agent_family(self) -> None:
        port = _StubPort(_RecordingSparql({"results": []}))
        with pytest.raises(ValueError):
            port.list_pipeline("")
