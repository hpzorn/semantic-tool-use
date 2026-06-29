"""Tests for the consolidated MCP tools (MIGRATION.md P0).

Covers store_facts, forget_facts, get_stats, recall_facts(since_hours=) and the
render_phase_spec phase-tool dispatcher. Old tools remain registered alongside
these. P3 removed the legacy duplicates entirely (no deprecation window).

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
    def test_canonical_tools_present_legacy_removed(self, kgserver):
        names = set(kgserver._tool_manager._tools)
        assert {"store_facts", "forget_facts", "get_stats"} <= names
        # P3: legacy duplicates fully removed (no deprecation window)
        assert not ({"store_fact", "store_facts_bulk", "forget_fact",
                     "forget_by_context", "get_memory_stats", "recall_recent_facts",
                     "get_graph_stats", "get_ralph_status"} & names)

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


class TestKeepPlusParams:
    """P3 KEEP+ params that absorbed dropped wrapper tools."""

    def test_get_idea_markdown_format(self, kgserver):
        create = _fn(kgserver, "create_idea")
        new = create(title="Param Idea", description="d", content="body text")
        get_idea = _fn(kgserver, "get_idea")
        md = get_idea(idea_id=new["id"], format="markdown")
        assert isinstance(md, str)
        assert md.startswith("---")
        assert "# Param Idea" in md
        # default still returns the metadata dict
        assert isinstance(get_idea(idea_id=new["id"]), dict)

    def test_query_ideas_wikidata_filter(self, kgserver):
        # routes through ideas_store.get_ideas_by_wikidata; empty graph -> []
        res = _fn(kgserver, "query_ideas")(wikidata="Q42")
        assert isinstance(res, list)

    def test_legacy_idea_wrappers_removed(self, kgserver):
        names = set(kgserver._tool_manager._tools)
        assert not ({"create_sub_idea", "crystallize_seed", "capture_seed",
                     "read_seed", "list_seeds", "export_idea_markdown",
                     "move_to_backlog", "get_ideas_by_lifecycle",
                     "list_by_author", "get_ideas_by_wikidata",
                     "get_related_ideas", "update_triple"} & names)

    def test_wikidata_tools_removed_from_ontology_server(self, kgserver):
        names = set(kgserver._tool_manager._tools)
        assert not ({"lookup_wikidata", "query_wikidata",
                     "search_wikidata_cache", "get_wikidata_stats"} & names)

    def test_validate_ontology_quality_summary(self, mcp_server):
        fn = mcp_server._tool_manager.get_tool("validate_ontology_quality").fn
        res = fn(ontology_uri="ontology://test/sample", summary=True)
        # summary mode returns the grouped shape (or a not-found error)
        assert "by_severity" in res or "error" in res

    def test_render_phase_spec_replaces_render_tools(self, kgserver):
        names = set(kgserver._tool_manager._tools)
        assert "render_phase_spec" in names
        assert not ({"render_gates_tool", "render_methodology_tool",
                     "render_tools_tool", "render_input_contract_tool",
                     "render_output_contract_tool", "render_phase_prompt_tool"} & names)


@pytest.fixture
def mcp_server(store, settings):
    validator = SHACLValidator(settings.shapes_path)
    return create_mcp_server(settings, store, validator)
