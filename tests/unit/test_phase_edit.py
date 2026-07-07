"""edit_phase_output tests: field edits at any approval status + changelog.

Real-store stack (seeded trig + SHACLValidator), proving:
- approved outputs are editable; approvalStatus never changes,
- gate-violating edits restore literals and record NOTHING,
- applied edits land in the change graph with old/new values,
- staleness = consuming phases that already recorded outputs for the idea,
- the review-flow approve-with-edit also records changes when kg_store given.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_graph.core.changelog import get_history, recent_changes
from knowledge_graph.core.store import KnowledgeGraphStore, GRAPH_PHASES
from ontology_server.api.routes.phases import handle_edit_phase_output
from ontology_server.core.validation import SHACLValidator
from ontology_server.mcp.phase_tools import (
    KGOntologyClient,
    PHASE_NS,
    record_phase_result,
    seed_phase_content,
)
from ontology_server.phase_approval import (
    ApprovalConflictError,
    approve_phase,
    consumers_of_fields,
    edit_phase_output,
    get_approval,
    stale_downstream_phases,
)

TRIG_PATH = (
    Path(__file__).resolve().parents[2] / "tulla" / "ontologies" / "phase-content.trig"
)

P1_OK = {
    "completed": True,
    "discovery_summary": "A summary of discovery.",
    "target_audience": "internal dev teams",
    "feature_scope": [{"feature_id": "F1", "name": "X", "priority": "P0"}],
    "mandatory_feature_coverage": [
        {"mandatory_feature": "x", "covered_by": "F1"},
    ],
    "uncovered_mandatory_features": [],
    "out_of_scope": ["y"],
    "scope_decisions": ["z"],
    "non_negotiable_constraints": ["c"],
    "success_metrics": ["m"],
    "jtbd_traceability": [{"feature": "F1", "persona": "dev", "jtbd": "t"}],
    "scope_boundaries": {"in_scope": ["F1"], "out_of_scope": ["y"]},
}


@pytest.fixture()
def kg_store() -> KnowledgeGraphStore:
    store = KnowledgeGraphStore()
    assert seed_phase_content(store, TRIG_PATH) > 0
    return store


@pytest.fixture()
def client(kg_store: KnowledgeGraphStore) -> KGOntologyClient:
    return KGOntologyClient(kg_store, SHACLValidator())


@pytest.fixture()
def approved_p1(client: KGOntologyClient, kg_store) -> str:
    """An APPROVED p1 output for idea-980; returns the subject URI."""
    record_phase_result(client, "p1", "980", "", P1_OK)
    approve_phase(client, client, "980", "p1")
    return f"{PHASE_NS}idea-980-p1"


def _literal(kg_store, subject: str, predicate: str) -> str | None:
    result = kg_store.query(
        f"SELECT ?o WHERE {{ GRAPH <{GRAPH_PHASES}> {{ "
        f"<{subject}> <{predicate}> ?o . }} }}"
    )
    return str(result.bindings[0]["o"]) if result.bindings else None


class TestEditAnyStatus:
    def test_edit_approved_output(self, client, kg_store, approved_p1) -> None:
        out = edit_phase_output(
            client, client, "980", "p1",
            {"target_audience": "platform team"},
            kg_store=kg_store, changed_by="hzorn", reason="reorg",
        )
        assert out["ok"] is True
        assert out["edited_fields"] == ["target_audience"]
        assert _literal(
            kg_store, approved_p1, f"{PHASE_NS}preserves-target_audience",
        ) == "platform team"
        # Approval status untouched.
        assert get_approval(client, "980", "p1")["status"] == "approved"

    def test_edit_records_change_with_old_and_new(
        self, client, kg_store, approved_p1,
    ) -> None:
        edit_phase_output(
            client, client, "980", "p1",
            {"target_audience": "platform team"},
            kg_store=kg_store, changed_by="hzorn", reason="reorg",
        )
        rows = get_history(kg_store, approved_p1)
        assert len(rows) == 1
        assert rows[0]["old"] == "internal dev teams"
        assert rows[0]["new"] == "platform team"
        assert rows[0]["by"] == "hzorn"
        assert rows[0]["reason"] == "reorg"
        assert rows[0]["entity_kind"] == "phase_output"

    def test_violating_edit_restores_and_records_nothing(
        self, client, kg_store, approved_p1,
    ) -> None:
        out = edit_phase_output(
            client, client, "980", "p1",
            {"uncovered_mandatory_features": '["dropped"]'},
            kg_store=kg_store,
        )
        assert out["ok"] is False
        assert out["violations"]
        assert _literal(
            kg_store, approved_p1,
            f"{PHASE_NS}preserves-uncovered_mandatory_features",
        ) == "[]"
        assert get_history(kg_store, approved_p1) == []

    def test_noop_edit_records_nothing(self, client, kg_store, approved_p1) -> None:
        out = edit_phase_output(
            client, client, "980", "p1",
            {"target_audience": "internal dev teams"},  # unchanged
            kg_store=kg_store,
        )
        assert out["ok"] is True
        assert out["edited_fields"] == []
        assert get_history(kg_store, approved_p1) == []

    def test_missing_output_conflicts(self, client, kg_store) -> None:
        with pytest.raises(ApprovalConflictError):
            edit_phase_output(
                client, client, "981", "p1", {"target_audience": "x"},
                kg_store=kg_store,
            )

    def test_batched_edits_share_batch(self, client, kg_store, approved_p1) -> None:
        edit_phase_output(
            client, client, "980", "p1",
            {"target_audience": "a", "discovery_summary": "New summary."},
            kg_store=kg_store,
        )
        rows = get_history(kg_store, approved_p1)
        assert len(rows) == 2
        assert len({r["batch"] for r in rows}) == 1


class TestStaleness:
    def test_consumers_reverse_lookup(self) -> None:
        consumers = consumers_of_fields(["mandatory_features"])
        # D5's mandatory_features feed P1 (and possibly others).
        assert "p1" in consumers["mandatory_features"]

    def test_stale_only_lists_recorded_consumers(self, client, kg_store) -> None:
        record_phase_result(client, "d5", "982", "", {
            "mode": "plan", "recommendation": "go", "northstar": "n",
            "mandatory_features": ["graph export"], "research_questions": [],
        })
        # No p1 output yet → consumers exist but nothing is stale.
        assert stale_downstream_phases(client, "982", ["mandatory_features"]) == []
        record_phase_result(client, "p1", "982", "", P1_OK)
        stale = stale_downstream_phases(client, "982", ["mandatory_features"])
        assert stale == ["p1"]

    def test_edit_returns_stale_phases(self, client, kg_store) -> None:
        record_phase_result(client, "d5", "983", "", {
            "mode": "plan", "recommendation": "go", "northstar": "n",
            "mandatory_features": ["graph export"], "research_questions": [],
        })
        record_phase_result(client, "p1", "983", "", P1_OK)
        out = edit_phase_output(
            client, client, "983", "d5",
            {"mandatory_features": '["f", "g"]'},
            kg_store=kg_store,
        )
        assert out["ok"] is True
        assert "p1" in out["stale_phases"]
        assert "p1" in out["consumers"]["mandatory_features"]


class TestApproveWithEditRecordsChanges:
    def test_review_flow_edit_is_logged(self, client, kg_store) -> None:
        record_phase_result(client, "p1", "984", "", P1_OK)
        approve_phase(
            client, client, "984", "p1",
            reviewed_by="hzorn",
            edited_fields={"target_audience": "external"},
            kg_store=kg_store,
        )
        rows = get_history(kg_store, f"{PHASE_NS}idea-984-p1")
        assert len(rows) == 1 and rows[0]["new"] == "external"

    def test_plain_approve_logs_nothing(self, client, kg_store) -> None:
        record_phase_result(client, "p1", "985", "", P1_OK)
        approve_phase(client, client, "985", "p1", kg_store=kg_store)
        assert recent_changes(kg_store) == []


class TestRestHandler:
    def test_edit_endpoint_matrix(self, client, kg_store, approved_p1) -> None:
        ok_status, payload = handle_edit_phase_output(
            client, kg_store,
            {"idea_id": "980", "phase_id": "p1",
             "edited_fields": {"target_audience": "ops"}},
        )
        assert ok_status == 200 and payload["ok"] is True

        assert handle_edit_phase_output(
            client, kg_store, {"idea_id": "980", "phase_id": "p1"},
        )[0] == 400  # no edited_fields
        assert handle_edit_phase_output(
            client, kg_store,
            {"idea_id": "980", "phase_id": "p1", "edited_fields": {"a": 1}},
        )[0] == 400  # non-string value
        assert handle_edit_phase_output(
            client, kg_store,
            {"idea_id": "999x", "phase_id": "p1",
             "edited_fields": {"target_audience": "x"}},
        )[0] == 409  # no output
        assert handle_edit_phase_output(
            client, kg_store, {"phase_id": "p1"},
        )[0] == 404  # missing idea_id

        gate_status, gate_payload = handle_edit_phase_output(
            client, kg_store,
            {"idea_id": "980", "phase_id": "p1",
             "edited_fields": {"uncovered_mandatory_features": '["x"]'}},
        )
        assert gate_status == 422 and gate_payload["violations"]
