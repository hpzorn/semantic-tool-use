"""REST handler tests for the HITL approval endpoints.

Exercises the framework-agnostic handle_* functions in
api/routes/phases.py against the real store + validator stack, proving the
HTTP status mapping: 200 decision, 422 gate-violating edit, 400 bad input,
404 missing ids, 409 conflict.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_graph.core.store import KnowledgeGraphStore
from ontology_server.api.routes.phases import (
    handle_approve_phase,
    handle_await_approval,
    handle_get_approval_status,
    handle_reject_phase,
    handle_set_requires_approval,
)
from ontology_server.core.validation import SHACLValidator
from ontology_server.mcp.phase_tools import (
    KGOntologyClient,
    record_phase_result,
    seed_phase_content,
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
def client() -> KGOntologyClient:
    store = KnowledgeGraphStore()
    assert seed_phase_content(store, TRIG_PATH) > 0
    return KGOntologyClient(store, SHACLValidator())


@pytest.fixture()
def pending_p1(client: KGOntologyClient) -> KGOntologyClient:
    out = record_phase_result(client, "p1", "960", "", P1_OK)
    assert out["approval"] == "pending"
    return client


class TestApproveEndpoint:
    def test_approve_returns_200(self, pending_p1) -> None:
        status, payload = handle_approve_phase(
            pending_p1, {"idea_id": "960", "phase_id": "p1"},
        )
        assert status == 200
        assert payload["status"] == "approved"

    def test_gate_violating_edit_returns_422(self, pending_p1) -> None:
        status, payload = handle_approve_phase(
            pending_p1,
            {
                "idea_id": "960", "phase_id": "p1",
                "edited_fields": {"uncovered_mandatory_features": '["x"]'},
            },
        )
        assert status == 422
        assert payload["ok"] is False
        assert payload["violations"]

    def test_bad_edited_fields_type_returns_400(self, pending_p1) -> None:
        status, payload = handle_approve_phase(
            pending_p1,
            {"idea_id": "960", "phase_id": "p1", "edited_fields": {"a": 1}},
        )
        assert status == 400

    def test_double_approve_returns_409(self, pending_p1) -> None:
        handle_approve_phase(pending_p1, {"idea_id": "960", "phase_id": "p1"})
        status, payload = handle_approve_phase(
            pending_p1, {"idea_id": "960", "phase_id": "p1"},
        )
        assert status == 409

    def test_missing_ids_return_404(self, client) -> None:
        assert handle_approve_phase(client, {"phase_id": "p1"})[0] == 404
        assert handle_approve_phase(client, {"idea_id": "960"})[0] == 404
        assert handle_approve_phase(client, None)[0] == 404


class TestRejectEndpoint:
    def test_reject_returns_200_and_stores_comment(self, pending_p1) -> None:
        status, payload = handle_reject_phase(
            pending_p1,
            {"idea_id": "960", "phase_id": "p1", "comment": "narrow the scope"},
        )
        assert status == 200
        assert payload["status"] == "rejected"
        _, state = handle_get_approval_status(pending_p1, "960", "p1")
        assert state["comment"] == "narrow the scope"

    def test_missing_comment_returns_400(self, pending_p1) -> None:
        status, _ = handle_reject_phase(
            pending_p1, {"idea_id": "960", "phase_id": "p1", "comment": "  "},
        )
        assert status == 400


class TestStatusAndToggle:
    def test_status_of_unknown_output_returns_404(self, client) -> None:
        status, _ = handle_get_approval_status(client, "999", "p1")
        assert status == 404

    def test_set_requires_approval_round_trip(self, client) -> None:
        status, payload = handle_set_requires_approval(
            client, {"phase_id": "p2", "required": True},
        )
        assert status == 200
        assert payload == {"phase_id": "p2", "requires_approval": True}

    def test_non_boolean_required_returns_400(self, client) -> None:
        status, _ = handle_set_requires_approval(
            client, {"phase_id": "p2", "required": "yes"},
        )
        assert status == 400


class TestAwaitEndpoint:
    async def test_await_returns_decision(self, pending_p1) -> None:
        handle_approve_phase(pending_p1, {"idea_id": "960", "phase_id": "p1"})
        status, payload = await handle_await_approval(
            pending_p1, {"idea_id": "960", "phase_id": "p1", "timeout_s": 1},
        )
        assert status == 200
        assert payload["status"] == "approved"

    async def test_await_missing_ids_return_404(self, client) -> None:
        status, _ = await handle_await_approval(client, {"phase_id": "p1"})
        assert status == 404
