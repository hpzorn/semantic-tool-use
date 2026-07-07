"""Context-cost controls on upstream fact collection.

collect_upstream_facts(consuming_phase_id=...) trims the payload to the
caller's declared PHASE_CONSUMED_FIELDS; get_phase_fact is the targeted
drill-down for anything outside that diet.
"""

from __future__ import annotations

import pytest

from knowledge_graph.core.store import KnowledgeGraphStore
from ontology_server.mcp.phase_tools import (
    KGOntologyClient,
    KGSparqlClient,
    collect_upstream_facts,
    get_phase_fact,
)
from ontology_server.phase_predicate_names import PHASE_CONSUMED_FIELDS


@pytest.fixture()
def sparql() -> KGSparqlClient:
    store = KnowledgeGraphStore()
    writer = KGOntologyClient(store)
    subject_d5 = "http://tulla.dev/phase#idea-16-d5"
    subject_r3 = "http://tulla.dev/phase#idea-16-r3"
    for subject, fields in (
        (subject_d5, {
            "mode": "research",
            "northstar": "a browser civ2",
            "mandatory_features": '["hex map", "tech tree"]',
            "research_questions": '["rq1", "rq2"]',
        }),
        (subject_r3, {
            "findings": '[{"rq": "rq1", "finding": "use pixi"}]',
            "key_insights": '["canvas is enough"]',
        }),
    ):
        writer.add_triple(
            subject, "http://tulla.dev/phase#producedBy",
            subject.rsplit("-", 1)[-1], is_literal=True,
        )
        writer.add_triple(
            subject, "http://tulla.dev/phase#forRequirement",
            "idea-16", is_literal=True,
        )
        for name, value in fields.items():
            writer.add_triple(
                subject, f"http://tulla.dev/phase#preserves-{name}",
                value, is_literal=True,
            )
    return KGSparqlClient(store)


class TestConsumingPhaseFilter:
    def test_unfiltered_returns_everything(self, sparql) -> None:
        out = collect_upstream_facts(sparql, "16")
        assert set(out) == {"d5", "r3"}
        assert "findings" in out["r3"]

    def test_r1_diet_drops_r3_findings(self, sparql) -> None:
        assert "findings" not in PHASE_CONSUMED_FIELDS["r1"]
        out = collect_upstream_facts(sparql, "16", consuming_phase_id="r1")
        assert "r3" not in out
        assert out["d5"]["northstar"] == "a browser civ2"
        assert "mode" in out["d5"]

    def test_r4_diet_keeps_findings(self, sparql) -> None:
        out = collect_upstream_facts(sparql, "16", consuming_phase_id="r4")
        assert "findings" in out["r3"]
        assert "key_insights" not in out["r3"]  # not in r4's diet

    def test_no_match_falls_back_to_unfiltered(self, sparql) -> None:
        # p2 consumes only P1 fields; none recorded yet — must NOT return
        # an empty dict (the agent would be flying blind).
        out = collect_upstream_facts(sparql, "16", consuming_phase_id="p2")
        assert set(out) == {"d5", "r3"}


class TestGetPhaseFact:
    def test_fetches_single_field(self, sparql) -> None:
        out = get_phase_fact(sparql, "16", "r3", "findings")
        assert out["found"] is True
        assert out["value"][0]["finding"] == "use pixi"

    def test_missing_field_reports_not_found(self, sparql) -> None:
        out = get_phase_fact(sparql, "16", "r3", "nonexistent")
        assert out == {
            "idea_id": "idea-16", "phase_id": "r3",
            "field": "nonexistent", "found": False, "value": None,
        }

    def test_requires_all_args(self, sparql) -> None:
        with pytest.raises(ValueError):
            get_phase_fact(sparql, "16", "", "findings")
