"""Fixture-first validation gate for tools/gate_audit.py verdict logic (T3.1).

Drives the PURE classification and hop-evaluation functions
(classify_phases, evaluate_hop via evaluate_coverage_chain, and
coverage_overall) with recorded idea-15 fixture bindings -- a snapshot of
the live post-gate run captured through gate_audit's own fetch layer
(derive_spec / fetch_phase_listing / fetch_d5_mode / fetch_coverage_fields
against the running ontology server, 2026-07-06). No test here performs
I/O or needs a live server (ADR-003, quality goal Modifiability P1).

ADR-003 checklist covered by this suite:

- 0 phase misclassifications on the idea-15 fixture (EXP4 baseline,
  extended to the full 23-phase derived pipeline: 17 persisted, 6
  not-persisted).
- 12/12 hop/verdict cases (R5 exp1 matrix: post-gate PASS chain, legacy
  predicate-absent chain, planning-not-run chain -- 3 scenarios x
  (3 hops + overall verdict)).
- the "[]" and "pass" sentinel conditions (raw-literal comparison).
- missing-claimed dangling-edge detection (both live URI conventions).
- the not-persisted ambiguity note, present on every such row.
- NOT-EVALUATED leniency for legacy predicate-absent nodes (never FAIL).
- COVERAGE: PASS iff every hop is CLOSED (verdict precedence fold).

The recorded coverage literals are VERBATIM raw strings as fetched, but
trimmed to the fields COVERAGE_HOP_JOINS reads (join source/map, uncovered
list, gate literal) plus d5's mode -- dropping predicates evaluate_hop
never touches keeps the snapshot reviewable without changing any verdict
input. Both coverage-map serializations are exercised: the live idea-15
list-of-dicts form (recorded below) and the R5 exp1 dict form (synthesized
in test_coverage_map_dict_serialization_also_closes).
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

# tools/gate_audit.py is a single file with no package __init__ (ADR-001):
# import it by path rather than pointing sys.path at a non-package dir.
_GATE_AUDIT_PATH = (
    Path(__file__).resolve().parents[2] / "tools" / "gate_audit.py"
)
_module_spec = importlib.util.spec_from_file_location(
    "gate_audit", _GATE_AUDIT_PATH
)
assert _module_spec is not None and _module_spec.loader is not None
gate_audit = importlib.util.module_from_spec(_module_spec)
sys.modules.setdefault("gate_audit", gate_audit)
_module_spec.loader.exec_module(gate_audit)


IDEA = "idea-15"

# ---------------------------------------------------------------------------
# Recorded idea-15 fixture bindings (live post-gate snapshot, 2026-07-06).
# spec     = derive_spec()          -- 23-phase pipeline, 23 gate shapes
# listing  = fetch_phase_listing()  -- 17 persisted phase nodes
# d5_mode  = fetch_d5_mode()        -- "research" (skips nothing)
# coverage = fetch_coverage_fields() trimmed to the hop-read fields
# ---------------------------------------------------------------------------
IDEA15_FIXTURE = {'spec': {'pipeline': [{'phase_id': 'd1', 'family': 'discovery', 'depth': 0},
                       {'phase_id': 'd2', 'family': 'discovery', 'depth': 1},
                       {'phase_id': 'd3', 'family': 'discovery', 'depth': 2},
                       {'phase_id': 'd4', 'family': 'discovery', 'depth': 3},
                       {'phase_id': 'd5', 'family': 'discovery', 'depth': 4},
                       {'phase_id': 'i1',
                        'family': 'implementation',
                        'depth': 0},
                       {'phase_id': 'intake',
                        'family': 'lightweight',
                        'depth': 0},
                       {'phase_id': 'context-scan',
                        'family': 'lightweight',
                        'depth': 2},
                       {'phase_id': 'plan',
                        'family': 'lightweight',
                        'depth': 4},
                       {'phase_id': 'execute',
                        'family': 'lightweight',
                        'depth': 6},
                       {'phase_id': 'trace',
                        'family': 'lightweight',
                        'depth': 8},
                       {'phase_id': 'p1', 'family': 'planning', 'depth': 0},
                       {'phase_id': 'p2', 'family': 'planning', 'depth': 1},
                       {'phase_id': 'p3', 'family': 'planning', 'depth': 2},
                       {'phase_id': 'p4', 'family': 'planning', 'depth': 3},
                       {'phase_id': 'p5', 'family': 'planning', 'depth': 4},
                       {'phase_id': 'p6', 'family': 'planning', 'depth': 5},
                       {'phase_id': 'r1', 'family': 'research', 'depth': 0},
                       {'phase_id': 'r2', 'family': 'research', 'depth': 1},
                       {'phase_id': 'r3', 'family': 'research', 'depth': 2},
                       {'phase_id': 'r4', 'family': 'research', 'depth': 3},
                       {'phase_id': 'r5', 'family': 'research', 'depth': 4},
                       {'phase_id': 'r6', 'family': 'research', 'depth': 5}],
          'gates_by_phase': {'p4': ['http://tulla.dev/phase#P4OutputShape'],
                             'd1': ['http://tulla.dev/phase#D1OutputShape'],
                             'intake': ['http://tulla.dev/phase#LWIntakeOutputShape'],
                             'r4': ['http://tulla.dev/phase#R4OutputShape'],
                             'p1': ['http://tulla.dev/phase#P1OutputShape'],
                             'i1': ['http://tulla.dev/phase#I1OutputShape'],
                             'p3': ['http://tulla.dev/phase#P3OutputShape'],
                             'p2': ['http://tulla.dev/phase#P2OutputShape'],
                             'plan': ['http://tulla.dev/phase#LWPlanOutputShape'],
                             'p5': ['http://tulla.dev/phase#P5OutputShape'],
                             'r5': ['http://tulla.dev/phase#R5OutputShape'],
                             'd5': ['http://tulla.dev/phase#D5OutputShape'],
                             'd2': ['http://tulla.dev/phase#D2OutputShape'],
                             'r6': ['http://tulla.dev/phase#R6OutputShape'],
                             'execute': ['http://tulla.dev/phase#LWExecuteOutputShape'],
                             'd3': ['http://tulla.dev/phase#D3OutputShape'],
                             'context-scan': ['http://tulla.dev/phase#LWContextScanOutputShape'],
                             'r1': ['http://tulla.dev/phase#R1OutputShape'],
                             'p6': ['http://tulla.dev/phase#P6OutputShape'],
                             'd4': ['http://tulla.dev/phase#D4OutputShape'],
                             'trace': ['http://tulla.dev/phase#LWTraceOutputShape'],
                             'r3': ['http://tulla.dev/phase#R3OutputShape'],
                             'r2': ['http://tulla.dev/phase#R2OutputShape']},
          'gate_uris': ['http://tulla.dev/phase#D1OutputShape',
                        'http://tulla.dev/phase#D2OutputShape',
                        'http://tulla.dev/phase#D3OutputShape',
                        'http://tulla.dev/phase#D4OutputShape',
                        'http://tulla.dev/phase#D5OutputShape',
                        'http://tulla.dev/phase#I1OutputShape',
                        'http://tulla.dev/phase#LWContextScanOutputShape',
                        'http://tulla.dev/phase#LWExecuteOutputShape',
                        'http://tulla.dev/phase#LWIntakeOutputShape',
                        'http://tulla.dev/phase#LWPlanOutputShape',
                        'http://tulla.dev/phase#LWTraceOutputShape',
                        'http://tulla.dev/phase#P1OutputShape',
                        'http://tulla.dev/phase#P2OutputShape',
                        'http://tulla.dev/phase#P3OutputShape',
                        'http://tulla.dev/phase#P4OutputShape',
                        'http://tulla.dev/phase#P5OutputShape',
                        'http://tulla.dev/phase#P6OutputShape',
                        'http://tulla.dev/phase#R1OutputShape',
                        'http://tulla.dev/phase#R2OutputShape',
                        'http://tulla.dev/phase#R3OutputShape',
                        'http://tulla.dev/phase#R4OutputShape',
                        'http://tulla.dev/phase#R5OutputShape',
                        'http://tulla.dev/phase#R6OutputShape'],
          'coverage_fields': {'d5': ['key_constraints',
                                     'mandatory_features',
                                     'mode',
                                     'northstar',
                                     'recommendation'],
                              'p1': ['discovery_summary',
                                     'feature_scope',
                                     'jtbd_traceability',
                                     'mandatory_feature_coverage',
                                     'non_negotiable_constraints',
                                     'out_of_scope',
                                     'scope_boundaries',
                                     'scope_decisions',
                                     'success_metrics',
                                     'target_audience',
                                     'uncovered_mandatory_features'],
                              'p4': ['blocked_tasks',
                                     'critical_path',
                                     'estimated_complexity',
                                     'feature_coverage',
                                     'implementation_phases',
                                     'implementation_summary',
                                     'p0_count',
                                     'p1_count',
                                     'p2_count',
                                     'task_count',
                                     'tasks',
                                     'uncovered_features'],
                              'p6': ['coverage_gate',
                                     'p0_count',
                                     'p1_count',
                                     'p2_count',
                                     'prd_context',
                                     'prd_file',
                                     'requirement_count',
                                     'requirements_exported',
                                     'uncovered_features']}},
 'listing': [{'phase_id': 'd1',
              'result_uri': 'http://tulla.dev/phase#idea-15-d1',
              'traces_to': [],
              'pipeline_index': 0},
             {'phase_id': 'd2',
              'result_uri': 'http://tulla.dev/phase#idea-15-d2',
              'traces_to': ['http://tulla.dev/phase#idea-15-d1'],
              'pipeline_index': 1},
             {'phase_id': 'd3',
              'result_uri': 'http://tulla.dev/phase#idea-15-d3',
              'traces_to': ['http://tulla.dev/phase#idea-15-d2'],
              'pipeline_index': 2},
             {'phase_id': 'd4',
              'result_uri': 'http://tulla.dev/phase#idea-15-d4',
              'traces_to': ['http://tulla.dev/phase#idea-15-d3'],
              'pipeline_index': 3},
             {'phase_id': 'd5',
              'result_uri': 'http://tulla.dev/phase#idea-15-d5',
              'traces_to': ['http://tulla.dev/phase#idea-15-d4'],
              'pipeline_index': 4},
             {'phase_id': 'p1',
              'result_uri': 'http://tulla.dev/phase#idea-15-p1',
              'traces_to': ['http://tulla.dev/phase#idea-15-r6'],
              'pipeline_index': 11},
             {'phase_id': 'p2',
              'result_uri': 'http://tulla.dev/phase#idea-15-p2',
              'traces_to': ['http://tulla.dev/phase#idea-15-p1'],
              'pipeline_index': 12},
             {'phase_id': 'p3',
              'result_uri': 'http://tulla.dev/phase#idea-15-p3',
              'traces_to': ['http://tulla.dev/phase#idea-15-p2'],
              'pipeline_index': 13},
             {'phase_id': 'p4',
              'result_uri': 'http://tulla.dev/phase#idea-15-p4',
              'traces_to': ['http://tulla.dev/phase#idea-15-p3'],
              'pipeline_index': 14},
             {'phase_id': 'p5',
              'result_uri': 'http://tulla.dev/phase#idea-15-p5',
              'traces_to': ['http://tulla.dev/phase#idea-15-p4'],
              'pipeline_index': 15},
             {'phase_id': 'p6',
              'result_uri': 'http://tulla.dev/phase#idea-15-p6',
              'traces_to': ['http://tulla.dev/phase#idea-15-p5'],
              'pipeline_index': 16},
             {'phase_id': 'r1',
              'result_uri': 'http://tulla.dev/phase#idea-15-r1',
              'traces_to': ['http://tulla.dev/phase#idea-15-d5'],
              'pipeline_index': 17},
             {'phase_id': 'r2',
              'result_uri': 'http://tulla.dev/phase#idea-15-r2',
              'traces_to': ['http://tulla.dev/phase#idea-15-r1'],
              'pipeline_index': 18},
             {'phase_id': 'r3',
              'result_uri': 'http://tulla.dev/phase#idea-15-r3',
              'traces_to': ['http://tulla.dev/phase#idea-15-r2'],
              'pipeline_index': 19},
             {'phase_id': 'r4',
              'result_uri': 'http://tulla.dev/phase#idea-15-r4',
              'traces_to': ['http://tulla.dev/phase#idea-15-r3'],
              'pipeline_index': 20},
             {'phase_id': 'r5',
              'result_uri': 'http://tulla.dev/phase#idea-15-r5',
              'traces_to': ['http://tulla.dev/phase#idea-15-r4'],
              'pipeline_index': 21},
             {'phase_id': 'r6',
              'result_uri': 'http://tulla.dev/phase#idea-15-r6',
              'traces_to': ['http://tulla.dev/phase#idea-15-r5'],
              'pipeline_index': 22}],
 'd5_mode': 'research',
 'coverage': {'d5': {'mandatory_features': '["Phase listing: given an idea '
                                           'id, query the ontology-server '
                                           'phases graph over its REST SPARQL '
                                           'endpoint and list every completed '
                                           'phase (d1..i1) with its '
                                           'phase:producedBy id and '
                                           'trace:tracesTo predecessor, in '
                                           'pipeline order", "Gate report: '
                                           'for each completed phase, show '
                                           'the SHACL gate shape URI declared '
                                           'via phase:shaclGate and whether a '
                                           'phase output exists for it '
                                           '(persisted = the gate passed, '
                                           'since nonconforming outputs are '
                                           'rolled back)", "Coverage-chain '
                                           'report: render the '
                                           'drift-prevention chain as a table '
                                           '\\u2014 D5 mandatory_features '
                                           '\\u2192 P1 feature_scope (+ '
                                           'uncovered_mandatory_features) '
                                           '\\u2192 P4 feature_coverage '
                                           '\\u2192 P6 '
                                           'coverage_gate/uncovered_features '
                                           '\\u2014 and print an overall '
                                           'verdict line: COVERAGE: PASS only '
                                           'if every link is closed", "JSON '
                                           'output mode: a --json flag that '
                                           'emits the same report as a '
                                           'machine-readable JSON object '
                                           'instead of tables"]',
                     'mode': 'research'},
              'p1': {'feature_scope': '[{"feature_id": "F1", "name": "Phase '
                                      'listing", "description": "Given an '
                                      'idea id, query the ontology-server '
                                      'phases graph over its REST SPARQL '
                                      'endpoint and list every completed '
                                      'phase (d1..i1) with its '
                                      'phase:producedBy id and trace:tracesTo '
                                      'predecessor, in pipeline order.", '
                                      '"acceptance_criteria": "For a known '
                                      'idea (e.g. idea-15 10-phase fixture), '
                                      'the CLI lists all persisted phases in '
                                      'the runtime-derived pipeline order, '
                                      'each row showing producedBy id and '
                                      'tracesTo predecessor; output matches '
                                      'the live graph exactly.", "priority": '
                                      '"P0"}, {"feature_id": "F2", "name": '
                                      '"Gate report with four-state phase '
                                      'classification", "description": "For '
                                      'each phase, show the SHACL gate shape '
                                      'URI declared via phase:shaclGate and '
                                      'its gate status using the R6-validated '
                                      'four-state classification: persisted, '
                                      'skipped, missing-claimed (dangling '
                                      'incoming trace edge), and '
                                      'not-persisted with an explicit '
                                      'never-ran-or-rolled-back ambiguity '
                                      'note.", "acceptance_criteria": "All '
                                      'phases of the idea-15 fixture classify '
                                      'with 0 misclassifications (EXP4 '
                                      'baseline); not-persisted states always '
                                      'carry the ambiguity note; persisted '
                                      'implies gate passed (rollback '
                                      'semantics).", "priority": "P0"}, '
                                      '{"feature_id": "F3", "name": '
                                      '"Coverage-chain report with per-hop '
                                      'verdict", "description": "Render the '
                                      'drift-prevention chain D5 '
                                      'mandatory_features -> P1 feature_scope '
                                      '(+ uncovered_mandatory_features) -> P4 '
                                      'feature_coverage -> P6 '
                                      'coverage_gate/uncovered_features as a '
                                      'table with per-hop states '
                                      '(CLOSED/OPEN/NOT-EVALUATED/MISSING-NODE), '
                                      'a client-side JSON join of every D5 '
                                      'feature into the downstream coverage '
                                      'map, and an overall COVERAGE: PASS '
                                      'line only if every link is closed.", '
                                      '"acceptance_criteria": "Per-hop '
                                      'itemized checks implement the R6 RQ2 '
                                      'closed-link conditions incl. '
                                      'uncovered-list == \\"[]\\" and P6 '
                                      'coverage_gate == \\"pass\\"; legacy '
                                      'predicate-absent nodes report '
                                      'NOT-EVALUATED, never FAIL; verdict '
                                      'logic validated by pytest against the '
                                      'first post-gate fixture before '
                                      'becoming verdict-affecting.", '
                                      '"priority": "P0"}, {"feature_id": '
                                      '"F4", "name": "JSON output mode '
                                      '(--json, SchemaVer 1-0-0)", '
                                      '"description": "A --json flag emitting '
                                      'the same report as a machine-readable '
                                      'JSON object: schema_version (SchemaVer '
                                      '1-0-0), frozen v1 enums for the four '
                                      'phase states and four hop states, '
                                      'per-hop itemized checks, an explicit '
                                      'limitations array, and '
                                      'non-verdict-affecting '
                                      'memory_coverage_links.", '
                                      '"acceptance_criteria": "JSON output '
                                      'validates against the frozen 1-0-0 '
                                      'schema; enums are frozen; evolution is '
                                      'additive-only within MODEL 1; '
                                      'memory_coverage_links is excluded from '
                                      'verdicts.overall.", "priority": "P0"}, '
                                      '{"feature_id": "F5", "name": "Runtime '
                                      'spec derivation at startup", '
                                      '"description": "Derive pipeline order, '
                                      'all declared phase:shaclGate URIs (23+ '
                                      'and growing), and the coverage field '
                                      'names at startup in at most 4 '
                                      'sub-second SELECTs against POST '
                                      "/kg/sparql; abort with 'spec not "
                                      "loaded' if gate derivation returns "
                                      'zero gates \\u2014 never fall back to '
                                      'a stale hardcoded list.", '
                                      '"acceptance_criteria": "Startup '
                                      'derivation completes within the 2 s '
                                      'budget (R5 measured p95 6.6 ms); gate '
                                      'enumeration uses phase:shaclGate '
                                      'directly (DISTINCT, not pipeline-order '
                                      'collapse); zero-gate result '
                                      "hard-aborts with 'spec not "
                                      'loaded\'.", "priority": "P0"}, '
                                      '{"feature_id": "F6", "name": "Sentinel '
                                      'sync convention", "description": '
                                      '"Hardcode only the \\"[]\\" and '
                                      '\\"pass\\" sentinel values (plus three '
                                      'namespace constants and hop-join '
                                      'semantics) under a named sync '
                                      'convention: marker comments at the '
                                      'sh:hasValue/sh:in lines in '
                                      'phase-content.trig plus a unit test '
                                      'that parses the trig file and asserts '
                                      'equality with the hardcoded '
                                      'sentinels.", "acceptance_criteria": "A '
                                      'unit test parses phase-content.trig '
                                      'directly and fails if the hardcoded '
                                      '\\"[]\\"/\\"pass\\" sentinels drift '
                                      'from the live gate shapes; no other '
                                      'spec values are hardcoded.", '
                                      '"priority": "P1"}, {"feature_id": '
                                      '"F7", "name": "Exit code mirrors '
                                      'overall verdict", "description": "The '
                                      'process exit code mirrors '
                                      'verdicts.overall so CI consumers can '
                                      'gate builds on the audit result '
                                      'without parsing output.", '
                                      '"acceptance_criteria": "Exit code 0 '
                                      'iff verdicts.overall is passing; '
                                      'nonzero otherwise; behaviour identical '
                                      'in table and --json modes and covered '
                                      'by a test.", "priority": "P1"}, '
                                      '{"feature_id": "F8", "name": "Explicit '
                                      'limitations reporting", "description": '
                                      '"Report known epistemic limits '
                                      'explicitly in v1: the unresolvable '
                                      'never-ran vs rolled-back ambiguity, '
                                      'transcript-only retry counts '
                                      '(excluded), and never-satisfied memory '
                                      'prd:coversFeature counts '
                                      '(informational only) \\u2014 via the '
                                      'JSON limitations array and table '
                                      'footnotes.", "acceptance_criteria": '
                                      '"The limitations array is present and '
                                      'populated in every JSON report; '
                                      'memory_coverage_links and retry counts '
                                      'never affect verdicts.overall or the '
                                      'exit code.", "priority": "P1"}]',
                     'mandatory_feature_coverage': '[{"mandatory_feature": '
                                                   '"Phase listing: given an '
                                                   'idea id, query the '
                                                   'ontology-server phases '
                                                   'graph over its REST '
                                                   'SPARQL endpoint and list '
                                                   'every completed phase '
                                                   '(d1..i1) with its '
                                                   'phase:producedBy id and '
                                                   'trace:tracesTo '
                                                   'predecessor, in pipeline '
                                                   'order", "covered_by": '
                                                   '"F1"}, '
                                                   '{"mandatory_feature": '
                                                   '"Gate report: for each '
                                                   'completed phase, show the '
                                                   'SHACL gate shape URI '
                                                   'declared via '
                                                   'phase:shaclGate and '
                                                   'whether a phase output '
                                                   'exists for it (persisted '
                                                   '= the gate passed, since '
                                                   'nonconforming outputs are '
                                                   'rolled back)", '
                                                   '"covered_by": "F2"}, '
                                                   '{"mandatory_feature": '
                                                   '"Coverage-chain report: '
                                                   'render the '
                                                   'drift-prevention chain as '
                                                   'a table \\u2014 D5 '
                                                   'mandatory_features '
                                                   '\\u2192 P1 feature_scope '
                                                   '(+ '
                                                   'uncovered_mandatory_features) '
                                                   '\\u2192 P4 '
                                                   'feature_coverage \\u2192 '
                                                   'P6 '
                                                   'coverage_gate/uncovered_features '
                                                   '\\u2014 and print an '
                                                   'overall verdict line: '
                                                   'COVERAGE: PASS only if '
                                                   'every link is closed", '
                                                   '"covered_by": "F3"}, '
                                                   '{"mandatory_feature": '
                                                   '"JSON output mode: a '
                                                   '--json flag that emits '
                                                   'the same report as a '
                                                   'machine-readable JSON '
                                                   'object instead of '
                                                   'tables", "covered_by": '
                                                   '"F4"}]',
                     'uncovered_mandatory_features': '[]'},
              'p4': {'feature_coverage': '[{"feature_id": "F1", "task_ids": '
                                         '["T2.1", "T4.1"]}, {"feature_id": '
                                         '"F2", "task_ids": ["T2.2", "T3.1", '
                                         '"T4.1"]}, {"feature_id": "F3", '
                                         '"task_ids": ["T2.3", "T3.1", '
                                         '"T4.1"]}, {"feature_id": "F4", '
                                         '"task_ids": ["T4.2"]}, '
                                         '{"feature_id": "F5", "task_ids": '
                                         '["T1.2"]}, {"feature_id": "F6", '
                                         '"task_ids": ["T3.2", "T3.3"]}, '
                                         '{"feature_id": "F7", "task_ids": '
                                         '["T4.3"]}, {"feature_id": "F8", '
                                         '"task_ids": ["T2.4", "T4.1", '
                                         '"T4.2"]}]',
                     'uncovered_features': '[]'},
              'p6': {'coverage_gate': 'pass', 'uncovered_features': '[]'}}}

SPEC = IDEA15_FIXTURE["spec"]
LISTING = IDEA15_FIXTURE["listing"]
D5_MODE = IDEA15_FIXTURE["d5_mode"]
COVERAGE = IDEA15_FIXTURE["coverage"]

PERSISTED_PHASES = {
    "d1", "d2", "d3", "d4", "d5",
    "r1", "r2", "r3", "r4", "r5", "r6",
    "p1", "p2", "p3", "p4", "p5", "p6",
}
NOT_PERSISTED_PHASES = {
    "i1", "intake", "context-scan", "plan", "execute", "trace"
}


def _states(rows: list[dict]) -> dict[str, str]:
    return {row["phase_id"]: row["state"] for row in rows}


def _classify(listing=None, d5_mode=D5_MODE) -> list[dict]:
    return gate_audit.classify_phases(
        SPEC, LISTING if listing is None else listing, IDEA, d5_mode
    )


def _discovery_only_listing() -> list[dict]:
    return [r for r in LISTING if r["phase_id"].startswith("d")]


# ---------------------------------------------------------------------------
# Phase classification: EXP4 baseline, 0 misclassifications
# ---------------------------------------------------------------------------


def test_phase_classification_zero_misclassifications():
    """EXP4 baseline on the full recorded fixture: 0 misclassifications."""
    expected = {p: gate_audit.STATE_PERSISTED for p in PERSISTED_PHASES}
    expected |= {
        p: gate_audit.STATE_NOT_PERSISTED for p in NOT_PERSISTED_PHASES
    }
    actual = _states(_classify())
    misclassified = {
        phase: (expected.get(phase), state)
        for phase, state in actual.items()
        if expected.get(phase) != state
    }
    assert misclassified == {}, f"misclassifications: {misclassified}"
    assert len(actual) == 23  # every derived-pipeline phase, none dropped


def test_persisted_rows_carry_result_gate_and_pipeline_index():
    for row in _classify():
        if row["state"] != gate_audit.STATE_PERSISTED:
            continue
        uris = [r["result_uri"] for r in row["results"]]
        assert uris == [f"http://tulla.dev/phase#{IDEA}-{row['phase_id']}"]
        assert row["gate_shape"] is not None  # persisted == gate passed
        assert row["pipeline_index"] is not None


def test_not_persisted_rows_always_carry_ambiguity_note():
    """ADR-130-7: never-ran and rolled-back are graph-identical; every
    not-persisted row must say so, and only those rows carry the note."""
    rows = _classify()
    noted = {
        r["phase_id"] for r in rows if r["note"] == gate_audit.AMBIGUITY_NOTE
    }
    assert noted == NOT_PERSISTED_PHASES
    for row in rows:
        if row["state"] == gate_audit.STATE_NOT_PERSISTED:
            assert row["results"] == []
        else:
            assert row["note"] is None


def test_research_mode_skips_nothing():
    """The recorded d5 mode is 'research': parking/researching skips no
    family, so nothing may classify as skipped (nor with no d5 at all)."""
    assert D5_MODE == "research"
    for mode in (D5_MODE, None):
        assert gate_audit.STATE_SKIPPED not in _states(
            _classify(d5_mode=mode)
        ).values()


@pytest.mark.parametrize(
    ("mode", "skipped_families"),
    [("plan", {"research"}), ("implement", {"research", "planning"})],
)
def test_d5_mode_marks_unpersisted_families_skipped(mode, skipped_families):
    """A persisted D5 routing mode is queryable skip evidence: absent
    phases of routed-around families are skipped, everything else absent
    stays not-persisted (with the ambiguity note)."""
    rows = _classify(listing=_discovery_only_listing(), d5_mode=mode)
    for row in rows:
        if row["phase_id"].startswith("d"):
            assert row["state"] == gate_audit.STATE_PERSISTED
        elif row["family"] in skipped_families:
            assert row["state"] == gate_audit.STATE_SKIPPED
            assert row["note"] is None
        else:
            assert row["state"] == gate_audit.STATE_NOT_PERSISTED
            assert row["note"] == gate_audit.AMBIGUITY_NOTE


# ---------------------------------------------------------------------------
# missing-claimed: dangling trace:tracesTo edge detection (T2.2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "dangling_target",
    [
        f"http://tulla.dev/phase#{IDEA}-r6",  # phase#idea-N-<pid> convention
        "http://tulla.dev/phase#15-r6",  # phase#N-<pid> convention
    ],
)
def test_missing_claimed_dangling_edge_both_uri_conventions(dangling_target):
    """Drop the research nodes but keep p1's tracesTo edge to r6: the
    dangling claim classifies r6 as missing-claimed under BOTH production
    subject-URI conventions -- and beats 'skipped' (evidence precedence
    persisted > missing-claimed > skipped > not-persisted)."""
    listing = [
        copy.deepcopy(r)
        for r in LISTING
        if not r["phase_id"].startswith("r")  # research family not persisted
    ]
    p1 = next(r for r in listing if r["phase_id"] == "p1")
    p1["traces_to"] = [dangling_target]
    states = _states(_classify(listing=listing, d5_mode="plan"))
    assert states["r6"] == gate_audit.STATE_MISSING_CLAIMED
    # the rest of the unpersisted research family stays plainly skipped
    assert states["r5"] == gate_audit.STATE_SKIPPED


def test_foreign_or_other_idea_trace_targets_claim_nothing():
    """Targets outside the phase namespace or belonging to another idea
    never manufacture a missing-claimed row."""
    listing = [copy.deepcopy(r) for r in LISTING if r["phase_id"] != "r6"]
    p1 = next(r for r in listing if r["phase_id"] == "p1")
    p1["traces_to"] = [
        "http://tulla.dev/phase#idea-14-r6",  # another idea's r6
        "http://semantic-tool-use.org/ideas/idea-15",  # foreign namespace
    ]
    states = _states(_classify(listing=listing))
    assert states["r6"] == gate_audit.STATE_NOT_PERSISTED


# ---------------------------------------------------------------------------
# Hop/verdict matrix: 12/12 cases (R5 exp1, formalized per T2.3)
# ---------------------------------------------------------------------------

# Legacy pre-gate chain (idea-13 shape): all four nodes persisted, but the
# coverage predicates were never emitted -- {} is "node exists, fields absent".
LEGACY_COVERAGE = {"d5": {}, "p1": {}, "p4": {}, "p6": {}}

# Post-gate D5 with planning not yet run (idea-15's own pre-planning shape).
PLANNING_NOT_RUN_COVERAGE = {
    "d5": COVERAGE["d5"],
    "p1": None,
    "p4": None,
    "p6": None,
}

# R5 exp1 scenario -> expected per-hop states and overall verdict. exp1's
# DOWNSTREAM-MISSING was frozen as MISSING-NODE in the v1 enum (ADR-003).
EXP1_MATRIX = {
    "post-gate-idea-15": (
        COVERAGE,
        {
            "d5->p1": gate_audit.HOP_CLOSED,
            "p1->p4": gate_audit.HOP_CLOSED,
            "p4->p6": gate_audit.HOP_CLOSED,
            "overall": gate_audit.COVERAGE_PASS,
        },
    ),
    "legacy-predicates-absent": (
        LEGACY_COVERAGE,
        {
            "d5->p1": gate_audit.HOP_NOT_EVALUATED,
            "p1->p4": gate_audit.HOP_NOT_EVALUATED,
            "p4->p6": gate_audit.HOP_NOT_EVALUATED,
            "overall": gate_audit.COVERAGE_NOT_EVALUATED,
        },
    ),
    "planning-not-run": (
        PLANNING_NOT_RUN_COVERAGE,
        {
            "d5->p1": gate_audit.HOP_MISSING_NODE,
            "p1->p4": gate_audit.HOP_MISSING_NODE,
            "p4->p6": gate_audit.HOP_MISSING_NODE,
            "overall": gate_audit.COVERAGE_INCOMPLETE,
        },
    ),
}


@pytest.mark.parametrize("case", ["d5->p1", "p1->p4", "p4->p6", "overall"])
@pytest.mark.parametrize("scenario", sorted(EXP1_MATRIX))
def test_hop_verdict_matrix(scenario, case):
    """The 12 R5-exp1 hop/verdict cases: 3 scenarios x (3 hops + overall)."""
    coverage, expected = EXP1_MATRIX[scenario]
    hops = gate_audit.evaluate_coverage_chain(coverage)
    if case == "overall":
        assert gate_audit.coverage_overall(hops) == expected["overall"]
    else:
        hop = next(h for h in hops if h["hop"] == case)
        assert hop["state"] == expected[case]


def test_legacy_leniency_never_reaches_sentinel_checks():
    """NOT-EVALUATED leniency: a legacy predicate-absent node fails only the
    presence check; the sentinel check is 'not reached' (ok None), the hop is
    never OPEN, and the chain never folds to FAIL."""
    hops = gate_audit.evaluate_coverage_chain(LEGACY_COVERAGE)
    for hop in hops:
        assert hop["state"] == gate_audit.HOP_NOT_EVALUATED
        checks = {c["check"]: c for c in hop["checks"]}
        assert checks["coverage-predicates-present"]["ok"] is False
        assert checks["uncovered-list-empty"]["ok"] is None
    assert gate_audit.coverage_overall(hops) != gate_audit.COVERAGE_FAIL


# ---------------------------------------------------------------------------
# Sentinel conditions: "[]" and "pass" (ADR-002, raw-literal comparison)
# ---------------------------------------------------------------------------


def test_sentinel_constants_match_frozen_gate_values():
    # Value pin only -- T3.3 owns the sync test against phase-content.trig.
    assert gate_audit.UNCOVERED_EMPTY_SENTINEL == "[]"
    assert gate_audit.COVERAGE_GATE_PASS_SENTINEL == "pass"


@pytest.mark.parametrize(
    "uncovered_literal",
    [
        '["Gate report per phase"]',  # a genuinely uncovered feature
        "[ ]",  # JSON-equivalent but not byte-equal: raw comparison (exp3)
    ],
)
def test_nonempty_uncovered_literal_opens_hop(uncovered_literal):
    coverage = copy.deepcopy(COVERAGE)
    coverage["p1"]["uncovered_mandatory_features"] = uncovered_literal
    hops = gate_audit.evaluate_coverage_chain(coverage)
    d5_p1 = next(h for h in hops if h["hop"] == "d5->p1")
    assert d5_p1["state"] == gate_audit.HOP_OPEN
    assert gate_audit.coverage_overall(hops) == gate_audit.COVERAGE_FAIL


def test_p6_coverage_gate_fail_literal_opens_hop():
    """The P6 shape deliberately admits "fail"; only the exact raw literal
    "pass" closes the hop -- anything else is OPEN and folds to FAIL."""
    coverage = copy.deepcopy(COVERAGE)
    coverage["p6"]["coverage_gate"] = "fail"
    hops = gate_audit.evaluate_coverage_chain(coverage)
    p4_p6 = next(h for h in hops if h["hop"] == "p4->p6")
    assert p4_p6["state"] == gate_audit.HOP_OPEN
    checks = {c["check"]: c for c in p4_p6["checks"]}
    assert checks["coverage-gate-pass"]["ok"] is False
    assert checks["uncovered-list-empty"]["ok"] is True  # itemized, not moot
    assert gate_audit.coverage_overall(hops) == gate_audit.COVERAGE_FAIL


def test_unjoined_upstream_feature_opens_hop():
    """The client-side JSON join (per-instance SHACL can't check it): drop
    F1 from p4's coverage map and the p1->p4 hop reports it unjoined."""
    coverage = copy.deepcopy(COVERAGE)
    fc = json.loads(coverage["p4"]["feature_coverage"])
    fc = [entry for entry in fc if entry["feature_id"] != "F1"]
    coverage["p4"]["feature_coverage"] = json.dumps(fc)
    hops = gate_audit.evaluate_coverage_chain(coverage)
    p1_p4 = next(h for h in hops if h["hop"] == "p1->p4")
    assert p1_p4["state"] == gate_audit.HOP_OPEN
    assert p1_p4["unjoined"] == ["F1"]
    assert gate_audit.coverage_overall(hops) == gate_audit.COVERAGE_FAIL


# ---------------------------------------------------------------------------
# Coverage-map serializations: live list-of-dicts AND R5 exp1 dict form
# ---------------------------------------------------------------------------


def test_recorded_fixture_uses_list_of_dicts_serialization():
    """Guard the fixture itself: live post-gate idea-15 emitted coverage
    maps as lists of dicts (the form the R5 scripts did NOT use)."""
    p1_map = json.loads(COVERAGE["p1"]["mandatory_feature_coverage"])
    p4_map = json.loads(COVERAGE["p4"]["feature_coverage"])
    assert isinstance(p1_map, list) and isinstance(p1_map[0], dict)
    assert isinstance(p4_map, list) and isinstance(p4_map[0], dict)


def test_coverage_map_dict_serialization_also_closes():
    """R5 exp1 emitted coverage maps as dicts keyed by feature id;
    evaluate_hop must close the same chain under that serialization too."""
    coverage = copy.deepcopy(COVERAGE)
    p1_map = json.loads(coverage["p1"]["mandatory_feature_coverage"])
    coverage["p1"]["mandatory_feature_coverage"] = json.dumps(
        {entry["mandatory_feature"]: entry["covered_by"] for entry in p1_map}
    )
    p4_map = json.loads(coverage["p4"]["feature_coverage"])
    coverage["p4"]["feature_coverage"] = json.dumps(
        {entry["feature_id"]: entry["task_ids"] for entry in p4_map}
    )
    hops = gate_audit.evaluate_coverage_chain(coverage)
    assert [h["state"] for h in hops] == [gate_audit.HOP_CLOSED] * 3
    assert gate_audit.coverage_overall(hops) == gate_audit.COVERAGE_PASS


# ---------------------------------------------------------------------------
# Overall verdict fold: PASS iff every hop CLOSED (precedence order)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("states", "verdict"),
    [
        (["CLOSED", "CLOSED", "CLOSED"], "PASS"),
        (["CLOSED", "OPEN", "CLOSED"], "FAIL"),
        (["OPEN", "MISSING-NODE", "NOT-EVALUATED"], "FAIL"),  # OPEN wins
        (["CLOSED", "MISSING-NODE", "NOT-EVALUATED"], "INCOMPLETE"),
        (["CLOSED", "CLOSED", "NOT-EVALUATED"], "NOT-EVALUATED"),
    ],
)
def test_coverage_overall_precedence(states, verdict):
    hops = [{"state": s} for s in states]
    assert gate_audit.coverage_overall(hops) == verdict


def test_frozen_v1_enum_values():
    """SchemaVer 1-0-0 rename ban (ADR-003): the literals this suite -- and
    every downstream consumer -- keys on may never change."""
    assert gate_audit.STATE_PERSISTED == "persisted"
    assert gate_audit.STATE_SKIPPED == "skipped"
    assert gate_audit.STATE_MISSING_CLAIMED == "missing-claimed"
    assert gate_audit.STATE_NOT_PERSISTED == "not-persisted"
    assert gate_audit.HOP_CLOSED == "CLOSED"
    assert gate_audit.HOP_OPEN == "OPEN"
    assert gate_audit.HOP_NOT_EVALUATED == "NOT-EVALUATED"
    assert gate_audit.HOP_MISSING_NODE == "MISSING-NODE"


# ---------------------------------------------------------------------------
# --json contract: frozen SchemaVer 1-0-0 shape check (T4.2, ADR-003)
# ---------------------------------------------------------------------------
# Pins schema_version, key structure, enum values, itemized checks, the
# always-populated limitations array, and the memory_coverage_links
# exclusion from verdicts. Evolution within MODEL 1 is additive-only: a new
# key extends the pinned sets below (1-N-0); renaming/removing any pinned
# key or enum literal is a breaking change (MODEL 2-0-0), not allowed here.

MEMORY_LINKS = 32  # live idea-15 count at fixture-capture time


def _report(memory_links: int = MEMORY_LINKS) -> dict:
    return gate_audit.build_report(
        IDEA,
        SPEC,
        _classify(),
        gate_audit.evaluate_coverage_chain(COVERAGE),
        memory_links,
    )


def _json_payload(memory_links: int = MEMORY_LINKS) -> dict:
    return json.loads(gate_audit.render_json(_report(memory_links)))


def test_json_parses_and_pins_schema_version():
    payload = _json_payload()
    assert payload["schema_version"] == "1-0-0"
    assert gate_audit.SCHEMA_VERSION == "1-0-0"


def test_json_frozen_top_level_key_structure():
    payload = _json_payload()
    assert set(payload) == {
        "schema_version",
        "idea",
        "spec",
        "phases",
        "verdicts",
        "memory_coverage_links",
        "limitations",
    }
    assert set(payload["verdicts"]) == {"hops", "overall"}
    assert payload["idea"] == IDEA


def test_json_phase_rows_frozen_shape_and_enum_values():
    payload = _json_payload()
    phase_states = {
        gate_audit.STATE_PERSISTED,
        gate_audit.STATE_SKIPPED,
        gate_audit.STATE_MISSING_CLAIMED,
        gate_audit.STATE_NOT_PERSISTED,
    }
    assert len(payload["phases"]) == 23
    for row in payload["phases"]:
        assert set(row) == {
            "phase_id",
            "family",
            "pipeline_index",
            "state",
            "gate_shape",
            "results",
            "note",
        }
        assert row["state"] in phase_states


def test_json_hops_frozen_shape_itemized_checks_and_enum_values():
    payload = _json_payload()
    hop_states = {
        gate_audit.HOP_CLOSED,
        gate_audit.HOP_OPEN,
        gate_audit.HOP_NOT_EVALUATED,
        gate_audit.HOP_MISSING_NODE,
    }
    hops = payload["verdicts"]["hops"]
    assert [h["hop"] for h in hops] == ["d5->p1", "p1->p4", "p4->p6"]
    for hop in hops:
        assert set(hop) == {
            "hop",
            "upstream",
            "downstream",
            "state",
            "checks",
            "unjoined",
        }
        assert hop["state"] in hop_states
        assert hop["checks"]  # per-hop itemized checks, never empty
        for check in hop["checks"]:
            assert set(check) == {"check", "ok", "detail"}
    assert payload["verdicts"]["overall"] == gate_audit.COVERAGE_PASS


def test_json_limitations_always_populated():
    payload = _json_payload()
    assert [lim["id"] for lim in payload["limitations"]] == [
        "not-persisted-ambiguity",
        "retry-counts-transcript-only",
        "memory-links-informational",
    ]
    for lim in payload["limitations"]:
        assert set(lim) == {"id", "text"}
        assert lim["text"]


@pytest.mark.parametrize("links", [0, MEMORY_LINKS, 10_000])
def test_json_memory_links_outside_verdicts_never_verdict_affecting(links):
    payload = _json_payload(links)
    assert payload["memory_coverage_links"] == links
    assert "memory_coverage_links" not in payload["verdicts"]
    assert payload["verdicts"]["overall"] == gate_audit.COVERAGE_PASS


def test_table_and_json_verdicts_identical():
    """Reliability P0 (ADR-003): both surfaces render the SAME report
    object, so the overall verdict line and every hop state must agree."""
    report = _report()
    payload = json.loads(gate_audit.render_json(report))
    table = gate_audit.render_table(report)
    assert f"COVERAGE: {payload['verdicts']['overall']}" in table.splitlines()
    assert [
        (h["hop"], h["state"]) for h in payload["verdicts"]["hops"]
    ] == [(h["hop"], h["state"]) for h in report["verdicts"]["hops"]]


def test_render_json_does_not_mutate_the_report():
    """render_json must stay a pure function of build_report()'s object."""
    report = _report()
    before = copy.deepcopy(report)
    gate_audit.render_json(report)
    assert report == before


# ---------------------------------------------------------------------------
# Exit code mirrors verdicts.overall (T4.3, ADR-003)
# ---------------------------------------------------------------------------
# main() is exercised end-to-end with the fetch layer monkeypatched to the
# recorded fixture (the T2.4 pattern) -- no I/O, no live server, and never a
# write anywhere. Both output modes run each case: exit code 0 iff the
# overall verdict is PASS (only PASS is passing per the T3.1-validated
# semantics), 1 otherwise, and the zero-gate abort keeps exit 2.

MODE_ARGS = pytest.mark.parametrize(
    "mode_args", [[], ["--json"]], ids=["table", "json"]
)


def _patch_fetches(monkeypatch, coverage) -> None:
    """Point main()'s entire fetch layer at the recorded fixture bindings."""
    monkeypatch.setattr(gate_audit, "derive_spec", lambda base_url: SPEC)
    monkeypatch.setattr(
        gate_audit, "fetch_phase_listing", lambda *args: LISTING
    )
    monkeypatch.setattr(gate_audit, "fetch_d5_mode", lambda *args: D5_MODE)
    monkeypatch.setattr(
        gate_audit, "fetch_coverage_fields", lambda *args: coverage
    )
    monkeypatch.setattr(
        gate_audit, "fetch_memory_coverage_links", lambda *args: MEMORY_LINKS
    )


def _open_hop_coverage() -> dict:
    """The recorded fixture with the p4->p6 hop opened (coverage_gate fail)."""
    coverage = copy.deepcopy(COVERAGE)
    coverage["p6"]["coverage_gate"] = "fail"
    return coverage


@pytest.mark.parametrize(
    ("overall", "expected"),
    [
        (gate_audit.COVERAGE_PASS, 0),
        (gate_audit.COVERAGE_FAIL, 1),
        (gate_audit.COVERAGE_INCOMPLETE, 1),
        (gate_audit.COVERAGE_NOT_EVALUATED, 1),
    ],
)
def test_exit_code_pure_mapping_only_pass_is_passing(overall, expected):
    """exit_code is a pure function of verdicts.overall: 0 iff PASS."""
    assert gate_audit.exit_code({"verdicts": {"overall": overall}}) == expected


@MODE_ARGS
def test_exit_code_zero_on_passing_fixture_both_modes(
    monkeypatch, capsys, mode_args
):
    _patch_fetches(monkeypatch, COVERAGE)
    assert gate_audit.main([IDEA, *mode_args]) == 0
    out = capsys.readouterr().out
    if mode_args:
        assert json.loads(out)["verdicts"]["overall"] == "PASS"
    else:
        assert "COVERAGE: PASS" in out.splitlines()


@MODE_ARGS
def test_exit_code_nonzero_on_open_hop_both_modes(
    monkeypatch, capsys, mode_args
):
    """An OPEN hop folds to FAIL: nonzero (and distinct from abort's 2)."""
    _patch_fetches(monkeypatch, _open_hop_coverage())
    code = gate_audit.main([IDEA, *mode_args])
    assert code == 1
    out = capsys.readouterr().out
    if mode_args:
        assert json.loads(out)["verdicts"]["overall"] == "FAIL"
    else:
        assert "COVERAGE: FAIL" in out.splitlines()


@MODE_ARGS
def test_exit_code_agrees_with_rendered_verdict_both_modes(
    monkeypatch, capsys, mode_args
):
    """Reliability P0: the printed verdict and the exit code derive from
    the same report object, so they can never disagree -- in either mode,
    passing and failing alike."""
    for coverage, expected_code, verdict in (
        (COVERAGE, 0, "PASS"),
        (_open_hop_coverage(), 1, "FAIL"),
    ):
        _patch_fetches(monkeypatch, coverage)
        assert gate_audit.main([IDEA, *mode_args]) == expected_code
        out = capsys.readouterr().out
        rendered = (
            json.loads(out)["verdicts"]["overall"]
            if mode_args
            else next(
                line.removeprefix("COVERAGE: ")
                for line in out.splitlines()
                if line.startswith("COVERAGE: ")
            )
        )
        assert rendered == verdict


@MODE_ARGS
def test_zero_gate_abort_stays_exit_2_both_modes(
    monkeypatch, capsys, mode_args
):
    """The 'spec not loaded' hard abort (ADR-002) keeps its nonzero exit 2
    in both output modes -- T4.3 must not break the existing error path."""

    def _abort(base_url):
        raise gate_audit.SpecNotLoadedError("spec not loaded")

    monkeypatch.setattr(gate_audit, "derive_spec", _abort)
    assert gate_audit.main([IDEA, *mode_args]) == 2
    captured = capsys.readouterr()
    assert "spec not loaded" in captured.err
    assert captured.out == ""
