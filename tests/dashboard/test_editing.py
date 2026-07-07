"""Dashboard editing + change-history integration tests.

Real stores (KnowledgeGraphStore + IdeasStore + AgentMemory + validator)
behind the dashboard TestClient — proving idea click-to-edit round-trips,
fact row edits, phase edits at approved status with the staleness banner,
history sections, and the global changes feed.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from knowledge_graph.core.ideas import Idea, IdeasStore
from knowledge_graph.core.memory import AgentMemory, MemoryFact
from knowledge_graph.core.store import KnowledgeGraphStore, GRAPH_PHASES, NAMESPACES
from ontology_server.core.validation import SHACLValidator
from ontology_server.dashboard import create_dashboard_app
from ontology_server.mcp.phase_tools import (
    KGOntologyClient,
    PHASE_NS,
    record_phase_result,
    seed_phase_content,
)
from ontology_server.phase_approval import approve_phase

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
def ideas_store(kg_store) -> IdeasStore:
    store = IdeasStore(kg_store)
    store.create_idea(Idea(
        id="idea-800", title="Editable idea",
        description="Before edit", tags=["alpha"],
    ))
    return store


@pytest.fixture()
def agent_memory(kg_store) -> AgentMemory:
    return AgentMemory(kg_store)


@pytest.fixture()
def client(kg_store, ideas_store, agent_memory) -> TestClient:
    app = create_dashboard_app(
        ontology_store=MagicMock(),
        kg_store=kg_store,
        agent_memory=agent_memory,
        ideas_store=ideas_store,
        validator=SHACLValidator(),
    )
    return TestClient(app, follow_redirects=False)


class TestIdeaClickToEdit:
    def test_detail_page_renders_editable_fields(self, client) -> None:
        response = client.get("/ideas/idea-800")
        assert response.status_code == 200
        assert "edit-pencil" in response.text

    def test_edit_form_prefilled(self, client) -> None:
        response = client.get("/ideas/idea-800/edit/description")
        assert response.status_code == 200
        assert "Before edit" in response.text
        assert "<form" in response.text

    def test_save_round_trip_and_history(self, client, ideas_store) -> None:
        response = client.post(
            "/ideas/idea-800/edit/description", data={"value": "After edit"},
        )
        assert response.status_code == 200
        assert "After edit" in response.text
        assert response.headers.get("hx-trigger") == "entity-edited"
        assert ideas_store.get_idea("idea-800").description == "After edit"

        history = client.get(
            "/partials/history",
            params={"target": f"{NAMESPACES['ideas']}idea-800"},
        )
        assert "Before edit" in history.text
        assert "After edit" in history.text

    def test_invalid_edit_rerenders_form_422(self, client) -> None:
        response = client.post(
            "/ideas/idea-800/edit/title", data={"value": "  "},
        )
        assert response.status_code == 422
        assert "field-error" in response.text

    def test_unknown_field_404(self, client) -> None:
        assert client.get("/ideas/idea-800/edit/lifecycle").status_code == 404


class TestFactRowEdit:
    @pytest.fixture()
    def fact_id(self, agent_memory) -> str:
        agent_memory.store_fact(MemoryFact(
            subject="prd:req-1-1", predicate="rdf:type",
            object="prd:Requirement", context="prd-idea-800",
        ))
        return agent_memory.store_fact(MemoryFact(
            subject="prd:req-1-1", predicate="prd:title",
            object="Old requirement title", context="prd-idea-800",
        ))

    def test_facts_page_has_edit_buttons(self, client, fact_id) -> None:
        response = client.get(
            "/facts/prd-idea-800", params={"subject": "prd:req-1-1"},
        )
        assert response.status_code == 200
        assert "edit-pencil" in response.text

    def test_fact_edit_round_trip(self, client, agent_memory, fact_id) -> None:
        form = client.get(f"/partials/fact-edit/{fact_id}")
        assert "Old requirement title" in form.text

        response = client.post(
            f"/facts-edit/{fact_id}",
            data={"object": "New requirement title", "confidence": "0.8"},
        )
        assert response.status_code == 200
        assert "New requirement title" in response.text
        updated = agent_memory.get_fact(fact_id)
        assert updated["object"] == "New requirement title"
        assert updated["confidence"] == 0.8

    def test_requirement_page_links_to_fact_editor(self, client, fact_id) -> None:
        response = client.get("/prds/prd-idea-800/prd:req-1-1")
        assert response.status_code == 200
        assert "Edit fields" in response.text


class TestPhaseEditPage:
    @pytest.fixture()
    def approved_p1(self, kg_store) -> None:
        writer = KGOntologyClient(kg_store, SHACLValidator())
        record_phase_result(writer, "d5", "800", "", {
            "mode": "plan", "recommendation": "go", "northstar": "n",
            "mandatory_features": ["graph export"], "research_questions": [],
        })
        record_phase_result(writer, "p1", "800", "", P1_OK)
        approve_phase(writer, writer, "800", "p1")
        approve_phase(writer, writer, "800", "d5")

    def test_edit_page_renders_at_approved_status(self, client, approved_p1) -> None:
        response = client.get("/phases/idea-800/p1/edit")
        assert response.status_code == 200
        assert "approved" in response.text
        assert "field__target_audience" in response.text
        assert "consumed by" in response.text  # consumer captions

    def test_save_shows_staleness_banner(self, client, kg_store, approved_p1) -> None:
        response = client.post(
            "/phases/idea-800/d5/edit",
            data={"field__mandatory_features": '["graph export", "extra"]',
                  "reason": "scope grew"},
        )
        assert response.status_code == 200
        assert "Saved:" in response.text
        assert "stale" in response.text
        assert "p1" in response.text  # p1 consumed mandatory_features
        # Approval status untouched.
        result = kg_store.query(
            f"SELECT ?st WHERE {{ GRAPH <{GRAPH_PHASES}> {{ "
            f"<{PHASE_NS}idea-800-d5> <{PHASE_NS}approvalStatus> ?st . }} }}"
        )
        assert result.bindings[0]["st"] == "approved"

    def test_gate_violating_edit_422(self, client, approved_p1) -> None:
        response = client.post(
            "/phases/idea-800/p1/edit",
            data={"field__uncovered_mandatory_features": '["dropped"]'},
        )
        assert response.status_code == 422
        assert "rejected by the phase" in response.text

    def test_phase_detail_links_to_editor(self, client, approved_p1) -> None:
        response = client.get("/phases/idea-800/p1")
        assert "Edit fields" in response.text


class TestChangesFeed:
    def test_feed_lists_edits_across_kinds(self, client, ideas_store) -> None:
        client.post("/ideas/idea-800/edit/title", data={"value": "Renamed"})
        response = client.get("/changes")
        assert response.status_code == 200
        assert "Renamed" in response.text
        assert "idea" in response.text

    def test_kind_filter(self, client) -> None:
        client.post("/ideas/idea-800/edit/title", data={"value": "Renamed"})
        response = client.get("/changes", params={"entity_kind": "fact"})
        assert "Renamed" not in response.text
