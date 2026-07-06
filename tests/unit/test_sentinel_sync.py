"""SENTINEL-SYNC drift test (T3.3, ADR-002).

The "[]"/"pass" sentinels in tools/gate_audit.py (UNCOVERED_EMPTY_SENTINEL,
COVERAGE_GATE_PASS_SENTINEL) are the only hardcoded spec values, provably
not runtime-derivable (R5 EXP3). This test is the enforcement half of the
SENTINEL-SYNC convention: it parses the canonical
tulla/ontologies/phase-content.trig directly (never the stale
data/phase-content-draft.trig copy, no live server), extracts

- the ``sh:hasValue`` sentinel from the P1OutputShape property on
  phase:preserves-uncovered_mandatory_features,
- the ``sh:hasValue`` sentinel from the P4OutputShape property on
  phase:preserves-uncovered_features, and
- the ``sh:in`` members from the P6OutputShape property on
  phase:preserves-coverage_gate,

and asserts equality with the CLI constants. The trig side carries
matching SENTINEL-SYNC marker comments (T3.2) pointing back here.
The P3 shape's ``sh:hasValue "[]"`` is deliberately out of scope: the
gate-audit CLI never compares against a P3 sentinel.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from rdflib import Dataset, Literal, Namespace, URIRef
from rdflib.namespace import RDF, SH

# Same TRIG_PATH resolution as tests/unit/test_phase_gate_shapes.py:
# the canonical trig, NOT data/phase-content-draft.trig.
TRIG_PATH = (
    Path(__file__).resolve().parents[2] / "tulla" / "ontologies" / "phase-content.trig"
)

PHASE = Namespace("http://tulla.dev/phase#")

# tools/gate_audit.py is a single file with no package __init__ (ADR-001):
# import it by path (pattern from tests/unit/test_gate_audit_verdicts.py).
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


@pytest.fixture(scope="module")
def trig() -> Dataset:
    ds = Dataset(default_union=True)
    ds.parse(TRIG_PATH, format="trig")
    assert len(list(ds.quads((None, None, None, None)))) > 0, (
        "phase-content.trig parsed to zero quads"
    )
    return ds


def _has_value_sentinel(ds: Dataset, shape: URIRef, path: URIRef) -> Literal:
    """The sh:hasValue on the given shape's property constraint for path."""
    values = [
        ds.value(prop, SH.hasValue)
        for prop in ds.objects(shape, SH.property)
        if ds.value(prop, SH.path) == path
    ]
    values = [v for v in values if v is not None]
    assert len(values) == 1, (
        f"expected exactly one sh:hasValue for {path} on {shape}, got {values}"
    )
    return values[0]


def _sh_in_members(ds: Dataset, shape: URIRef, path: URIRef) -> list[str]:
    """The sh:in RDF-list members on the given shape's property constraint."""
    lists = [
        ds.value(prop, SH["in"])
        for prop in ds.objects(shape, SH.property)
        if ds.value(prop, SH.path) == path
    ]
    lists = [l for l in lists if l is not None]
    assert len(lists) == 1, (
        f"expected exactly one sh:in for {path} on {shape}, got {lists}"
    )
    members = []
    node = lists[0]
    while node != RDF.nil:
        members.append(str(ds.value(node, RDF.first)))
        node = ds.value(node, RDF.rest)
    return members


def test_p1_uncovered_sentinel_matches_cli(trig: Dataset) -> None:
    sentinel = _has_value_sentinel(
        trig, PHASE.P1OutputShape, PHASE["preserves-uncovered_mandatory_features"]
    )
    assert str(sentinel) == gate_audit.UNCOVERED_EMPTY_SENTINEL, (
        "P1OutputShape sh:hasValue drifted from "
        "gate_audit.UNCOVERED_EMPTY_SENTINEL — change both together "
        "(see SENTINEL-SYNC comments in phase-content.trig)"
    )


def test_p4_uncovered_sentinel_matches_cli(trig: Dataset) -> None:
    sentinel = _has_value_sentinel(
        trig, PHASE.P4OutputShape, PHASE["preserves-uncovered_features"]
    )
    assert str(sentinel) == gate_audit.UNCOVERED_EMPTY_SENTINEL, (
        "P4OutputShape sh:hasValue drifted from "
        "gate_audit.UNCOVERED_EMPTY_SENTINEL — change both together "
        "(see SENTINEL-SYNC comments in phase-content.trig)"
    )


def test_p6_coverage_gate_pass_member_matches_cli(trig: Dataset) -> None:
    members = _sh_in_members(
        trig, PHASE.P6OutputShape, PHASE["preserves-coverage_gate"]
    )
    assert gate_audit.COVERAGE_GATE_PASS_SENTINEL in members, (
        f"P6OutputShape sh:in members {members} no longer contain "
        "gate_audit.COVERAGE_GATE_PASS_SENTINEL — change both together "
        "(see SENTINEL-SYNC comments in phase-content.trig)"
    )
