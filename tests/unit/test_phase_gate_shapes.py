"""End-to-end SHACL gate tests over the REAL stack.

Unlike test_record_phase_result.py (recording fakes), these tests wire a real
in-memory KnowledgeGraphStore, seed the actual tulla/ontologies/phase-content.trig,
and validate with the real pyshacl-backed SHACLValidator — proving:

1. every pipeline phase (d1..p6, i1) has a resolvable gate shape,
2. a conforming payload persists (ok=True),
3. a nonconforming payload is rolled back to ZERO residual triples,
4. the mechanical coverage gates (P1/P3/P4 ``sh:hasValue "[]"``) halt
   feature-dropping phases,
5. P6 can record a coverage_gate="fail" (the orchestrator/I1 block on it),
6. a declared gate NEVER silently passes (no validator / missing shape ⇒ fail).
"""

from __future__ import annotations

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

TRIG_PATH = (
    Path(__file__).resolve().parents[2] / "tulla" / "ontologies" / "phase-content.trig"
)

ALL_GATED_PHASES = [
    "d1", "d2", "d3", "d4", "d5",
    "r1", "r2", "r3", "r4", "r5", "r6",
    "p1", "p2", "p3", "p4", "p5", "p6",
    "i1",
]


@pytest.fixture()
def kg_store() -> KnowledgeGraphStore:
    store = KnowledgeGraphStore()  # in-memory
    loaded = seed_phase_content(store, TRIG_PATH)
    assert loaded > 0, "phase-content.trig must seed at least one quad"
    return store


@pytest.fixture()
def client(kg_store: KnowledgeGraphStore) -> KGOntologyClient:
    return KGOntologyClient(kg_store, SHACLValidator())


def _residual_triples(kg_store: KnowledgeGraphStore, idea_id: str, phase_id: str) -> int:
    result = kg_store.query(
        f"SELECT (COUNT(*) AS ?n) WHERE {{ GRAPH <{GRAPH_PHASES}> {{ "
        f"<{PHASE_NS}{idea_id}-{phase_id}> ?p ?o . }} }}"
    )
    return int(result.bindings[0]["n"])


# ---------------------------------------------------------------------------
# Gate coverage: every pipeline phase declares a resolvable shape
# ---------------------------------------------------------------------------


class TestEveryPhaseIsGated:
    @pytest.mark.parametrize("phase_id", ALL_GATED_PHASES)
    def test_phase_declares_gate_shape(self, kg_store: KnowledgeGraphStore, phase_id: str) -> None:
        result = kg_store.query(
            f"SELECT ?shape WHERE {{ GRAPH <{GRAPH_PHASES}> {{ "
            f"<{PHASE_NS}{phase_id}> <{PHASE_NS}shaclGate> ?shape . }} }}"
        )
        assert result.bindings, f"phase {phase_id} has no shaclGate declaration"
        shape_uri = result.bindings[0]["shape"]
        # The shape must actually be DEFINED, not a dangling reference.
        cbd = kg_store.export_cbd_turtle(shape_uri, graph=GRAPH_PHASES)
        assert cbd, f"gate shape {shape_uri} for {phase_id} is a dangling reference"
        assert "sh:property" in cbd or "ns1:property" in cbd or "property" in cbd

    def test_empty_payload_fails_every_gate(self, client: KGOntologyClient, kg_store: KnowledgeGraphStore) -> None:
        """The gates are real: an empty result_json conforms nowhere."""
        for phase_id in ALL_GATED_PHASES:
            out = record_phase_result(client, phase_id, "900", "", {})
            assert out["ok"] is False, f"{phase_id} gate passed an empty payload"
            assert out["violations"], f"{phase_id} returned no violations"
            assert _residual_triples(kg_store, "idea-900", phase_id) == 0, (
                f"{phase_id} left residual triples after rollback"
            )


# ---------------------------------------------------------------------------
# Conforming payloads persist
# ---------------------------------------------------------------------------


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
    "out_of_scope": ["mobile app", "multi-tenant"],
    "scope_decisions": ["defer mobile", "reuse auth"],
    "non_negotiable_constraints": ["offline-first"],
    "success_metrics": ["100% mandatory feature retention"],
    "jtbd_traceability": [{"feature": "F1", "persona": "dev", "jtbd": "trace"}],
    "scope_boundaries": {"in_scope": ["F1", "F2"], "out_of_scope": ["mobile"]},
}


class TestConformingPayloadsPersist:
    def test_p1_conforming_persists(self, client: KGOntologyClient, kg_store: KnowledgeGraphStore) -> None:
        out = record_phase_result(client, "p1", "901", "", P1_OK, predecessor_phase_id="d5")
        assert out == {"ok": True, "violations": []}
        assert _residual_triples(kg_store, "idea-901", "p1") > 0

    def test_p6_can_record_a_coverage_fail(self, client: KGOntologyClient, kg_store: KnowledgeGraphStore) -> None:
        """P6 must be able to RECORD coverage_gate=fail so the orchestrator
        and I1 can see it and block — the fail is data, not a gate violation."""
        p6_fail = {
            "requirement_count": "4",
            "requirements_exported": "4",
            "prd_context": "prd-idea-902",
            "prd_file": "work/idea-902/p6-prd-export.ttl",
            "p0_count": "2", "p1_count": "1", "p2_count": "1",
            "coverage_gate": "fail",
            "uncovered_features": ["F3"],
        }
        out = record_phase_result(client, "p6", "902", "", p6_fail, predecessor_phase_id="p5")
        assert out == {"ok": True, "violations": []}
        result = kg_store.query(
            f"SELECT ?v WHERE {{ GRAPH <{GRAPH_PHASES}> {{ "
            f"<{PHASE_NS}idea-902-p6> <{PHASE_NS}preserves-coverage_gate> ?v . }} }}"
        )
        assert result.bindings[0]["v"] == "fail"

    def test_p6_rejects_invalid_coverage_gate_value(self, client: KGOntologyClient) -> None:
        p6_bad = {
            "requirement_count": "4",
            "prd_context": "prd-idea-903",
            "prd_file": "x.ttl",
            "coverage_gate": "maybe",
            "uncovered_features": [],
        }
        out = record_phase_result(client, "p6", "903", "", p6_bad)
        assert out["ok"] is False


# ---------------------------------------------------------------------------
# The mechanical coverage gates (sh:hasValue "[]")
# ---------------------------------------------------------------------------


class TestCoverageGatesHalt:
    def test_p1_dropping_a_mandatory_feature_rolls_back(
        self, client: KGOntologyClient, kg_store: KnowledgeGraphStore
    ) -> None:
        dropped = dict(P1_OK, uncovered_mandatory_features=["realtime sync"])
        out = record_phase_result(client, "p1", "904", "", dropped)
        assert out["ok"] is False
        assert any("uncovered_mandatory_features" in v for v in out["violations"])
        assert _residual_triples(kg_store, "idea-904", "p1") == 0

    def test_p3_architecture_gap_rolls_back(
        self, client: KGOntologyClient, kg_store: KnowledgeGraphStore
    ) -> None:
        p3 = {
            "architecture_decisions": [{"id": "ADR-001", "title": "t", "rationale": "r", "consequences": "c"}],
            "quality_goals": [{"attribute": "Modifiability", "priority": "P0"}],
            "adr_count": "1",
            "total_dependencies": "0",
            "circular_dependencies": "0",
            "feature_coverage": [{"feature_id": "F1", "covered_by": ["ADR-001"]}],
            "uncovered_features": ["F2"],  # <- architecture gap
        }
        out = record_phase_result(client, "p3", "905", "", p3)
        assert out["ok"] is False
        assert _residual_triples(kg_store, "idea-905", "p3") == 0

    def test_p4_task_gap_rolls_back(
        self, client: KGOntologyClient, kg_store: KnowledgeGraphStore
    ) -> None:
        p4 = {
            "tasks": [{"id": "T1.1", "title": "t", "features": ["F1"]}],
            "task_count": "1",
            "critical_path": ["T1.1"],
            "feature_coverage": [{"feature_id": "F1", "task_ids": ["T1.1"]}],
            "uncovered_features": ["F2"],  # <- no task for F2
        }
        out = record_phase_result(client, "p4", "906", "", p4)
        assert out["ok"] is False
        assert _residual_triples(kg_store, "idea-906", "p4") == 0


# ---------------------------------------------------------------------------
# A declared gate never silently passes
# ---------------------------------------------------------------------------


class TestGateNeverSilentlyPasses:
    def test_missing_validator_fails_gate(self, kg_store: KnowledgeGraphStore) -> None:
        client = KGOntologyClient(kg_store, validator=None)
        out = record_phase_result(client, "p1", "907", "", P1_OK)
        assert out["ok"] is False
        assert any("no validator" in v for v in out["violations"])
        assert _residual_triples(kg_store, "idea-907", "p1") == 0

    def test_dangling_shape_reference_fails_gate(self, kg_store: KnowledgeGraphStore) -> None:
        kg_store.add_triple(
            f"{PHASE_NS}zz", f"{PHASE_NS}shaclGate", f"{PHASE_NS}NoSuchShape",
            graph=GRAPH_PHASES,
        )
        client = KGOntologyClient(kg_store, SHACLValidator())
        out = record_phase_result(client, "zz", "908", "", {"anything": "x"})
        assert out["ok"] is False
        assert any("not found" in v for v in out["violations"])
        assert _residual_triples(kg_store, "idea-908", "zz") == 0


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


class TestSeeding:
    def test_seed_is_idempotent(self, kg_store: KnowledgeGraphStore) -> None:
        assert seed_phase_content(kg_store, TRIG_PATH) == 0  # second call skips

    def test_missing_file_returns_zero(self) -> None:
        store = KnowledgeGraphStore()
        assert seed_phase_content(store, Path("/nonexistent/phase-content.trig")) == 0

    def test_seed_upserts_stale_definitions(self) -> None:
        """A store carrying an OLDER definition version gets it replaced,
        not duplicated, while live phase outputs survive."""
        store = KnowledgeGraphStore()
        stale = "STALE procedure from an old deployment"
        store.add_triple(
            f"{PHASE_NS}p3", f"{PHASE_NS}procedure", stale,
            is_literal=True, graph=GRAPH_PHASES,
        )
        # A live phase OUTPUT must not be touched by the upsert.
        store.add_triple(
            f"{PHASE_NS}idea-1-d1", f"{PHASE_NS}producedBy", "d1",
            is_literal=True, graph=GRAPH_PHASES,
        )
        assert seed_phase_content(store, TRIG_PATH) > 0
        procs = store.query(
            f"SELECT ?p WHERE {{ GRAPH <{GRAPH_PHASES}> {{ "
            f"<{PHASE_NS}p3> <{PHASE_NS}procedure> ?p . }} }}"
        )
        values = [b["p"] for b in procs.bindings]
        assert stale not in values
        assert len(values) == 1
        assert store.ask(
            f"ASK {{ GRAPH <{GRAPH_PHASES}> {{ "
            f"<{PHASE_NS}idea-1-d1> ?p ?o . }} }}"
        )


class TestGatesDisableFlag:
    """ONTOLOGY_DISABLE_GATES is the ablation switch (SDLC-bench arm b)."""

    def test_disable_flag_skips_validation(self, kg_store, monkeypatch) -> None:
        monkeypatch.setenv("ONTOLOGY_DISABLE_GATES", "1")
        client = KGOntologyClient(kg_store, SHACLValidator())
        out = record_phase_result(client, "p1", "909", "", {})  # empty = nonconforming
        assert out["ok"] is True
        assert out.get("gate_skipped") is True
        assert _residual_triples(kg_store, "idea-909", "p1") > 0  # persisted unvalidated

    def test_flag_unset_still_enforces(self, kg_store, monkeypatch) -> None:
        monkeypatch.delenv("ONTOLOGY_DISABLE_GATES", raising=False)
        client = KGOntologyClient(kg_store, SHACLValidator())
        out = record_phase_result(client, "p1", "910", "", {})
        assert out["ok"] is False
