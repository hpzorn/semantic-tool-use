"""Change-log core tests: reified change records in the changes graph."""

from __future__ import annotations

import time

from knowledge_graph.core.changelog import (
    get_history,
    get_history_for_targets,
    new_batch_id,
    recent_changes,
    record_change,
)
from knowledge_graph.core.store import (
    GRAPH_CHANGES,
    KnowledgeGraphStore,
    NAMESPACES,
)

TARGET = "http://tulla.dev/phase#idea-1-p1"


def _store() -> KnowledgeGraphStore:
    return KnowledgeGraphStore()


class TestRecordChange:
    def test_record_writes_reified_change(self) -> None:
        store = _store()
        uri = record_change(
            store,
            target=TARGET, target_graph="http://semantic-tool-use.org/graphs/phases",
            field="target_audience", old="devs", new="ops",
            changed_by="hzorn", entity_kind="phase_output",
            predicate="http://tulla.dev/phase#preserves-target_audience",
            reason="scope shift",
        )
        rows = get_history(store, TARGET)
        assert len(rows) == 1
        row = rows[0]
        assert row["change_uri"] == uri
        assert row["field"] == "target_audience"
        assert row["old"] == "devs"
        assert row["new"] == "ops"
        assert row["by"] == "hzorn"
        assert row["reason"] == "scope shift"
        assert row["entity_kind"] == "phase_output"

    def test_absent_old_value_is_omitted(self) -> None:
        store = _store()
        record_change(
            store, target=TARGET, target_graph="default",
            field="vision", old=None, new="a vision",
            changed_by="dashboard", entity_kind="idea",
        )
        row = get_history(store, TARGET)[0]
        assert row["old"] is None
        # No oldValue triple at all in the graph.
        assert not store.ask(
            f"ASK {{ GRAPH <{GRAPH_CHANGES}> {{ "
            f"?c <{NAMESPACES['change']}oldValue> ?o . }} }}"
        )

    def test_batch_id_shared_across_edits(self) -> None:
        store = _store()
        batch = new_batch_id()
        for field in ("title", "description"):
            record_change(
                store, target=TARGET, target_graph="default",
                field=field, old="x", new="y",
                changed_by="dashboard", entity_kind="idea", batch_id=batch,
            )
        rows = get_history(store, TARGET)
        assert {r["batch"] for r in rows} == {batch}

    def test_large_json_value_verbatim(self) -> None:
        store = _store()
        blob = '[{"feature_id": "F1", "name": "with \\"quotes\\"\\nand newline"}]'
        record_change(
            store, target=TARGET, target_graph="g",
            field="feature_scope", old=None, new=blob,
            changed_by="dashboard", entity_kind="phase_output",
        )
        assert get_history(store, TARGET)[0]["new"] == blob


class TestHistoryQueries:
    def test_history_most_recent_first(self) -> None:
        store = _store()
        record_change(
            store, target=TARGET, target_graph="g", field="f",
            old="v1", new="v2", changed_by="a", entity_kind="idea",
        )
        time.sleep(0.01)
        record_change(
            store, target=TARGET, target_graph="g", field="f",
            old="v2", new="v3", changed_by="a", entity_kind="idea",
        )
        rows = get_history(store, TARGET)
        assert [r["new"] for r in rows] == ["v3", "v2"]

    def test_history_scoped_to_target(self) -> None:
        store = _store()
        record_change(
            store, target=TARGET, target_graph="g", field="f",
            old=None, new="x", changed_by="a", entity_kind="idea",
        )
        record_change(
            store, target="http://other", target_graph="g", field="f",
            old=None, new="y", changed_by="a", entity_kind="idea",
        )
        assert len(get_history(store, TARGET)) == 1

    def test_history_for_targets_unions(self) -> None:
        store = _store()
        facts = [f"http://semantic-tool-use.org/memory/fact/f{i}" for i in (1, 2)]
        for f in facts:
            record_change(
                store, target=f, target_graph="mem", field="prd:title",
                old=None, new="t", changed_by="a", entity_kind="fact",
            )
        assert len(get_history_for_targets(store, facts)) == 2
        assert get_history_for_targets(store, []) == []

    def test_recent_changes_kind_filter(self) -> None:
        store = _store()
        record_change(
            store, target=TARGET, target_graph="g", field="f",
            old=None, new="x", changed_by="a", entity_kind="idea",
        )
        record_change(
            store, target=TARGET, target_graph="g", field="f2",
            old=None, new="y", changed_by="a", entity_kind="fact",
        )
        assert len(recent_changes(store)) == 2
        only_facts = recent_changes(store, entity_kind="fact")
        assert [r["field"] for r in only_facts] == ["f2"]
