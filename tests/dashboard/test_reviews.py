"""Integration tests for the HITL review queue dashboard pages.

Unlike test_resolve_route.py (mocked stores), these wire a REAL in-memory
KnowledgeGraphStore seeded with phase-content.trig and the real
SHACLValidator into the dashboard app, then drive the queue / approve /
reject / settings flows through TestClient — proving the full stack from
form POST to graph mutation.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from knowledge_graph.core.store import KnowledgeGraphStore, GRAPH_PHASES
from ontology_server.core.validation import SHACLValidator
from ontology_server.dashboard import create_dashboard_app
from ontology_server.mcp.phase_tools import (
    KGOntologyClient,
    PHASE_NS,
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
def kg_store() -> KnowledgeGraphStore:
    store = KnowledgeGraphStore()
    assert seed_phase_content(store, TRIG_PATH) > 0
    return store


@pytest.fixture()
def client(kg_store: KnowledgeGraphStore) -> TestClient:
    app = create_dashboard_app(
        ontology_store=MagicMock(),
        kg_store=kg_store,
        agent_memory=MagicMock(),
        ideas_store=MagicMock(),
        validator=SHACLValidator(),
    )
    return TestClient(app, follow_redirects=False)


@pytest.fixture()
def pending_p1(kg_store: KnowledgeGraphStore) -> KnowledgeGraphStore:
    writer = KGOntologyClient(kg_store, SHACLValidator())
    out = record_phase_result(writer, "p1", "970", "", P1_OK)
    assert out["approval"] == "pending"
    return kg_store


def _status(kg_store: KnowledgeGraphStore, idea_id: str, phase_id: str) -> str | None:
    result = kg_store.query(
        f"SELECT ?st WHERE {{ GRAPH <{GRAPH_PHASES}> {{ "
        f"<{PHASE_NS}{idea_id}-{phase_id}> <{PHASE_NS}approvalStatus> ?st . }} }}"
    )
    return str(result.bindings[0]["st"]) if result.bindings else None


class TestQueuePage:
    def test_queue_lists_pending_output(self, client, pending_p1) -> None:
        response = client.get("/reviews")
        assert response.status_code == 200
        assert "idea-970" in response.text
        assert "p1" in response.text

    def test_empty_queue_shows_empty_state(self, client) -> None:
        response = client.get("/reviews")
        assert response.status_code == 200
        assert "No phase outputs awaiting review" in response.text

    def test_badge_partial_counts_pending(self, client, pending_p1) -> None:
        response = client.get("/partials/review-badge")
        assert response.status_code == 200
        assert ">1<" in response.text

    def test_badge_partial_empty_when_none(self, client) -> None:
        response = client.get("/partials/review-badge")
        assert response.text == ""

    def test_rows_partial_renders(self, client, pending_p1) -> None:
        response = client.get("/partials/review-rows")
        assert response.status_code == 200
        assert "idea-970" in response.text


class TestReviewDetailPage:
    def test_detail_shows_fields_and_status(self, client, pending_p1) -> None:
        response = client.get("/reviews/idea-970/p1")
        assert response.status_code == 200
        assert "pending" in response.text
        assert "field__target_audience" in response.text
        assert "internal dev teams" in response.text

    def test_unknown_output_returns_404(self, client) -> None:
        response = client.get("/reviews/idea-999/p1")
        assert response.status_code == 404


class TestApproveFlow:
    def test_plain_approve_redirects_and_approves(
        self, client, pending_p1,
    ) -> None:
        response = client.post(
            "/reviews/idea-970/p1/approve", data={"comment": "fine"},
        )
        assert response.status_code == 303
        assert _status(pending_p1, "idea-970", "p1") == "approved"

    def test_edited_field_persists(self, client, pending_p1) -> None:
        response = client.post(
            "/reviews/idea-970/p1/approve",
            data={"field__target_audience": "external customers"},
        )
        assert response.status_code == 303
        result = pending_p1.query(
            f"SELECT ?v WHERE {{ GRAPH <{GRAPH_PHASES}> {{ "
            f"<{PHASE_NS}idea-970-p1> <{PHASE_NS}preserves-target_audience> ?v . }} }}"
        )
        assert result.bindings[0]["v"] == "external customers"

    def test_gate_violating_edit_returns_422_and_keeps_store(
        self, client, pending_p1,
    ) -> None:
        response = client.post(
            "/reviews/idea-970/p1/approve",
            data={"field__uncovered_mandatory_features": '["dropped feature"]'},
        )
        assert response.status_code == 422
        assert "rejected by the phase" in response.text
        # Store untouched, output still pending.
        result = pending_p1.query(
            f"SELECT ?v WHERE {{ GRAPH <{GRAPH_PHASES}> {{ "
            f"<{PHASE_NS}idea-970-p1> "
            f"<{PHASE_NS}preserves-uncovered_mandatory_features> ?v . }} }}"
        )
        assert result.bindings[0]["v"] == "[]"
        assert _status(pending_p1, "idea-970", "p1") == "pending"

    def test_double_approve_returns_422(self, client, pending_p1) -> None:
        client.post("/reviews/idea-970/p1/approve", data={})
        response = client.post("/reviews/idea-970/p1/approve", data={})
        assert response.status_code == 422


class TestRejectFlow:
    def test_reject_requires_comment(self, client, pending_p1) -> None:
        response = client.post(
            "/reviews/idea-970/p1/reject", data={"comment": "  "},
        )
        assert response.status_code == 422
        assert _status(pending_p1, "idea-970", "p1") == "pending"

    def test_reject_with_comment_redirects(self, client, pending_p1) -> None:
        response = client.post(
            "/reviews/idea-970/p1/reject",
            data={"comment": "narrow the scope to F1 only"},
        )
        assert response.status_code == 303
        assert _status(pending_p1, "idea-970", "p1") == "rejected"


class TestSettingsPage:
    def test_settings_lists_ship_defaults(self, client) -> None:
        response = client.get("/settings/phases")
        assert response.status_code == 200
        for phase_id in ("d5", "p1", "p6"):
            assert phase_id in response.text

    def test_toggle_writes_flag(self, client, kg_store) -> None:
        response = client.post(
            "/settings/phases/p2/approval", data={"required": "true"},
        )
        assert response.status_code == 303
        result = kg_store.query(
            f"SELECT ?v WHERE {{ GRAPH <{GRAPH_PHASES}> {{ "
            f"<{PHASE_NS}p2> <{PHASE_NS}requiresApproval> ?v . }} }}"
        )
        assert result.bindings[0]["v"] == "true"
