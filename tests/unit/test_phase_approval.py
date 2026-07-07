"""HITL phase-approval tests over the REAL stack.

Wires a real in-memory KnowledgeGraphStore seeded from
tulla/ontologies/phase-content.trig with the real SHACLValidator, and proves:

1. record_phase_result writes approvalStatus "pending" on HITL gate points
   (phase:requiresApproval) and "approved" everywhere else, plus recordedAt,
2. completion queries shaped like the orchestrator's Query A exclude
   pending/rejected but include approved AND legacy (pre-HITL, no status)
   outputs,
3. approve/reject decision semantics: reviewer metadata, mandatory rejection
   comment, conflict on double-decisions, re-record wipes a rejection,
4. edit-then-approve re-runs the SHACL gate and restores the original
   literals when the edit violates the shape — the pending output survives,
5. requiresApproval is toggleable and the ablation switch always
   auto-approves.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from knowledge_graph.core.store import KnowledgeGraphStore, GRAPH_PHASES
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
    get_approval,
    list_pending_approvals,
    reject_phase,
    set_requires_approval,
)
from ontology_server.phase_constants import (
    APPROVAL_STATUS_PRED,
    EDITED_BY_REVIEWER_PRED,
    RECORDED_AT_PRED,
    REVIEW_COMMENT_PRED,
    REVIEWED_BY_PRED,
)

TRIG_PATH = (
    Path(__file__).resolve().parents[2] / "tulla" / "ontologies" / "phase-content.trig"
)

P1_OK = {
    "completed": True,
    "discovery_summary": "A summary of discovery.",
    "target_audience": "internal dev teams",
    "feature_scope": [
        {"feature_id": "F1", "name": "Graph export", "priority": "P0"},
        {"feature_id": "F2", "name": "Coverage gate", "priority": "P0"},
    ],
    "mandatory_feature_coverage": [
        {"mandatory_feature": "graph export", "covered_by": "F1"},
        {"mandatory_feature": "coverage gate", "covered_by": "F2"},
    ],
    "uncovered_mandatory_features": [],
    "out_of_scope": ["mobile app"],
    "scope_decisions": ["defer mobile"],
    "non_negotiable_constraints": ["offline-first"],
    "success_metrics": ["100% mandatory feature retention"],
    "jtbd_traceability": [{"feature": "F1", "persona": "dev", "jtbd": "trace"}],
    "scope_boundaries": {"in_scope": ["F1", "F2"], "out_of_scope": ["mobile"]},
}


@pytest.fixture()
def kg_store() -> KnowledgeGraphStore:
    store = KnowledgeGraphStore()
    assert seed_phase_content(store, TRIG_PATH) > 0
    return store


@pytest.fixture()
def client(kg_store: KnowledgeGraphStore) -> KGOntologyClient:
    return KGOntologyClient(kg_store, SHACLValidator())


def _literal(kg_store: KnowledgeGraphStore, subject: str, predicate: str) -> str | None:
    result = kg_store.query(
        f"SELECT ?o WHERE {{ GRAPH <{GRAPH_PHASES}> {{ "
        f"<{subject}> <{predicate}> ?o . }} }}"
    )
    return str(result.bindings[0]["o"]) if result.bindings else None


def _completed_phase_ids(kg_store: KnowledgeGraphStore, idea_id: str) -> set[str]:
    """The orchestrator's Query A shape, with the HITL approval filter."""
    result = kg_store.query(
        f"SELECT DISTINCT ?phase_id WHERE {{ GRAPH <{GRAPH_PHASES}> {{\n"
        f"  ?output <{PHASE_NS}producedBy> ?phase_id ;\n"
        f'          <{PHASE_NS}forRequirement> "{idea_id}" .\n'
        f"  FILTER NOT EXISTS {{\n"
        f"    ?output <{APPROVAL_STATUS_PRED}> ?st .\n"
        f'    FILTER(?st IN ("pending","rejected"))\n'
        f"  }}\n"
        f"}} }}"
    )
    return {str(b["phase_id"]) for b in result.bindings}


# ---------------------------------------------------------------------------
# Recording writes approval status
# ---------------------------------------------------------------------------


class TestRecordWritesApprovalStatus:
    def test_flagged_phase_records_pending(self, client, kg_store) -> None:
        out = record_phase_result(client, "p1", "910", "", P1_OK)
        assert out["ok"] is True
        assert out["approval"] == "pending"
        subject = f"{PHASE_NS}idea-910-p1"
        assert _literal(kg_store, subject, APPROVAL_STATUS_PRED) == "pending"
        assert _literal(kg_store, subject, RECORDED_AT_PRED)

    def test_unflagged_phase_records_approved(self, client, kg_store) -> None:
        set_requires_approval(client, "p1", False)
        out = record_phase_result(client, "p1", "911", "", P1_OK)
        assert out["approval"] == "approved"
        subject = f"{PHASE_NS}idea-911-p1"
        assert _literal(kg_store, subject, APPROVAL_STATUS_PRED) == "approved"

    def test_ship_defaults_flag_d5_p1_p6(self, kg_store) -> None:
        for phase_id in ("d5", "p1", "p6"):
            flag = _literal(
                kg_store, f"{PHASE_NS}{phase_id}", f"{PHASE_NS}requiresApproval",
            )
            assert flag == "true", f"{phase_id} should ship as a HITL gate point"

    def test_ablation_mode_always_approves(self, client, kg_store, monkeypatch) -> None:
        monkeypatch.setitem(os.environ, "ONTOLOGY_DISABLE_GATES", "1")
        out = record_phase_result(client, "p1", "912", "", {"completed": True})
        assert out["gate_skipped"] is True
        assert out["approval"] == "approved"


# ---------------------------------------------------------------------------
# Completion semantics (orchestrator Query A shape)
# ---------------------------------------------------------------------------


class TestCompletionExcludesUndecided:
    def test_pending_and_rejected_do_not_count(self, client, kg_store) -> None:
        record_phase_result(client, "p1", "920", "", P1_OK)  # pending
        assert _completed_phase_ids(kg_store, "idea-920") == set()

        reject_phase(client, client, "920", "p1", "scope too broad")
        assert _completed_phase_ids(kg_store, "idea-920") == set()

        approve_phase(client, client, "920", "p1")
        assert _completed_phase_ids(kg_store, "idea-920") == {"p1"}

    def test_legacy_output_without_status_counts(self, client, kg_store) -> None:
        # Pre-HITL output: producedBy/forRequirement but no approvalStatus.
        subject = f"{PHASE_NS}idea-921-p1"
        kg_store.add_triple(
            subject, f"{PHASE_NS}producedBy", "p1",
            is_literal=True, graph=GRAPH_PHASES,
        )
        kg_store.add_triple(
            subject, f"{PHASE_NS}forRequirement", "idea-921",
            is_literal=True, graph=GRAPH_PHASES,
        )
        assert _completed_phase_ids(kg_store, "idea-921") == {"p1"}
        state = get_approval(client, "921", "p1")
        assert state is not None and state["status"] == "approved"


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------


class TestDecisions:
    def test_approve_writes_reviewer_metadata(self, client, kg_store) -> None:
        record_phase_result(client, "p1", "930", "", P1_OK)
        out = approve_phase(
            client, client, "930", "p1",
            reviewed_by="hzorn", comment="looks right",
        )
        assert out == {"ok": True, "violations": [], "status": "approved"}
        subject = f"{PHASE_NS}idea-930-p1"
        assert _literal(kg_store, subject, REVIEWED_BY_PRED) == "hzorn"
        assert _literal(kg_store, subject, REVIEW_COMMENT_PRED) == "looks right"

    def test_reject_requires_comment(self, client) -> None:
        record_phase_result(client, "p1", "931", "", P1_OK)
        with pytest.raises(ValueError):
            reject_phase(client, client, "931", "p1", "   ")

    def test_reject_then_rerecord_yields_fresh_pending(self, client, kg_store) -> None:
        record_phase_result(client, "p1", "932", "", P1_OK)
        reject_phase(client, client, "932", "p1", "wrong audience")
        state = get_approval(client, "932", "p1")
        assert state["status"] == "rejected"
        assert state["comment"] == "wrong audience"

        # The agent re-run: idempotent cleanup replaces the whole subject.
        record_phase_result(client, "p1", "932", "", P1_OK)
        state = get_approval(client, "932", "p1")
        assert state["status"] == "pending"
        assert state["comment"] is None

    def test_double_approve_conflicts(self, client) -> None:
        record_phase_result(client, "p1", "933", "", P1_OK)
        approve_phase(client, client, "933", "p1")
        with pytest.raises(ApprovalConflictError):
            approve_phase(client, client, "933", "p1")

    def test_reject_approved_output_conflicts(self, client) -> None:
        record_phase_result(client, "p1", "934", "", P1_OK)
        approve_phase(client, client, "934", "p1")
        with pytest.raises(ApprovalConflictError):
            reject_phase(client, client, "934", "p1", "too late")

    def test_decision_without_output_conflicts(self, client) -> None:
        with pytest.raises(ApprovalConflictError):
            approve_phase(client, client, "935", "p1")

    def test_rejected_output_can_be_approved(self, client) -> None:
        """A reviewer can reverse a rejection without an agent re-run."""
        record_phase_result(client, "p1", "936", "", P1_OK)
        reject_phase(client, client, "936", "p1", "hold on")
        out = approve_phase(client, client, "936", "p1")
        assert out["status"] == "approved"

    def test_list_pending_approvals(self, client) -> None:
        record_phase_result(client, "p1", "937", "", P1_OK)
        record_phase_result(client, "p1", "938", "", P1_OK)
        approve_phase(client, client, "938", "p1")
        pending = list_pending_approvals(client)
        assert [(p["idea_id"], p["phase_id"]) for p in pending] == [
            ("idea-937", "p1"),
        ]


# ---------------------------------------------------------------------------
# Edit-then-approve
# ---------------------------------------------------------------------------


class TestEditThenApprove:
    def test_valid_edit_persists_and_marks_edited(self, client, kg_store) -> None:
        record_phase_result(client, "p1", "940", "", P1_OK)
        out = approve_phase(
            client, client, "940", "p1",
            edited_fields={"target_audience": "external customers"},
        )
        assert out["ok"] is True
        subject = f"{PHASE_NS}idea-940-p1"
        assert _literal(
            kg_store, subject, f"{PHASE_NS}preserves-target_audience",
        ) == "external customers"
        assert _literal(kg_store, subject, EDITED_BY_REVIEWER_PRED) == "true"

    def test_gate_violating_edit_restores_original(self, client, kg_store) -> None:
        record_phase_result(client, "p1", "941", "", P1_OK)
        # P1's shape requires uncovered_mandatory_features sh:hasValue "[]".
        out = approve_phase(
            client, client, "941", "p1",
            edited_fields={"uncovered_mandatory_features": '["graph export"]'},
        )
        assert out["ok"] is False
        assert out["violations"]
        subject = f"{PHASE_NS}idea-941-p1"
        assert _literal(
            kg_store, subject, f"{PHASE_NS}preserves-uncovered_mandatory_features",
        ) == "[]"
        # The pending output survives the failed edit intact.
        assert _literal(kg_store, subject, APPROVAL_STATUS_PRED) == "pending"

    def test_non_allowlisted_field_rejected(self, client) -> None:
        record_phase_result(client, "p1", "942", "", P1_OK)
        with pytest.raises(ValueError, match="allowlist"):
            approve_phase(
                client, client, "942", "p1",
                edited_fields={"made_up_field": "x"},
            )

    def test_json_field_edited_to_garbage_rejected(self, client) -> None:
        record_phase_result(client, "p1", "943", "", P1_OK)
        with pytest.raises(ValueError, match="JSON"):
            approve_phase(
                client, client, "943", "p1",
                edited_fields={"feature_scope": "not json {"},
            )


# ---------------------------------------------------------------------------
# requiresApproval toggle
# ---------------------------------------------------------------------------


class TestRequiresApprovalToggle:
    def test_toggle_round_trip(self, client, kg_store) -> None:
        subject = f"{PHASE_NS}p2"
        assert _literal(kg_store, subject, f"{PHASE_NS}requiresApproval") is None
        set_requires_approval(client, "p2", True)
        assert _literal(kg_store, subject, f"{PHASE_NS}requiresApproval") == "true"
        set_requires_approval(client, "p2", False)
        assert _literal(kg_store, subject, f"{PHASE_NS}requiresApproval") == "false"

    def test_reseed_restores_ship_defaults(self, client, kg_store) -> None:
        """The flag lives on a trig-declared subject: a re-seed (probe absent)
        resets operator toggles to ship defaults — documented trade-off."""
        set_requires_approval(client, "d5", False)
        kg_store.remove_triple(
            subject=f"{PHASE_NS}d5",
            predicate=f"{PHASE_NS}requiresApproval",
            graph=GRAPH_PHASES,
        )
        assert seed_phase_content(kg_store, TRIG_PATH) > 0
        assert _literal(
            kg_store, f"{PHASE_NS}d5", f"{PHASE_NS}requiresApproval",
        ) == "true"
