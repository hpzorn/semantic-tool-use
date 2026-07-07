"""AgentMemory.update_fact tests: in-place edits + change tracking.

PRD requirements are memory facts, so this is also the PRD edit path —
the last test proves an edited prd:title shows up via the dashboard's
requirement query.
"""

from __future__ import annotations

import pytest

from knowledge_graph.core.changelog import get_history
from knowledge_graph.core.memory import AgentMemory, MemoryFact
from knowledge_graph.core.store import KnowledgeGraphStore, NAMESPACES

MEMORY = NAMESPACES["memory"]


@pytest.fixture()
def store() -> KnowledgeGraphStore:
    return KnowledgeGraphStore()


@pytest.fixture()
def memory(store: KnowledgeGraphStore) -> AgentMemory:
    return AgentMemory(store)


@pytest.fixture()
def fact_id(memory: AgentMemory) -> str:
    return memory.store_fact(MemoryFact(
        subject="prd:req-1-1", predicate="prd:title",
        object="Original requirement title",
        context="prd-idea-701", confidence=0.9, agent="P6_prd_export",
    ))


class TestUpdateFact:
    def test_object_updated_in_place(self, memory, fact_id) -> None:
        before = memory.get_fact(fact_id)
        updated = memory.update_fact(
            fact_id, new_object="Sharper requirement title",
            changed_by="hzorn", reason="clarity",
        )
        assert updated["object"] == "Sharper requirement title"
        # Identity + original provenance preserved.
        assert updated["fact_id"] == fact_id
        assert updated["timestamp"] == before["timestamp"]
        assert updated["updated_at"] is not None

    def test_original_attribution_preserved(self, store, memory, fact_id) -> None:
        memory.update_fact(fact_id, new_object="x", changed_by="hzorn")
        uri = f"{MEMORY}fact/{fact_id}"
        assert store.ask(
            f"ASK {{ GRAPH <{memory._graph}> {{ "
            f"<{uri}> <{NAMESPACES['prov']}wasAttributedTo> "
            f"<{NAMESPACES['agents']}P6_prd_export> . }} }}"
        )

    def test_change_recorded_with_predicate_as_field(
        self, store, memory, fact_id,
    ) -> None:
        memory.update_fact(
            fact_id, new_object="New title", changed_by="hzorn",
        )
        rows = get_history(store, f"{MEMORY}fact/{fact_id}")
        assert len(rows) == 1
        assert rows[0]["field"] == "prd:title"
        assert rows[0]["old"] == "Original requirement title"
        assert rows[0]["new"] == "New title"
        assert rows[0]["entity_kind"] == "fact"

    def test_confidence_update(self, store, memory, fact_id) -> None:
        updated = memory.update_fact(
            fact_id, new_confidence=0.5, changed_by="hzorn",
        )
        assert updated["confidence"] == 0.5
        rows = get_history(store, f"{MEMORY}fact/{fact_id}")
        assert rows[0]["field"] == "confidence"

    def test_noop_records_nothing(self, store, memory, fact_id) -> None:
        updated = memory.update_fact(
            fact_id, new_object="Original requirement title",
        )
        assert updated["updated_at"] is None
        assert get_history(store, f"{MEMORY}fact/{fact_id}") == []

    def test_missing_fact_raises(self, memory) -> None:
        with pytest.raises(ValueError, match="does not exist"):
            memory.update_fact("nope1234", new_object="x")

    def test_recall_reflects_edit(self, memory, fact_id) -> None:
        memory.update_fact(fact_id, new_object="Edited")
        facts = memory.recall(context="prd-idea-701")
        assert [f["object"] for f in facts] == ["Edited"]


class TestPrdRequirementEditPath:
    def test_prd_page_query_sees_edit(self, store, memory) -> None:
        """DashboardService.get_prd_requirements-shaped read reflects the
        in-place edit (fact identity stable)."""
        memory.store_fact(MemoryFact(
            subject="prd:req-1-1", predicate="rdf:type",
            object="prd:Requirement", context="prd-idea-702",
        ))
        title_id = memory.store_fact(MemoryFact(
            subject="prd:req-1-1", predicate="prd:title",
            object="Old title", context="prd-idea-702",
        ))
        memory.update_fact(title_id, new_object="New title")
        rows = memory.recall(context="prd-idea-702", subject="prd:req-1-1")
        titles = [r["object"] for r in rows if r["predicate"] == "prd:title"]
        assert titles == ["New title"]
