"""Integration tests for record_phase_result (req-130-3-3, ADR-130-7).

Covers the server-side persist-validate-rollback sequence in
:mod:`mcp.phase_tools`, the HTTP twin in :mod:`api.routes.phases`, and the
default port implementation on
:class:`tulla.ports.ontology.OntologyPort.record_phase_result`.

The verification target (Task 3.4) is the 8-step sequence defined by
ADR-130-7 — order-sensitive, idempotent cleanup before write, SHACL
gate lookup with rollback on violation, and only-allow-listed intent
fields persisted as ``phase:preserves-*`` literals.
"""

from __future__ import annotations

import json

import pytest

from api.routes.phases import handle_record_phase_result
from mcp.phase_tools import (
    PHASE_NS,
    PHASES_GRAPH,
    RDF_TYPE,
    TRACE_NS,
    record_phase_result,
)
from tulla.ontology.phase_predicate_names import PHASE_PREDICATE_NAMES
from tulla.ports.ontology import OntologyPort


# ---------------------------------------------------------------------------
# Recording ontology client — records every method call so the persist
# sequence can be asserted step-by-step.
# ---------------------------------------------------------------------------


class _RecordingOntology:
    """Minimal in-memory OntologyClient that records every call.

    Tracks add_triple / remove_triples_by_subject / validate_instance /
    sparql_query as ordered events so tests can assert both the count
    and the *order* of the 8-step persist sequence (load-bearing per
    ADR-130-7).
    """

    def __init__(
        self,
        *,
        gate_shape: str | None = None,
        validation: dict | None = None,
        validate_exc: Exception | None = None,
    ) -> None:
        self.calls: list[tuple] = []
        self.triples: list[dict] = []
        self._gate_shape = gate_shape
        self._validation = validation if validation is not None else {
            "conforms": True,
            "violations": [],
        }
        self._validate_exc = validate_exc

    def sparql_query(self, query: str):
        self.calls.append(("sparql_query", query))
        if self._gate_shape:
            return {"results": [{"shape": self._gate_shape}]}
        return {"results": []}

    def add_triple(self, subject, predicate, object, *, is_literal=False):
        self.calls.append(
            ("add_triple", subject, predicate, object, is_literal),
        )
        self.triples.append(
            {
                "subject": subject,
                "predicate": predicate,
                "object": object,
                "is_literal": is_literal,
            }
        )
        return {"status": "added"}

    def remove_triples_by_subject(self, subject):
        self.calls.append(("remove_triples_by_subject", subject))
        before = len(self.triples)
        self.triples = [t for t in self.triples if t["subject"] != subject]
        return before - len(self.triples)

    def validate_instance(self, instance_uri, shape_uri):
        self.calls.append(("validate_instance", instance_uri, shape_uri))
        if self._validate_exc is not None:
            raise self._validate_exc
        return self._validation


# ---------------------------------------------------------------------------
# record_phase_result (mcp.phase_tools)
# ---------------------------------------------------------------------------


class TestRecordPhaseResult:
    def test_persist_emits_metadata_and_preserves_for_known_intent_fields(self) -> None:
        ontology = _RecordingOntology()
        d1_names = sorted(PHASE_PREDICATE_NAMES["d1"])
        result_json = {
            d1_names[0]: "alpha",
            d1_names[1]: 42,
            "unknown_field": "dropped",
        }
        out = record_phase_result(
            ontology, "d1", "130", "/tmp/artifact.json", result_json,
        )
        assert out == {"ok": True, "violations": []}

        subject = f"{PHASE_NS}130-d1"
        preds = [t["predicate"] for t in ontology.triples]
        assert RDF_TYPE in preds
        assert f"{PHASE_NS}producedBy" in preds
        assert f"{PHASE_NS}forRequirement" in preds
        # Allow-listed fields are persisted, unknown is dropped.
        assert f"{PHASE_NS}preserves-{d1_names[0]}" in preds
        assert f"{PHASE_NS}preserves-{d1_names[1]}" in preds
        assert all("unknown_field" not in p for p in preds)
        # All triples share the subject URI.
        for t in ontology.triples:
            assert t["subject"] == subject

    def test_cleanup_before_write_is_step_two(self) -> None:
        ontology = _RecordingOntology()
        record_phase_result(
            ontology, "d1", "130", "", {}, None,
        )
        ops = [c[0] for c in ontology.calls]
        # remove_triples_by_subject must come BEFORE any add_triple.
        assert ops.index("remove_triples_by_subject") < ops.index("add_triple")

    def test_predecessor_adds_traces_to_edge(self) -> None:
        ontology = _RecordingOntology()
        record_phase_result(
            ontology, "r2", "130", "", {}, predecessor_phase_id="r1",
        )
        edges = [
            (t["predicate"], t["object"]) for t in ontology.triples
        ]
        assert (f"{TRACE_NS}tracesTo", f"{PHASE_NS}130-r1") in edges

    def test_predecessor_absent_does_not_add_traces_to(self) -> None:
        ontology = _RecordingOntology()
        record_phase_result(ontology, "r2", "130", "", {})
        preds = [t["predicate"] for t in ontology.triples]
        assert f"{TRACE_NS}tracesTo" not in preds

    def test_shacl_violation_rolls_back_and_returns_violations(self) -> None:
        ontology = _RecordingOntology(
            gate_shape="http://example/shape/PhaseOutputShape",
            validation={"conforms": False, "violations": ["minCount on preserves-foo"]},
        )
        out = record_phase_result(
            ontology, "d1", "130", "", {}, None,
        )
        assert out["ok"] is False
        assert out["violations"] == ["minCount on preserves-foo"]
        # Two remove_triples_by_subject calls: initial cleanup + rollback.
        removes = [c for c in ontology.calls if c[0] == "remove_triples_by_subject"]
        assert len(removes) == 2
        # Triples were wiped on rollback.
        assert ontology.triples == []

    def test_shacl_success_keeps_triples(self) -> None:
        ontology = _RecordingOntology(
            gate_shape="http://example/shape/PhaseOutputShape",
            validation={"conforms": True, "violations": []},
        )
        out = record_phase_result(ontology, "d1", "130", "", {}, None)
        assert out == {"ok": True, "violations": []}
        # Only the initial cleanup; no rollback.
        removes = [c for c in ontology.calls if c[0] == "remove_triples_by_subject"]
        assert len(removes) == 1
        assert ontology.triples  # triples retained

    def test_no_shacl_gate_still_returns_ok(self) -> None:
        ontology = _RecordingOntology(gate_shape=None)
        out = record_phase_result(ontology, "d1", "130", "", {})
        assert out == {"ok": True, "violations": []}
        # No validation call when no gate is configured.
        assert all(c[0] != "validate_instance" for c in ontology.calls)

    def test_validate_exception_rolls_back(self) -> None:
        ontology = _RecordingOntology(
            gate_shape="http://example/shape/X",
            validate_exc=RuntimeError("validator unavailable"),
        )
        out = record_phase_result(ontology, "d1", "130", "", {})
        assert out["ok"] is False
        assert out["violations"] == ["validator unavailable"]

    def test_compound_value_is_json_stringified(self) -> None:
        ontology = _RecordingOntology()
        d1_names = sorted(PHASE_PREDICATE_NAMES["d1"])
        record_phase_result(
            ontology, "d1", "130", "", {d1_names[0]: ["a", "b", "c"]},
        )
        triple = next(
            t for t in ontology.triples
            if t["predicate"] == f"{PHASE_NS}preserves-{d1_names[0]}"
        )
        assert triple["object"] == json.dumps(["a", "b", "c"])
        assert triple["is_literal"] is True

    def test_none_value_is_skipped(self) -> None:
        ontology = _RecordingOntology()
        d1_names = sorted(PHASE_PREDICATE_NAMES["d1"])
        record_phase_result(
            ontology, "d1", "130", "", {d1_names[0]: None},
        )
        preds = [t["predicate"] for t in ontology.triples]
        assert f"{PHASE_NS}preserves-{d1_names[0]}" not in preds

    def test_empty_phase_id_raises(self) -> None:
        with pytest.raises(ValueError):
            record_phase_result(_RecordingOntology(), "", "130", "", {})

    def test_empty_idea_id_raises(self) -> None:
        with pytest.raises(ValueError):
            record_phase_result(_RecordingOntology(), "d1", "", "", {})

    def test_subject_uri_is_idea_dash_phase(self) -> None:
        ontology = _RecordingOntology()
        record_phase_result(ontology, "r5-retry", "130", "", {})
        for t in ontology.triples:
            assert t["subject"] == f"{PHASE_NS}130-r5-retry"

    def test_shacl_gate_lookup_targets_phases_graph(self) -> None:
        ontology = _RecordingOntology(gate_shape=None)
        record_phase_result(ontology, "d1", "130", "", {})
        query = next(
            c[1] for c in ontology.calls if c[0] == "sparql_query"
        )
        assert f"GRAPH <{PHASES_GRAPH}>" in query
        assert f"<{PHASE_NS}shaclGate>" in query


# ---------------------------------------------------------------------------
# HTTP twin
# ---------------------------------------------------------------------------


class TestHandleRecordPhaseResult:
    def test_success_returns_200_with_ok(self) -> None:
        ontology = _RecordingOntology()
        status, payload = handle_record_phase_result(
            ontology,
            {
                "phase_id": "d1",
                "idea_id": "130",
                "artifact_path": "/tmp/a.json",
                "result_json": {},
            },
        )
        assert status == 200
        assert payload == {"ok": True, "violations": []}

    def test_violation_returns_200_with_ok_false(self) -> None:
        ontology = _RecordingOntology(
            gate_shape="http://example/shape/X",
            validation={"conforms": False, "violations": ["v1", "v2"]},
        )
        status, payload = handle_record_phase_result(
            ontology,
            {
                "phase_id": "d1",
                "idea_id": "130",
                "artifact_path": "",
                "result_json": {},
            },
        )
        assert status == 200
        assert payload == {"ok": False, "violations": ["v1", "v2"]}

    def test_missing_phase_id_returns_404(self) -> None:
        status, payload = handle_record_phase_result(
            _RecordingOntology(), {"idea_id": "130"},
        )
        assert status == 404
        assert payload == {"error": "missing phase_id"}

    def test_missing_idea_id_returns_404(self) -> None:
        status, payload = handle_record_phase_result(
            _RecordingOntology(), {"phase_id": "d1"},
        )
        assert status == 404
        assert payload == {"error": "missing idea_id"}

    def test_none_body_returns_404(self) -> None:
        status, payload = handle_record_phase_result(_RecordingOntology(), None)
        assert status == 404

    def test_predecessor_propagated(self) -> None:
        ontology = _RecordingOntology()
        handle_record_phase_result(
            ontology,
            {
                "phase_id": "r2",
                "idea_id": "130",
                "result_json": {},
                "predecessor_phase_id": "r1",
            },
        )
        edges = [(t["predicate"], t["object"]) for t in ontology.triples]
        assert (f"{TRACE_NS}tracesTo", f"{PHASE_NS}130-r1") in edges


# ---------------------------------------------------------------------------
# OntologyPort default adapter method
# ---------------------------------------------------------------------------


class _StubPort(OntologyPort):
    """Minimal port whose mutating methods record onto a recording client."""

    def __init__(self, ontology: _RecordingOntology) -> None:
        self._inner = ontology

    def sparql_query(self, query: str, *, validate: bool = True):  # type: ignore[override]
        return self._inner.sparql_query(query)

    def add_triple(  # type: ignore[override]
        self, subject, predicate, object, *, is_literal=False, ontology=None,
    ):
        return self._inner.add_triple(
            subject, predicate, object, is_literal=is_literal,
        )

    def remove_triples_by_subject(self, subject, *, ontology=None):  # type: ignore[override]
        return self._inner.remove_triples_by_subject(subject)

    def validate_instance(  # type: ignore[override]
        self, instance_uri, shape_uri, *, ontology=None,
    ):
        return self._inner.validate_instance(instance_uri, shape_uri)

    # -- stubs for the rest of the ABC --
    def query_ideas(self, **_): return {}
    def get_idea(self, idea_id): return {}
    def store_fact(self, subject, predicate, object, **_): return {}
    def forget_fact(self, fact_id): return {}
    def recall_facts(self, **_): return {}
    def sparql_update(self, query, **_): return {}
    def update_idea(self, idea_id, **_): return {}
    def forget_by_context(self, context): return 0
    def set_lifecycle(self, idea_id, new_state, **_): return {}


class TestOntologyPortRecordPhaseResult:
    def test_default_implementation_persists_intent_fields(self) -> None:
        inner = _RecordingOntology()
        port = _StubPort(inner)
        d1_names = sorted(PHASE_PREDICATE_NAMES["d1"])
        out = port.record_phase_result(
            "d1", "130", "/tmp/a.json", {d1_names[0]: "value"},
        )
        assert out == {"ok": True, "violations": []}
        preds = [t["predicate"] for t in inner.triples]
        assert f"{PHASE_NS}preserves-{d1_names[0]}" in preds
        assert f"{PHASE_NS}producedBy" in preds
        assert f"{PHASE_NS}forRequirement" in preds

    def test_default_implementation_rolls_back_on_violation(self) -> None:
        inner = _RecordingOntology(
            gate_shape="http://example/shape/X",
            validation={"conforms": False, "violations": ["boom"]},
        )
        port = _StubPort(inner)
        out = port.record_phase_result("d1", "130", "", {})
        assert out["ok"] is False
        assert out["violations"] == ["boom"]
        assert inner.triples == []

    def test_default_implementation_rejects_empty_phase_id(self) -> None:
        port = _StubPort(_RecordingOntology())
        with pytest.raises(ValueError):
            port.record_phase_result("", "130", "", {})

    def test_default_implementation_rejects_empty_idea_id(self) -> None:
        port = _StubPort(_RecordingOntology())
        with pytest.raises(ValueError):
            port.record_phase_result("d1", "", "", {})
