"""Long-poll semantics of phase_approval.await_approval.

The orchestrator calls this (via await_approval_tool / POST
/phase/await-approval) instead of burning an LLM turn per SPARQL probe while
a human reviews a pending phase output in the dashboard.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from knowledge_graph.core.store import KnowledgeGraphStore
from ontology_server.core.validation import SHACLValidator
from ontology_server.mcp.phase_tools import (
    KGOntologyClient,
    record_phase_result,
    seed_phase_content,
)
from ontology_server.phase_approval import (
    approve_phase,
    await_approval,
    reject_phase,
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


async def test_returns_immediately_when_already_decided(client) -> None:
    record_phase_result(client, "p1", "950", "", P1_OK)
    approve_phase(client, client, "950", "p1")
    out = await await_approval(client, "950", "p1", timeout_s=5)
    assert out == {"status": "approved", "comment": None}


async def test_rejection_returns_the_comment(client) -> None:
    record_phase_result(client, "p1", "951", "", P1_OK)
    reject_phase(client, client, "951", "p1", "tighten the scope")
    out = await await_approval(client, "951", "p1", timeout_s=5)
    assert out == {"status": "rejected", "comment": "tighten the scope"}


async def test_pending_at_timeout(client) -> None:
    record_phase_result(client, "p1", "952", "", P1_OK)
    out = await await_approval(
        client, "952", "p1", timeout_s=1, poll_interval=0.2,
    )
    assert out == {"status": "pending", "comment": None}


async def test_missing_output_reports_missing_immediately(client) -> None:
    out = await await_approval(client, "953", "p1", timeout_s=110)
    assert out == {"status": "missing", "comment": None}


async def test_decision_mid_poll_is_picked_up(client) -> None:
    record_phase_result(client, "p1", "954", "", P1_OK)

    async def _approve_soon() -> None:
        await asyncio.sleep(0.5)
        approve_phase(client, client, "954", "p1", reviewed_by="dashboard")

    task = asyncio.create_task(_approve_soon())
    out = await await_approval(
        client, "954", "p1", timeout_s=10, poll_interval=0.2,
    )
    await task
    assert out["status"] == "approved"
