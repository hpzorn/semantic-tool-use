"""Tests for the consolidated MCP tools (MIGRATION.md P0).

Covers store_facts, forget_facts, get_stats, recall_facts(since_hours=) and the
render_phase_spec phase-tool dispatcher. Old tools remain registered alongside
these (additive consolidation); other tests continue to cover them.

The memory/stats tools are registered by _register_knowledge_graph_tools, which
is kg-gated, so all of these use the kg-backed server fixture.
"""

import pytest

from ontology_server.config import Settings
from ontology_server.core.store import OntologyStore
from ontology_server.core.validation import SHACLValidator
from ontology_server.mcp.server import create_mcp_server


@pytest.fixture
def kgserver(store: OntologyStore, settings: Settings):
    from knowledge_graph import KnowledgeGraphStore

    validator = SHACLValidator(settings.shapes_path)
    return create_mcp_server(settings, store, validator, kg_store=KnowledgeGraphStore())


def _fn(srv, name):
    return srv._tool_manager.get_tool(name).fn


class TestConsolidatedMemoryTools:
    def test_canonical_and_legacy_tools_coexist(self, kgserver):
        names = set(kgserver._tool_manager._tools)
        assert {"store_facts", "forget_facts", "get_stats"} <= names
        assert {"store_fact", "store_facts_bulk", "forget_fact",
                "forget_by_context", "get_memory_stats"} <= names

    def test_store_facts_is_list_based(self, kgserver):
        res = _fn(kgserver, "store_facts")(
            facts=[
                {"subject": "s1", "predicate": "p", "object": "o1"},
                {"subject": "s2", "predicate": "p", "object": "o2", "confidence": 0.5},
            ],
            context="ctx-test",
        )
        assert res["stored"] == 2
        assert res["errors"] == []

    def test_recall_facts_since_hours(self, kgserver):
        _fn(kgserver, "store_facts")(
            facts=[{"subject": "rs", "predicate": "p", "object": "o"}],
            context="ctx-recent",
        )
        recall = _fn(kgserver, "recall_facts")
        assert isinstance(recall(since_hours=24), list)
        assert isinstance(recall(context="ctx-recent"), list)

    def test_forget_facts_requires_exactly_one_selector(self, kgserver):
        forget = _fn(kgserver, "forget_facts")
        assert "error" in forget()
        assert "error" in forget(fact_id="x", context="y")

    def test_forget_facts_by_context(self, kgserver):
        _fn(kgserver, "store_facts")(
            facts=[{"subject": "fs", "predicate": "p", "object": "o"}],
            context="ctx-forget",
        )
        res = _fn(kgserver, "forget_facts")(context="ctx-forget")
        assert res["status"] == "forgotten"
        assert res["context"] == "ctx-forget"

    def test_get_stats_scopes(self, kgserver):
        get_stats = _fn(kgserver, "get_stats")
        assert "fact_count" in get_stats(scope="memory")
        assert isinstance(get_stats(scope="ralph"), dict)
        assert "error" in get_stats(scope="bogus")


class TestRenderPhaseSpec:
    def test_registered_with_kg(self, kgserver):
        assert "render_phase_spec" in kgserver._tool_manager._tools

    def test_unknown_section_raises(self, kgserver):
        with pytest.raises(ValueError):
            _fn(kgserver, "render_phase_spec")(phase_id="d1", section="nonsense")

    def test_valid_section_returns_str(self, kgserver):
        render = _fn(kgserver, "render_phase_spec")
        assert isinstance(render(phase_id="d1", section="gates"), str)
        assert isinstance(render(phase_id="d1", section="all"), str)
