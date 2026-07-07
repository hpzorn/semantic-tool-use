"""update_idea_fields tests: targeted idea edits + change tracking."""

from __future__ import annotations

import json

import pytest

from knowledge_graph.core.changelog import get_history
from knowledge_graph.core.ideas import Idea, IdeasStore
from knowledge_graph.core.store import KnowledgeGraphStore, NAMESPACES

DCTERMS = NAMESPACES["dcterms"]
IDEAS = NAMESPACES["ideas"]


@pytest.fixture()
def store() -> KnowledgeGraphStore:
    return KnowledgeGraphStore()


@pytest.fixture()
def ideas(store: KnowledgeGraphStore) -> IdeasStore:
    ideas_store = IdeasStore(store)
    ideas_store.create_idea(Idea(
        id="idea-700", title="Original title",
        description="Original description",
        tags=["alpha"], priority=2,
    ))
    return ideas_store


class TestUpdateIdeaFields:
    def test_text_edit_persists_and_logs(self, store, ideas) -> None:
        changed = ideas.update_idea_fields(
            "idea-700", {"title": "Better title"}, changed_by="hzorn",
        )
        assert changed == ["title"]
        assert ideas.get_idea("idea-700").title == "Better title"

        rows = get_history(store, f"{IDEAS}idea-700")
        assert len(rows) == 1
        assert rows[0]["old"] == "Original title"
        assert rows[0]["new"] == "Better title"
        assert rows[0]["by"] == "hzorn"
        assert rows[0]["entity_kind"] == "idea"

    def test_dcterms_modified_stamped(self, store, ideas) -> None:
        ideas.update_idea_fields("idea-700", {"description": "New desc"})
        assert store.ask(
            f"ASK {{ <{IDEAS}idea-700> <{DCTERMS}modified> ?t }}"
        )

    def test_untouched_fields_survive(self, ideas) -> None:
        ideas.update_idea_fields("idea-700", {"title": "T2"})
        idea = ideas.get_idea("idea-700")
        assert idea.description == "Original description"
        assert idea.tags == ["alpha"]
        assert idea.priority == 2

    def test_noop_edit_logs_nothing(self, store, ideas) -> None:
        changed = ideas.update_idea_fields(
            "idea-700", {"title": "Original title"},
        )
        assert changed == []
        assert get_history(store, f"{IDEAS}idea-700") == []
        assert not store.ask(
            f"ASK {{ <{IDEAS}idea-700> <{DCTERMS}modified> ?t }}"
        )

    def test_tags_comma_separated(self, store, ideas) -> None:
        ideas.update_idea_fields("idea-700", {"tags": "beta, gamma"})
        assert sorted(ideas.get_idea("idea-700").tags) == ["beta", "gamma"]
        row = get_history(store, f"{IDEAS}idea-700")[0]
        assert json.loads(row["old"]) == ["alpha"]
        assert sorted(json.loads(row["new"])) == ["beta", "gamma"]

    def test_multi_field_one_per_line(self, store, ideas) -> None:
        ideas.update_idea_fields(
            "idea-700", {"requirements": "req one\nreq two\n"},
        )
        # RDF multi-values are unordered.
        assert sorted(ideas.get_idea("idea-700").requirements) == [
            "req one", "req two",
        ]

    def test_priority_int_and_clear(self, ideas) -> None:
        ideas.update_idea_fields("idea-700", {"priority": "5"})
        assert ideas.get_idea("idea-700").priority == 5
        ideas.update_idea_fields("idea-700", {"priority": ""})
        assert ideas.get_idea("idea-700").priority is None

    def test_batch_shared_across_fields(self, store, ideas) -> None:
        ideas.update_idea_fields(
            "idea-700", {"title": "T", "description": "D"},
        )
        rows = get_history(store, f"{IDEAS}idea-700")
        assert len(rows) == 2
        assert len({r["batch"] for r in rows}) == 1

    def test_empty_title_rejected(self, ideas) -> None:
        with pytest.raises(ValueError, match="title"):
            ideas.update_idea_fields("idea-700", {"title": "  "})

    def test_unknown_field_rejected(self, ideas) -> None:
        with pytest.raises(ValueError, match="not editable"):
            ideas.update_idea_fields("idea-700", {"lifecycle": "completed"})

    def test_missing_idea_rejected(self, ideas) -> None:
        with pytest.raises(ValueError, match="does not exist"):
            ideas.update_idea_fields("idea-999", {"title": "x"})
