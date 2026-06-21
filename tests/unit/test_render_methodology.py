"""Tests for the render_methodology MCP tool (req-130-2-2).

Covers the server-side function in :mod:`ontology_server.mcp.phase_tools`, the
HTTP twin in :mod:`ontology_server.api.routes.phases`, and the default port
implementation on :class:`tulla.ports.ontology.OntologyPort`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import rdflib

from ontology_server.api.routes.phases import handle_render_methodology
from ontology_server.mcp.phase_tools import (
    PHASE_NS,
    PHASES_GRAPH,
    _build_methodology_query,
    render_methodology,
)
from tulla.ports.ontology import OntologyPort


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIXTURE_TTL = Path(__file__).parent.parent / "fixtures" / "phase_content_curated.ttl"


def _load_r3_procedure_body() -> str:
    graph = rdflib.Graph()
    graph.parse(str(_FIXTURE_TTL), format="turtle")
    subject = rdflib.URIRef(f"{PHASE_NS}r3")
    predicate = rdflib.URIRef(f"{PHASE_NS}procedure")
    value = graph.value(subject=subject, predicate=predicate)
    assert value is not None, "phase:r3 phase:procedure missing from curated TTL"
    return str(value)


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


# ---------------------------------------------------------------------------
# render_methodology (mcp/phase_tools.py)
# ---------------------------------------------------------------------------


class TestRenderMethodology:
    def test_returns_r3_procedure_body(self) -> None:
        body = _load_r3_procedure_body()
        sparql = _RecordingSparql({"results": [{"proc": body}]})

        result = render_methodology(sparql, "r3")

        assert result == body
        assert PHASES_GRAPH in (sparql.last_query or "")
        assert f"<{PHASE_NS}r3>" in (sparql.last_query or "")
        assert f"<{PHASE_NS}procedure>" in (sparql.last_query or "")

    def test_query_targets_phases_graph(self) -> None:
        query = _build_methodology_query("r3")
        assert f"GRAPH <{PHASES_GRAPH}>" in query
        assert "SELECT ?proc" in query

    def test_missing_procedure_returns_empty_string_with_warning(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        sparql = _RecordingSparql({"results": []})

        with caplog.at_level("WARNING", logger="ontology_server.mcp.phase_tools"):
            result = render_methodology(sparql, "x99")

        assert result == ""
        assert any(
            "No phase:procedure literal" in rec.message for rec in caplog.records
        )

    def test_falsy_phase_id_raises(self) -> None:
        with pytest.raises(ValueError):
            render_methodology(_RecordingSparql({"results": []}), "")

    def test_sparql_failure_returns_empty(self, caplog: pytest.LogCaptureFixture) -> None:
        sparql = _RecordingSparql(RuntimeError("backend down"))
        with caplog.at_level("WARNING", logger="ontology_server.mcp.phase_tools"):
            result = render_methodology(sparql, "r3")
        assert result == ""


# ---------------------------------------------------------------------------
# HTTP twin (api/routes/phases.py)
# ---------------------------------------------------------------------------


class TestHandleRenderMethodology:
    def test_success_returns_200(self) -> None:
        body = _load_r3_procedure_body()
        sparql = _RecordingSparql({"results": [{"proc": body}]})
        status, payload = handle_render_methodology(sparql, {"phase_id": "r3"})
        assert status == 200
        assert payload == {"markdown": body}

    def test_missing_phase_id_returns_404(self) -> None:
        sparql = _RecordingSparql({"results": []})
        status, payload = handle_render_methodology(sparql, {})
        assert status == 404
        assert payload == {"error": "missing phase_id"}

    def test_none_body_returns_404(self) -> None:
        sparql = _RecordingSparql({"results": []})
        status, payload = handle_render_methodology(sparql, None)
        assert status == 404

    def test_empty_procedure_returns_200_empty_markdown(self) -> None:
        sparql = _RecordingSparql({"results": []})
        status, payload = handle_render_methodology(sparql, {"phase_id": "x99"})
        assert status == 200
        assert payload == {"markdown": ""}


# ---------------------------------------------------------------------------
# OntologyPort default implementation
# ---------------------------------------------------------------------------


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


class TestOntologyPortRenderMethodology:
    def test_default_implementation_returns_body(self) -> None:
        body = _load_r3_procedure_body()
        port = _StubPort({"results": [{"proc": body}]})
        assert port.render_methodology("r3") == body
        assert "r3" in (port.last_query or "")

    def test_default_implementation_rejects_empty_phase_id(self) -> None:
        port = _StubPort({"results": []})
        with pytest.raises(ValueError):
            port.render_methodology("")
