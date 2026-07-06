"""Workstream D tests: PROV-O structural memory scoping + cross-idea lessons.

D1: storing a fact with a per-idea context materializes REAL edges
    (memory:aboutIdea -> idea resource, memory:contextKind, PROV provenance),
    and legacy string-scoped facts are backfilled idempotently.
D2: recall_lessons retrieves lessons ACROSS ideas, filtered by file/term
    relevance (including lesson:touchesFile companion facts), excluding the
    asking idea.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from knowledge_graph.core.memory import AgentMemory, MemoryFact
from knowledge_graph.core.store import GRAPH_MEMORY, KnowledgeGraphStore

IDEAS = "http://semantic-tool-use.org/ideas/"
MEMORY = "http://semantic-tool-use.org/memory/"
PROV = "http://www.w3.org/ns/prov#"
AGENTS = "http://semantic-tool-use.org/agents/"


@pytest.fixture()
def store() -> KnowledgeGraphStore:
    return KnowledgeGraphStore()


@pytest.fixture()
def memory(store: KnowledgeGraphStore) -> AgentMemory:
    return AgentMemory(store)


def _ask(store: KnowledgeGraphStore, pattern: str) -> bool:
    return store.ask(
        f"ASK WHERE {{ GRAPH <{GRAPH_MEMORY}> {{ {pattern} }} }}"
    )


class TestStructuralScoping:
    def test_per_idea_context_gets_structural_edges(self, store, memory) -> None:
        fid = memory.store_fact(MemoryFact(
            subject="lesson:idea-7-T1.1", predicate="lesson:text",
            object="Mock the clock in limiter tests", context="lesson-idea-7",
            agent="I1_coding",
        ))
        fact = f"<{MEMORY}fact/{fid}>"
        assert _ask(store, f"{fact} <{MEMORY}aboutIdea> <{IDEAS}idea-7> .")
        assert _ask(store, f'{fact} <{MEMORY}contextKind> "lesson" .')
        assert _ask(store, f"{fact} <{PROV}wasAttributedTo> <{AGENTS}I1_coding> .")
        assert _ask(store, f"{fact} <{PROV}generatedAtTime> ?t .")

    def test_multiword_kind_parses(self, store, memory) -> None:
        fid = memory.store_fact(MemoryFact(
            subject="task:idea-9-T1.1", predicate="prd:title",
            object="x", context="p4-tasks-idea-9",
        ))
        fact = f"<{MEMORY}fact/{fid}>"
        assert _ask(store, f"{fact} <{MEMORY}aboutIdea> <{IDEAS}idea-9> .")
        assert _ask(store, f'{fact} <{MEMORY}contextKind> "p4-tasks" .')

    def test_non_idea_context_gets_no_idea_edge(self, store, memory) -> None:
        fid = memory.store_fact(MemoryFact(
            subject="s", predicate="p", object="o", context="global-notes",
        ))
        assert not _ask(store, f"<{MEMORY}fact/{fid}> <{MEMORY}aboutIdea> ?i .")

    def test_backfill_materializes_legacy_facts(self, store) -> None:
        memory = AgentMemory(store)
        # Simulate a pre-D1 fact: context string only, no structural edges.
        legacy = f"{MEMORY}fact/legacy01"
        store.add_triple(legacy, "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
                         f"{MEMORY}Fact", graph=GRAPH_MEMORY)
        for prop, val in (("subject", "lesson:idea-3"), ("predicate", "lesson:text"),
                          ("object", "old lesson"), ("context", "lesson-idea-3")):
            store.add_triple(legacy, f"{MEMORY}{prop}", val, is_literal=True,
                             graph=GRAPH_MEMORY)
        assert memory.materialize_scoping() == 1
        assert _ask(store, f"<{legacy}> <{MEMORY}aboutIdea> <{IDEAS}idea-3> .")
        # Idempotent: second run touches nothing.
        assert memory.materialize_scoping() == 0


class TestCrossIdeaLessons:
    @pytest.fixture()
    def brain(self, memory: AgentMemory) -> AgentMemory:
        t0 = datetime.now(timezone.utc)
        # idea-7: lesson about auth.py (older)
        memory.store_fact(MemoryFact(
            subject="lesson:idea-7-T2.1", predicate="lesson:text",
            object="auth.py: session middleware must be registered before routers",
            context="lesson-idea-7", agent="I1_coding",
            timestamp=t0 - timedelta(days=2),
        ))
        # idea-9: lesson whose TEXT does not mention the file, but a
        # touchesFile companion fact links it to limiter.py
        memory.store_fact(MemoryFact(
            subject="lesson:idea-9-T1.1", predicate="lesson:text",
            object="inject a fake clock; real sleeps make tests flaky",
            context="lesson-idea-9", agent="I1_coding",
            timestamp=t0 - timedelta(days=1),
        ))
        memory.store_fact(MemoryFact(
            subject="lesson:idea-9-T1.1", predicate="lesson:touchesFile",
            object="src/limiter.py", context="lesson-idea-9",
        ))
        # idea-15: the asking idea's own lesson
        memory.store_fact(MemoryFact(
            subject="lesson:idea-15-T1.1", predicate="lesson:text",
            object="loglens argparse: keep --json and --csv mutually exclusive",
            context="lesson-idea-15", agent="I1_coding", timestamp=t0,
        ))
        return memory

    def test_unfiltered_returns_all_ideas_lessons(self, brain) -> None:
        out = brain.recall_lessons()
        assert {l["idea"] for l in out} == {"idea-7", "idea-9", "idea-15"}
        # touchesFile companion facts are not lessons themselves
        assert all("touchesFile" not in (l["lesson"] or "") for l in out)
        # most recent first
        assert out[0]["idea"] == "idea-15"

    def test_exclude_own_idea(self, brain) -> None:
        out = brain.recall_lessons(exclude_idea="idea-15")
        assert {l["idea"] for l in out} == {"idea-7", "idea-9"}

    def test_file_relevance_via_text(self, brain) -> None:
        out = brain.recall_lessons(files=["src/auth.py"], exclude_idea="idea-15")
        assert [l["idea"] for l in out] == ["idea-7"]

    def test_file_relevance_via_touches_file_join(self, brain) -> None:
        out = brain.recall_lessons(files=["lib/limiter.py"], exclude_idea="idea-15")
        assert [l["idea"] for l in out] == ["idea-9"]
        assert "fake clock" in out[0]["lesson"]

    def test_term_relevance(self, brain) -> None:
        out = brain.recall_lessons(terms=["middleware"])
        assert [l["idea"] for l in out] == ["idea-7"]

    def test_single_idea_restriction(self, brain) -> None:
        out = brain.recall_lessons(idea="9")
        assert {l["idea"] for l in out} == {"idea-9"}

    def test_agent_provenance_returned(self, brain) -> None:
        out = brain.recall_lessons(idea="idea-7")
        assert out[0]["agent"] == "I1_coding"
