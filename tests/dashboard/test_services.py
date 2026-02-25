"""Unit tests for DashboardService."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ontology_server.dashboard.services import (
    DashboardService,
    KNOWN_PHASES,
    PHASE_NS,
    PHASES_GRAPH,
    PRD_NS,
)


def _make_service(kg_store: MagicMock | None = None) -> DashboardService:
    """Build a DashboardService with mocked backing stores."""
    return DashboardService(
        ontology_store=MagicMock(),
        kg_store=kg_store or MagicMock(),
        agent_memory=MagicMock(),
        ideas_store=MagicMock(),
    )


def _sparql_result(phases: list[str]) -> SimpleNamespace:
    """Create a fake SPARQL result with .bindings matching kg_store.query() shape."""
    return SimpleNamespace(bindings=[{"phase": p} for p in phases])


class TestGetIdeaProgress:
    """Tests for DashboardService.get_idea_progress()."""

    def test_no_completed_phases(self) -> None:
        """When no phases completed, percent is 0 and current is d0."""
        kg = MagicMock()
        kg.query.return_value = _sparql_result([])
        svc = _make_service(kg)

        result = svc.get_idea_progress("idea-99")

        assert result["completed"] == []
        assert result["total"] == 6
        assert result["percent"] == 0
        assert result["current"] == "d0"

    def test_some_phases_completed(self) -> None:
        """With d1 and d2 completed, percent is 33 and current is d0."""
        kg = MagicMock()
        kg.query.return_value = _sparql_result(["d2", "d1"])
        svc = _make_service(kg)

        result = svc.get_idea_progress("idea-50")

        assert result["completed"] == ["d1", "d2"]
        assert result["total"] == 6
        assert result["percent"] == 33
        assert result["current"] == "d0"

    def test_contiguous_phases_completed(self) -> None:
        """With d0, d1, d2 completed, current is d3."""
        kg = MagicMock()
        kg.query.return_value = _sparql_result(["d0", "d1", "d2"])
        svc = _make_service(kg)

        result = svc.get_idea_progress("idea-50")

        assert result["completed"] == ["d0", "d1", "d2"]
        assert result["total"] == 6
        assert result["percent"] == 50
        assert result["current"] == "d3"

    def test_all_phases_completed(self) -> None:
        """When all known phases are done, percent is 100 and current is None."""
        kg = MagicMock()
        kg.query.return_value = _sparql_result(KNOWN_PHASES[:])
        svc = _make_service(kg)

        result = svc.get_idea_progress("idea-1")

        assert result["completed"] == ["d0", "d1", "d2", "d3", "d4", "d5"]
        assert result["total"] == 6
        assert result["percent"] == 100
        assert result["current"] is None

    def test_unknown_phases_ignored(self) -> None:
        """Phases not in KNOWN_PHASES are filtered out."""
        kg = MagicMock()
        kg.query.return_value = _sparql_result(["d1", "d99", "impl-loop"])
        svc = _make_service(kg)

        result = svc.get_idea_progress("idea-50")

        assert result["completed"] == ["d1"]
        assert result["total"] == 6
        assert result["percent"] == 16
        assert result["current"] == "d0"

    def test_query_exception_returns_empty_progress(self) -> None:
        """On SPARQL error, return empty progress dict and log error."""
        kg = MagicMock()
        kg.query.side_effect = RuntimeError("Oxigraph unavailable")
        svc = _make_service(kg)

        result = svc.get_idea_progress("idea-broken")

        assert result["completed"] == []
        assert result["total"] == 6
        assert result["percent"] == 0
        assert result["current"] is None

    def test_sparql_query_uses_idea_id(self) -> None:
        """The SPARQL query includes the idea_id in the forRequirement filter."""
        kg = MagicMock()
        kg.query.return_value = _sparql_result([])
        svc = _make_service(kg)

        svc.get_idea_progress("idea-42")

        sparql_arg = kg.query.call_args[0][0]
        assert "idea-42" in sparql_arg

    def test_completed_list_is_sorted(self) -> None:
        """Completed phases are returned in sorted order regardless of input."""
        kg = MagicMock()
        kg.query.return_value = _sparql_result(["d5", "d3", "d0", "d1"])
        svc = _make_service(kg)

        result = svc.get_idea_progress("idea-10")

        assert result["completed"] == ["d0", "d1", "d3", "d5"]


# -- Helpers for get_phase_facts tests ------------------------------------


def _spo_bindings(triples: list[tuple[str, str, str]]) -> SimpleNamespace:
    """Create a fake SPARQL result with .bindings for SPO triples."""
    return SimpleNamespace(
        bindings=[{"s": s, "p": p, "o": o} for s, p, o in triples],
    )


class TestGetPhaseFacts:
    """Tests for DashboardService.get_phase_facts()."""

    def test_groups_facts_by_phase_and_field(self) -> None:
        """Sample SPO triples are grouped into {phase: {field: value}}."""
        kg = MagicMock()
        kg.query.return_value = _spo_bindings([
            (f"{PHASE_NS}idea50-d1", f"{PHASE_NS}preserves-tools_found", "16"),
            (f"{PHASE_NS}idea50-d1", f"{PHASE_NS}preserves-mcp_servers_found", "3"),
            (f"{PHASE_NS}idea50-d1", f"{PHASE_NS}forRequirement", "idea50"),
            (f"{PHASE_NS}idea50-d1", f"{PHASE_NS}producedBy", "d1"),
            (f"{PHASE_NS}idea50-d3", f"{PHASE_NS}preserves-quadrant", "Major Project"),
            (f"{PHASE_NS}idea50-d3", f"{PHASE_NS}preserves-total_value_score", "42"),
            (f"{PHASE_NS}idea50-d3", f"{PHASE_NS}forRequirement", "idea50"),
            (f"{PHASE_NS}idea50-d3", f"{PHASE_NS}producedBy", "d3"),
        ])
        svc = _make_service(kg)

        result = svc.get_phase_facts("idea50")

        assert result == {
            "d1": {"tools_found": 16, "mcp_servers_found": 3},
            "d3": {"quadrant": "Major Project", "total_value_score": 42},
        }

    def test_try_coerce_converts_numeric_strings_to_int(self) -> None:
        """Numeric string values are coerced to ints by _try_coerce."""
        kg = MagicMock()
        kg.query.return_value = _spo_bindings([
            (f"{PHASE_NS}idea7-d2", f"{PHASE_NS}preserves-persona_count", "5"),
            (f"{PHASE_NS}idea7-d2", f"{PHASE_NS}forRequirement", "idea7"),
        ])
        svc = _make_service(kg)

        result = svc.get_phase_facts("idea7")

        assert result["d2"]["persona_count"] == 5
        assert isinstance(result["d2"]["persona_count"], int)

    def test_empty_query_returns_empty_dict(self) -> None:
        """When no triples match, return an empty dict."""
        kg = MagicMock()
        kg.query.return_value = _spo_bindings([])
        svc = _make_service(kg)

        result = svc.get_phase_facts("idea-999")

        assert result == {}

    def test_query_exception_returns_empty_dict(self) -> None:
        """On SPARQL error, return empty dict and log the error."""
        kg = MagicMock()
        kg.query.side_effect = RuntimeError("Oxigraph unavailable")
        svc = _make_service(kg)

        result = svc.get_phase_facts("idea-broken")

        assert result == {}

    def test_sparql_query_uses_idea_id(self) -> None:
        """The SPARQL query filters by the given idea_id."""
        kg = MagicMock()
        kg.query.return_value = _spo_bindings([])
        svc = _make_service(kg)

        svc.get_phase_facts("idea-42")

        sparql_arg = kg.query.call_args[0][0]
        assert "idea-42" in sparql_arg

    def test_metadata_predicates_are_skipped(self) -> None:
        """Non-preserves predicates (forRequirement, producedBy, rdf:type) are excluded."""
        kg = MagicMock()
        kg.query.return_value = _spo_bindings([
            (f"{PHASE_NS}idea50-d4", f"{PHASE_NS}preserves-gaps_found", "3"),
            (f"{PHASE_NS}idea50-d4", f"{PHASE_NS}forRequirement", "idea50"),
            (f"{PHASE_NS}idea50-d4", f"{PHASE_NS}producedBy", "d4"),
            (f"{PHASE_NS}idea50-d4", "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", f"{PHASE_NS}PhaseOutput"),
        ])
        svc = _make_service(kg)

        result = svc.get_phase_facts("idea50")

        assert result == {"d4": {"gaps_found": 3}}


# -- Helpers for get_phase_detail tests ------------------------------------

def _po_bindings(pairs: list[tuple[str, str]]) -> SimpleNamespace:
    """Create a fake SPARQL result with .bindings for predicate-object pairs."""
    return SimpleNamespace(bindings=[{"p": p, "o": o} for p, o in pairs])


class TestGetPhaseDetail:
    """Tests for DashboardService.get_phase_detail()."""

    def test_separates_intent_fields_from_metadata(self) -> None:
        """Intent fields (preserves-*) are separated from metadata predicates."""
        kg = MagicMock()
        # First call: phase detail query; second call: traverse_chain ancestor query;
        # third call: traverse_chain facts query for starting subject
        kg.query.side_effect = [
            _po_bindings([
                (f"{PHASE_NS}preserves-tools_found", "16"),
                (f"{PHASE_NS}preserves-mcp_servers_found", "3"),
                (f"{PHASE_NS}forRequirement", "idea50"),
                (f"{PHASE_NS}producedBy", "d1"),
                ("http://www.w3.org/1999/02/22-rdf-syntax-ns#type", f"{PHASE_NS}PhaseOutput"),
            ]),
            # traverse_chain ancestor query returns no ancestors
            SimpleNamespace(bindings=[]),
            # traverse_chain facts query for starting subject
            SimpleNamespace(bindings=[]),
        ]
        svc = _make_service(kg)

        result = svc.get_phase_detail("idea50", "d1")

        assert result is not None
        assert result["phase_id"] == "d1"
        assert result["idea_id"] == "idea50"
        assert result["intent_fields"] == {
            "tools_found": "16",
            "mcp_servers_found": "3",
        }
        assert f"{PHASE_NS}forRequirement" in result["metadata"]
        assert f"{PHASE_NS}producedBy" in result["metadata"]
        assert "http://www.w3.org/1999/02/22-rdf-syntax-ns#type" in result["metadata"]

    def test_trace_ancestors_populated(self) -> None:
        """traverse_chain ancestors are returned as URI strings."""
        kg = MagicMock()
        kg.query.side_effect = [
            # Phase detail query
            _po_bindings([
                (f"{PHASE_NS}preserves-quadrant", "Major Project"),
                (f"{PHASE_NS}producedBy", "d3"),
            ]),
            # traverse_chain ancestor query — d2 and d1 are ancestors
            SimpleNamespace(bindings=[
                {"ancestor": f"{PHASE_NS}idea50-d2"},
                {"ancestor": f"{PHASE_NS}idea50-d1"},
            ]),
            # traverse_chain facts for starting subject (d3)
            SimpleNamespace(bindings=[]),
            # traverse_chain facts for d2
            SimpleNamespace(bindings=[]),
            # traverse_chain facts for d1
            SimpleNamespace(bindings=[]),
        ]
        svc = _make_service(kg)

        result = svc.get_phase_detail("idea50", "d3")

        assert result is not None
        assert result["trace_ancestors"] == [
            f"{PHASE_NS}idea50-d2",
            f"{PHASE_NS}idea50-d1",
        ]

    def test_returns_none_when_no_triples(self) -> None:
        """Return None if no triples exist for the subject."""
        kg = MagicMock()
        kg.query.return_value = _po_bindings([])
        svc = _make_service(kg)

        result = svc.get_phase_detail("idea-999", "d1")

        assert result is None

    def test_returns_none_on_query_exception(self) -> None:
        """On SPARQL error, return None."""
        kg = MagicMock()
        kg.query.side_effect = RuntimeError("Oxigraph unavailable")
        svc = _make_service(kg)

        result = svc.get_phase_detail("idea-broken", "d2")

        assert result is None

    def test_traverse_chain_error_gives_empty_ancestors(self) -> None:
        """If traverse_chain fails, trace_ancestors is an empty list."""
        kg = MagicMock()
        # First call succeeds (detail query), then all subsequent calls fail
        kg.query.side_effect = [
            _po_bindings([
                (f"{PHASE_NS}preserves-gaps_found", "5"),
                (f"{PHASE_NS}producedBy", "d4"),
            ]),
            RuntimeError("traverse query failed"),
        ]
        svc = _make_service(kg)

        result = svc.get_phase_detail("idea50", "d4")

        assert result is not None
        assert result["trace_ancestors"] == []
        assert result["intent_fields"] == {"gaps_found": "5"}

    def test_only_preserves_predicates_are_intent_fields(self) -> None:
        """Non-preserves predicates never appear in intent_fields."""
        kg = MagicMock()
        kg.query.side_effect = [
            _po_bindings([
                (f"{PHASE_NS}preserves-persona_count", "5"),
                (f"{PHASE_NS}forRequirement", "idea7"),
                (f"{PHASE_NS}producedBy", "d2"),
            ]),
            SimpleNamespace(bindings=[]),
            SimpleNamespace(bindings=[]),
        ]
        svc = _make_service(kg)

        result = svc.get_phase_detail("idea7", "d2")

        assert result is not None
        assert list(result["intent_fields"].keys()) == ["persona_count"]
        # forRequirement and producedBy should be in metadata, not intent_fields
        assert "forRequirement" not in result["intent_fields"]
        assert "producedBy" not in result["intent_fields"]


# -- Helpers for resolve_uri tests -----------------------------------------

def _type_bindings(types: list[str]) -> SimpleNamespace:
    """Create a fake SPARQL result with .bindings for rdf:type values."""
    return SimpleNamespace(bindings=[{"type": t} for t in types])


class TestResolveUri:
    """Tests for DashboardService.resolve_uri()."""

    def test_phase_output_dispatch(self) -> None:
        """A URI with rdf:type phase:PhaseOutput maps to phase_detail."""
        kg = MagicMock()
        kg.query.return_value = _type_bindings([f"{PHASE_NS}PhaseOutput"])
        svc = _make_service(kg)

        route, params = svc.resolve_uri(f"{PHASE_NS}idea50-d1")

        assert route == "phase_detail"
        assert params == {"idea_id": "idea50", "phase_id": "d1"}

    def test_skos_concept_dispatch(self) -> None:
        """A URI with rdf:type skos:Concept maps to idea_detail with extracted id."""
        kg = MagicMock()
        kg.query.return_value = _type_bindings(
            ["http://www.w3.org/2004/02/skos/core#Concept"]
        )
        svc = _make_service(kg)

        route, params = svc.resolve_uri("http://example.org/ideas/idea-42")

        assert route == "idea_detail"
        assert params == {"idea_id": "idea-42"}

    def test_prd_namespace_dispatch(self) -> None:
        """A URI whose rdf:type is in the prd: namespace maps to requirement_detail."""
        kg = MagicMock()
        kg.query.return_value = _type_bindings(["http://tulla.dev/prd#Requirement"])
        svc = _make_service(kg)

        route, params = svc.resolve_uri("http://example.org/prd-idea-50/req-50-1-1")

        assert route == "requirement_detail"
        assert params == {"context": "prd-idea-50", "subject": "req-50-1-1"}

    def test_prd_compact_prefix_dispatch(self) -> None:
        """A URI whose rdf:type uses the compact prd: prefix also dispatches."""
        kg = MagicMock()
        kg.query.return_value = _type_bindings(["prd:Requirement"])
        svc = _make_service(kg)

        route, params = svc.resolve_uri("http://example.org/prd-idea-50/req-50-2-1")

        assert route == "requirement_detail"
        assert params == {"context": "prd-idea-50", "subject": "req-50-2-1"}

    def test_unknown_type_fallback(self) -> None:
        """An unrecognized rdf:type returns generic_detail."""
        kg = MagicMock()
        kg.query.return_value = _type_bindings(["http://example.org/UnknownClass"])
        svc = _make_service(kg)

        route, params = svc.resolve_uri("http://example.org/something")

        assert route == "generic_detail"
        assert params == {"uri": "http://example.org/something"}

    def test_no_type_found_fallback(self) -> None:
        """When no rdf:type triples exist, return generic_detail."""
        kg = MagicMock()
        kg.query.return_value = _type_bindings([])
        svc = _make_service(kg)

        route, params = svc.resolve_uri("http://example.org/orphan")

        assert route == "generic_detail"
        assert params == {"uri": "http://example.org/orphan"}

    def test_query_exception_fallback(self) -> None:
        """On SPARQL error, return generic_detail."""
        kg = MagicMock()
        kg.query.side_effect = RuntimeError("Oxigraph unavailable")
        svc = _make_service(kg)

        route, params = svc.resolve_uri("http://example.org/broken")

        assert route == "generic_detail"
        assert params == {"uri": "http://example.org/broken"}

    def test_self_referential_guard(self) -> None:
        """URIs starting with the resolver's own prefix are rejected to prevent loops."""
        svc = _make_service()

        route, params = svc.resolve_uri("/resolve/http://example.org/foo")

        assert route == "generic_detail"
        assert params == {"uri": "/resolve/http://example.org/foo"}
        # kg_store.query should NOT have been called
        svc._kg_store.query.assert_not_called()


# -- Helpers for get_iteration_facts tests ---------------------------------


def _iteration_bindings(
    triples: list[tuple[str, str, str]],
) -> SimpleNamespace:
    """Create a fake SPARQL result with .bindings for iteration SPO triples."""
    return SimpleNamespace(
        bindings=[{"s": s, "p": p, "o": o} for s, p, o in triples],
    )


class TestGetIterationFacts:
    """Tests for DashboardService.get_iteration_facts()."""

    def test_extracts_all_five_intent_fields(self) -> None:
        """All five intent fields are extracted from iteration triples."""
        kg = MagicMock()
        kg.query.return_value = _iteration_bindings([
            (f"{PHASE_NS}idea50-impl-1", f"{PHASE_NS}preserves-requirement_id", "req-50-1-1"),
            (f"{PHASE_NS}idea50-impl-1", f"{PHASE_NS}preserves-quality_focus", "isaqb:FunctionalCorrectness"),
            (f"{PHASE_NS}idea50-impl-1", f"{PHASE_NS}preserves-passed", "true"),
            (f"{PHASE_NS}idea50-impl-1", f"{PHASE_NS}preserves-feedback", "All tests pass"),
            (f"{PHASE_NS}idea50-impl-1", f"{PHASE_NS}preserves-commit_hash", "abc1234"),
        ])
        svc = _make_service(kg)

        result = svc.get_iteration_facts("idea50")

        assert len(result) == 1
        assert result[0] == {
            "requirement_id": "req-50-1-1",
            "quality_focus": "isaqb:FunctionalCorrectness",
            "passed": "true",
            "feedback": "All tests pass",
            "commit_hash": "abc1234",
        }

    def test_multiple_iterations_ordered_by_subject(self) -> None:
        """Multiple iterations are returned ordered by subject URI."""
        kg = MagicMock()
        kg.query.return_value = _iteration_bindings([
            (f"{PHASE_NS}idea50-impl-2", f"{PHASE_NS}preserves-requirement_id", "req-50-1-2"),
            (f"{PHASE_NS}idea50-impl-2", f"{PHASE_NS}preserves-passed", "false"),
            (f"{PHASE_NS}idea50-impl-1", f"{PHASE_NS}preserves-requirement_id", "req-50-1-1"),
            (f"{PHASE_NS}idea50-impl-1", f"{PHASE_NS}preserves-passed", "true"),
        ])
        svc = _make_service(kg)

        result = svc.get_iteration_facts("idea50")

        assert len(result) == 2
        # impl-1 comes before impl-2 alphabetically
        assert result[0]["requirement_id"] == "req-50-1-1"
        assert result[0]["passed"] == "true"
        assert result[1]["requirement_id"] == "req-50-1-2"
        assert result[1]["passed"] == "false"

    def test_non_intent_predicates_are_excluded(self) -> None:
        """Non-intent predicates (forRequirement, producedBy, etc.) are excluded."""
        kg = MagicMock()
        kg.query.return_value = _iteration_bindings([
            (f"{PHASE_NS}idea50-impl-1", f"{PHASE_NS}preserves-requirement_id", "req-50-1-1"),
            (f"{PHASE_NS}idea50-impl-1", f"{PHASE_NS}preserves-passed", "true"),
            (f"{PHASE_NS}idea50-impl-1", f"{PHASE_NS}forRequirement", "idea50"),
            (f"{PHASE_NS}idea50-impl-1", f"{PHASE_NS}producedBy", "impl-1"),
            (f"{PHASE_NS}idea50-impl-1", f"{PHASE_NS}preserves-unknown_field", "ignored"),
        ])
        svc = _make_service(kg)

        result = svc.get_iteration_facts("idea50")

        assert len(result) == 1
        assert set(result[0].keys()) == {"requirement_id", "passed"}

    def test_empty_query_returns_empty_list(self) -> None:
        """When no iteration triples match, return an empty list."""
        kg = MagicMock()
        kg.query.return_value = _iteration_bindings([])
        svc = _make_service(kg)

        result = svc.get_iteration_facts("idea-999")

        assert result == []

    def test_query_exception_returns_empty_list(self) -> None:
        """On SPARQL error, return empty list and log the error."""
        kg = MagicMock()
        kg.query.side_effect = RuntimeError("Oxigraph unavailable")
        svc = _make_service(kg)

        result = svc.get_iteration_facts("idea-broken")

        assert result == []

    def test_sparql_query_uses_idea_id(self) -> None:
        """The SPARQL query filters by the given idea_id."""
        kg = MagicMock()
        kg.query.return_value = _iteration_bindings([])
        svc = _make_service(kg)

        svc.get_iteration_facts("idea-42")

        sparql_arg = kg.query.call_args[0][0]
        assert "idea-42" in sparql_arg

    def test_sparql_query_filters_impl_phases(self) -> None:
        """The SPARQL query includes a STRSTARTS filter for impl- phases."""
        kg = MagicMock()
        kg.query.return_value = _iteration_bindings([])
        svc = _make_service(kg)

        svc.get_iteration_facts("idea-50")

        sparql_arg = kg.query.call_args[0][0]
        assert 'STRSTARTS' in sparql_arg
        assert '"impl-"' in sparql_arg


# -- Tests for get_requirement_phase_history --------------------------------


class TestGetRequirementPhaseHistory:
    """Tests for DashboardService.get_requirement_phase_history()."""

    def test_three_phase_outputs_ordered_with_correct_fields(self) -> None:
        """Mock data for a requirement with three phase outputs; assert ordered and correct."""
        kg = MagicMock()
        # Three phase outputs linked to requirement "req-50-1-1"
        kg.query.return_value = _spo_bindings([
            # d1 output
            (f"{PHASE_NS}idea50-d1", f"{PHASE_NS}producedBy", "d1"),
            (f"{PHASE_NS}idea50-d1", f"{PHASE_NS}forRequirement", "req-50-1-1"),
            (f"{PHASE_NS}idea50-d1", f"{PHASE_NS}preserves-tools_found", "16"),
            (f"{PHASE_NS}idea50-d1", f"{PHASE_NS}preserves-mcp_servers_found", "3"),
            # d2 output
            (f"{PHASE_NS}idea50-d2", f"{PHASE_NS}producedBy", "d2"),
            (f"{PHASE_NS}idea50-d2", f"{PHASE_NS}forRequirement", "req-50-1-1"),
            (f"{PHASE_NS}idea50-d2", f"{PHASE_NS}preserves-persona_count", "5"),
            (f"{PHASE_NS}idea50-d2", f"{PHASE_NS}preserves-timestamp", "2026-02-04T09:00:00"),
            # d3 output
            (f"{PHASE_NS}idea50-d3", f"{PHASE_NS}producedBy", "d3"),
            (f"{PHASE_NS}idea50-d3", f"{PHASE_NS}forRequirement", "req-50-1-1"),
            (f"{PHASE_NS}idea50-d3", f"{PHASE_NS}preserves-quadrant", "Major Project"),
            (f"{PHASE_NS}idea50-d3", f"{PHASE_NS}preserves-total_value_score", "42"),
        ])
        svc = _make_service(kg)

        result = svc.get_requirement_phase_history("prd-idea-50", "req-50-1-1")

        assert len(result) == 3

        # Ordered by subject URI: idea50-d1, idea50-d2, idea50-d3
        assert result[0]["phase_id"] == "d1"
        assert result[0]["produced_by"] == "d1"
        assert result[0]["intent_fields"] == {
            "tools_found": "16",
            "mcp_servers_found": "3",
        }
        assert result[0]["timestamp"] is None

        assert result[1]["phase_id"] == "d2"
        assert result[1]["produced_by"] == "d2"
        assert result[1]["intent_fields"] == {"persona_count": "5"}
        assert result[1]["timestamp"] == "2026-02-04T09:00:00"

        assert result[2]["phase_id"] == "d3"
        assert result[2]["produced_by"] == "d3"
        assert result[2]["intent_fields"] == {
            "quadrant": "Major Project",
            "total_value_score": "42",
        }
        assert result[2]["timestamp"] is None

    def test_follows_traces_to_chain(self) -> None:
        """Phase outputs linked via trace:tracesTo are included in the result."""
        trace_pred = "http://tulla.dev/trace#tracesTo"
        kg = MagicMock()
        # d3 links to d2 via tracesTo; d2 is not directly forRequirement
        kg.query.side_effect = [
            # First query: forRequirement match — only d3
            _spo_bindings([
                (f"{PHASE_NS}idea50-d3", f"{PHASE_NS}producedBy", "d3"),
                (f"{PHASE_NS}idea50-d3", f"{PHASE_NS}forRequirement", "req-50-1-1"),
                (f"{PHASE_NS}idea50-d3", f"{PHASE_NS}preserves-quadrant", "Major"),
                (f"{PHASE_NS}idea50-d3", trace_pred, f"{PHASE_NS}idea50-d2"),
            ]),
            # Second query: ancestor d2's triples
            _po_bindings([
                (f"{PHASE_NS}producedBy", "d2"),
                (f"{PHASE_NS}preserves-persona_count", "5"),
            ]),
        ]
        svc = _make_service(kg)

        result = svc.get_requirement_phase_history("prd-idea-50", "req-50-1-1")

        assert len(result) == 2
        # d2 comes before d3 alphabetically
        assert result[0]["phase_id"] == "d2"
        assert result[0]["intent_fields"] == {"persona_count": "5"}
        assert result[1]["phase_id"] == "d3"
        assert result[1]["intent_fields"] == {"quadrant": "Major"}

    def test_empty_query_returns_empty_list(self) -> None:
        """When no phase outputs match, return an empty list."""
        kg = MagicMock()
        kg.query.return_value = _spo_bindings([])
        svc = _make_service(kg)

        result = svc.get_requirement_phase_history("prd-idea-999", "req-999-1-1")

        assert result == []

    def test_query_exception_returns_empty_list(self) -> None:
        """On SPARQL error, return empty list."""
        kg = MagicMock()
        kg.query.side_effect = RuntimeError("Oxigraph unavailable")
        svc = _make_service(kg)

        result = svc.get_requirement_phase_history("prd-idea-broken", "req-broken")

        assert result == []

    def test_sparql_query_uses_subject(self) -> None:
        """The SPARQL query includes the requirement subject in the forRequirement filter."""
        kg = MagicMock()
        kg.query.return_value = _spo_bindings([])
        svc = _make_service(kg)

        svc.get_requirement_phase_history("prd-idea-42", "req-42-1-1")

        sparql_arg = kg.query.call_args[0][0]
        assert "req-42-1-1" in sparql_arg

    def test_metadata_predicates_excluded_from_intent_fields(self) -> None:
        """Non-preserves predicates are excluded from intent_fields."""
        kg = MagicMock()
        kg.query.return_value = _spo_bindings([
            (f"{PHASE_NS}idea50-d1", f"{PHASE_NS}producedBy", "d1"),
            (f"{PHASE_NS}idea50-d1", f"{PHASE_NS}forRequirement", "req-50-1-1"),
            (f"{PHASE_NS}idea50-d1", f"{PHASE_NS}preserves-tools_found", "16"),
            (f"{PHASE_NS}idea50-d1", "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", f"{PHASE_NS}PhaseOutput"),
        ])
        svc = _make_service(kg)

        result = svc.get_requirement_phase_history("prd-idea-50", "req-50-1-1")

        assert len(result) == 1
        assert result[0]["intent_fields"] == {"tools_found": "16"}
        assert "forRequirement" not in result[0]["intent_fields"]

    def test_result_contains_all_required_keys(self) -> None:
        """Every item in the result contains phase_id, produced_by, intent_fields, timestamp."""
        kg = MagicMock()
        kg.query.return_value = _spo_bindings([
            (f"{PHASE_NS}idea50-d1", f"{PHASE_NS}producedBy", "d1"),
            (f"{PHASE_NS}idea50-d1", f"{PHASE_NS}forRequirement", "req-50-1-1"),
        ])
        svc = _make_service(kg)

        result = svc.get_requirement_phase_history("prd-idea-50", "req-50-1-1")

        assert len(result) == 1
        assert set(result[0].keys()) == {"phase_id", "produced_by", "intent_fields", "timestamp"}


# -- Tests for get_project_detail ------------------------------------------


class TestGetProjectDetail:
    """Tests for DashboardService.get_project_detail()."""

    def test_returns_properties_for_existing_project(self) -> None:
        """A project with triples returns found=True and populated properties."""
        kg = MagicMock()
        kg.query.return_value = _po_bindings([
            ("http://www.w3.org/1999/02/22-rdf-syntax-ns#type", f"{PRD_NS}Project"),
            (f"{PRD_NS}hasTitle", "My Project"),
            (f"{PRD_NS}hasRequirement", f"{PRD_NS}req-1-1"),
            (f"{PRD_NS}hasRequirement", f"{PRD_NS}req-1-2"),
        ])
        svc = _make_service(kg)

        result = svc.get_project_detail("prd-idea-50")

        assert result["found"] is True
        assert result["project_id"] == "prd-idea-50"
        assert result["uri"] == f"{PRD_NS}prd-idea-50"
        assert "http://www.w3.org/1999/02/22-rdf-syntax-ns#type" in result["properties"]
        assert result["properties"][f"{PRD_NS}hasTitle"] == ["My Project"]
        assert result["properties"][f"{PRD_NS}hasRequirement"] == [
            f"{PRD_NS}req-1-1",
            f"{PRD_NS}req-1-2",
        ]

    def test_multi_valued_predicates_collected_as_list(self) -> None:
        """Multiple objects for the same predicate are collected into a list."""
        kg = MagicMock()
        kg.query.return_value = _po_bindings([
            (f"{PRD_NS}hasRequirement", f"{PRD_NS}req-1"),
            (f"{PRD_NS}hasRequirement", f"{PRD_NS}req-2"),
            (f"{PRD_NS}hasRequirement", f"{PRD_NS}req-3"),
        ])
        svc = _make_service(kg)

        result = svc.get_project_detail("proj-1")

        assert len(result["properties"][f"{PRD_NS}hasRequirement"]) == 3

    def test_not_found_returns_empty_properties(self) -> None:
        """When no triples match, found is False and properties is empty."""
        kg = MagicMock()
        kg.query.return_value = _po_bindings([])
        svc = _make_service(kg)

        result = svc.get_project_detail("nonexistent")

        assert result["found"] is False
        assert result["project_id"] == "nonexistent"
        assert result["uri"] == f"{PRD_NS}nonexistent"
        assert result["properties"] == {}

    def test_query_exception_returns_not_found(self) -> None:
        """On SPARQL error, return found=False with empty properties."""
        kg = MagicMock()
        kg.query.side_effect = RuntimeError("Oxigraph unavailable")
        svc = _make_service(kg)

        result = svc.get_project_detail("broken-proj")

        assert result["found"] is False
        assert result["project_id"] == "broken-proj"
        assert result["properties"] == {}

    def test_uri_construction_uses_prd_ns(self) -> None:
        """The project URI is constructed as PRD_NS + project_id."""
        kg = MagicMock()
        kg.query.return_value = _po_bindings([])
        svc = _make_service(kg)

        result = svc.get_project_detail("prd-idea-79")

        assert result["uri"] == f"{PRD_NS}prd-idea-79"

    def test_sparql_queries_phases_graph(self) -> None:
        """The SPARQL query targets the phases named graph."""
        kg = MagicMock()
        kg.query.return_value = _po_bindings([])
        svc = _make_service(kg)

        svc.get_project_detail("prd-idea-42")

        sparql_arg = kg.query.call_args[0][0]
        assert PHASES_GRAPH in sparql_arg

    def test_sparql_query_uses_project_id_in_uri(self) -> None:
        """The SPARQL query includes the project_id within the constructed URI."""
        kg = MagicMock()
        kg.query.return_value = _po_bindings([])
        svc = _make_service(kg)

        svc.get_project_detail("prd-idea-42")

        sparql_arg = kg.query.call_args[0][0]
        assert "prd-idea-42" in sparql_arg
