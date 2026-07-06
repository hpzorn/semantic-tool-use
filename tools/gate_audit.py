#!/usr/bin/env python3
"""Read-only gate audit CLI for the Tulla phase pipeline.

For a given idea, reports all persisted phases in pipeline order with their
SHACL gate status and trace edges, plus the D5->P1->P4->P6 feature-coverage
chain with an unambiguous COVERAGE: PASS/FAIL verdict, as a human-readable
table or stable machine-readable JSON (--json).

Single-file, stdlib-only, strictly read-only (SPARQL SELECTs only).
All graph access goes through the single _sparql() helper below (ADR-001).
Deliberately imports nothing from src/ (query shapes are mirrored, not
imported) so the audit stays independent of server-internal modules.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

# The ONLY hardcoded vocabulary (ADR-001/ADR-002): namespaces and the phases
# graph URI. Everything else (pipeline order, gate URIs, coverage field
# names) is derived from the live graph at runtime.
PHASE_NS = "http://tulla.dev/phase#"
TRACE_NS = "http://tulla.dev/trace#"
PRD_NS = "http://tulla.dev/prd#"
PHASES_GRAPH = "http://semantic-tool-use.org/graphs/phases"

DEFAULT_SERVER = "http://localhost:8100"

# Hop-join semantics of the feature-coverage chain (ADR-002): the chain
# D5 -> P1 -> P4 -> P6 is a fixed contract, not graph data, so the hop
# phase ids may be hardcoded. Which fields each hop emits is still derived.
COVERAGE_CHAIN = ("d5", "p1", "p4", "p6")

# Frozen SchemaVer 1-0-0 phase-state enum (ADR-003): these literals may
# never be renamed, only additively extended (breaking rename = MODEL 2-0-0).
STATE_PERSISTED = "persisted"
STATE_SKIPPED = "skipped"
STATE_MISSING_CLAIMED = "missing-claimed"
STATE_NOT_PERSISTED = "not-persisted"

# Frozen SchemaVer 1-0-0 hop-state enum (ADR-003), same rename ban. Legacy
# leniency is load-bearing: a persisted node that predates the coverage
# gates (predicates absent) is NOT-EVALUATED, never an open/failed hop.
HOP_CLOSED = "CLOSED"
HOP_OPEN = "OPEN"
HOP_NOT_EVALUATED = "NOT-EVALUATED"
HOP_MISSING_NODE = "MISSING-NODE"

# Overall coverage verdict values (R5 exp1 / R6 RQ2): PASS iff every hop is
# CLOSED; any OPEN hop is FAIL; otherwise a missing node beats legacy
# leniency (INCOMPLETE over NOT-EVALUATED).
COVERAGE_PASS = "PASS"
COVERAGE_FAIL = "FAIL"
COVERAGE_INCOMPLETE = "INCOMPLETE"
COVERAGE_NOT_EVALUATED = "NOT-EVALUATED"

# The ONLY hardcoded gate sentinel values (ADR-002): provably not derivable
# at runtime (R5 EXP3 -- SHACL shapes load into a non-queryable validation
# layer). They mirror, and must stay equal to, the sh:hasValue "[]" lines
# of the P1/P4 gate shapes and the sh:in ("pass" "fail") member of the P6
# shape in tulla/ontologies/phase-content.trig; T3.2/T3.3 add marker
# comments there and a sync test parsing the trig against these constants.
# Compared against the RAW literal (the gates compare the raw literal too).
UNCOVERED_EMPTY_SENTINEL = "[]"
COVERAGE_GATE_PASS_SENTINEL = "pass"

# Per-hop join semantics of the coverage chain (R6 RQ2, fixed contract like
# COVERAGE_CHAIN -- which field plays which role is a design fact, not a
# spec datum; the graph only declares field *presence* via emitsIntentField).
# Field roles per hop:
#   join_source_field/key: upstream list naming what must be covered
#     (key None = entries are plain strings, else the dict key holding the id)
#   join_map_field/key:    downstream coverage map the join lands in
#   uncovered_field:       downstream list literal that must equal "[]"
#   gate_field:            downstream literal that must equal "pass" (P6 only;
#     the P6 shape deliberately admits "fail" so the pipeline can record it)
# A hop's coverage predicates = its non-None join_map/uncovered/gate fields;
# any of them absent on a persisted downstream node => NOT-EVALUATED.
COVERAGE_HOP_JOINS = (
    {
        "hop": "d5->p1",
        "upstream": "d5",
        "downstream": "p1",
        "join_source_field": "mandatory_features",
        "join_source_key": None,
        "join_map_field": "mandatory_feature_coverage",
        "join_map_key": "mandatory_feature",
        "uncovered_field": "uncovered_mandatory_features",
        "gate_field": None,
    },
    {
        "hop": "p1->p4",
        "upstream": "p1",
        "downstream": "p4",
        "join_source_field": "feature_scope",
        "join_source_key": "feature_id",
        "join_map_field": "feature_coverage",
        "join_map_key": "feature_id",
        "uncovered_field": "uncovered_features",
        "gate_field": None,
    },
    {
        "hop": "p4->p6",
        "upstream": "p4",
        "downstream": "p6",
        "join_source_field": None,
        "join_source_key": None,
        "join_map_field": None,
        "join_map_key": None,
        "uncovered_field": "uncovered_features",
        "gate_field": "coverage_gate",
    },
)

# ADR-130-7 rollback semantics: a failed SHACL gate rolls back to zero
# triples and writes no tombstone, so an absent phase is provably
# graph-identical to one that never ran. Every not-persisted row MUST carry
# this note (ADR-003) -- the tool never overclaims what the graph can show.
AMBIGUITY_NOTE = (
    "never ran OR was rolled back by a failed SHACL gate; the two are "
    "graph-identical read-only (rollback leaves zero triples, no tombstone)"
)

# Pipeline-routing semantics of D5's preserves-mode literal (fixed contract
# like COVERAGE_CHAIN's hop-join semantics, not graph data): the persisted
# D5 mode is the queryable evidence that a whole agent family was routed
# around -- 'plan' skips research, 'implement' skips research and planning
# (mirrors next_phase_tool routing). 'research' and 'park' skip nothing:
# parking halts the pipeline, which leaves downstream phases ambiguous
# (not-persisted), not provably skipped.
D5_MODE_SKIPPED_FAMILIES = {
    "plan": ("research",),
    "implement": ("research", "planning"),
}

_PORT_CAVEAT = (
    "Note on ports: this tool defaults to http://localhost:8100 (the port "
    "Tulla deployments conventionally expose the ontology server on), but "
    "the ontology server's own built-in default port is 8420 "
    "(src/ontology_server/config.py). If nothing answers on 8100, retry "
    "with --server http://localhost:8420 or set ONTOLOGY_API_URL."
)


class SpecNotLoadedError(RuntimeError):
    """Raised when runtime spec derivation finds no gate declarations.

    Zero gates means the phases graph is empty or we are pointed at the
    wrong graph/server; the ONLY correct response is a hard abort (ADR-002).
    Falling back to a hardcoded phase/gate list would let the audit report
    verdicts against a stale spec.
    """


class SparqlError(RuntimeError):
    """Raised when /kg/sparql reports an error (HTTP-200 {'error': ...} body).

    The endpoint returns HTTP 200 even for failed queries, with the failure
    tucked into an 'error' key; treating that as data would silently corrupt
    verdicts, so we always raise (fail loudly, quality goal Reliability P0).
    """


def _sparql(base_url: str, query: str) -> dict:
    """POST a SPARQL SELECT to {base}/kg/sparql and return the decoded body.

    The query travels as a URL-encoded ``query`` parameter (the endpoint
    takes it as a query-string param, not a request body). Sends
    ``Authorization: Bearer $ONTOLOGY_API_KEY`` when the env var is set.
    Raises SparqlError when the HTTP-200 JSON body contains an 'error' key;
    HTTP-level failures propagate as urllib.error.HTTPError/URLError.

    Returns the full response dict: {variables, bindings, results, count}.
    """
    url = "{}/kg/sparql?{}".format(
        base_url.rstrip("/"), urllib.parse.urlencode({"query": query})
    )
    headers = {"Accept": "application/json"}
    api_key = os.environ.get("ONTOLOGY_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=b"", headers=headers, method="POST")
    with urllib.request.urlopen(request) as response:
        body = json.loads(response.read().decode("utf-8"))
    if isinstance(body, dict) and "error" in body:
        raise SparqlError(f"/kg/sparql returned an error: {body['error']}")
    return body


def derive_spec(base_url: str) -> dict:
    """Derive the pipeline spec from the live phases graph in 3 SELECTs.

    Nothing about the pipeline besides namespaces, the graph URI, and the
    coverage hop ids is hardcoded (ADR-002); adding a phase or gate shape to
    the graph is picked up here with zero CLI code changes (quality goal
    Modifiability P1, <=4 sub-second SELECTs).

    Returns::

        {
          "pipeline":        [{"phase_id", "family", "depth"}, ...],
          "gates_by_phase":  {phase_id: [gate_uri, ...]},
          "gate_uris":       sorted list of distinct gate shape URIs,
          "coverage_fields": {hop_id: [field_name, ...]} for COVERAGE_CHAIN,
        }

    Raises SpecNotLoadedError when gate derivation returns zero gates
    (empty/wrong graph) -- never falls back to a stale hardcoded list.
    """
    # (a) Pipeline order: transitive upstreamPhase+ depth per family,
    # mirroring list_pipeline's query shape (src/ontology_server/mcp/
    # phase_tools.py) but covering every family in one SELECT. Within a
    # family, (depth, phaseId) ordering is exactly list_pipeline's.
    order_query = (
        f"SELECT ?phaseId ?family (COUNT(?ancestor) AS ?depth) WHERE {{\n"
        f"  GRAPH <{PHASES_GRAPH}> {{\n"
        f"    ?phase <{PHASE_NS}agentFamily> ?family ;\n"
        f"           <{PHASE_NS}phaseId> ?phaseId .\n"
        f"    OPTIONAL {{\n"
        f"      ?phase <{PHASE_NS}upstreamPhase>+ ?ancestor .\n"
        f"      ?ancestor <{PHASE_NS}agentFamily> ?family .\n"
        f"    }}\n"
        f"  }}\n"
        f"}}\n"
        f"GROUP BY ?phaseId ?family\n"
        f"ORDER BY ?family ?depth ?phaseId"
    )
    pipeline = [
        {
            "phase_id": str(row.get("phaseId", "")),
            "family": str(row.get("family", "")),
            "depth": int(row.get("depth", 0)),
        }
        for row in _sparql(base_url, order_query).get("results", [])
        if row.get("phaseId")
    ]

    # (b) Declared gate shape URIs: SELECT DISTINCT on phase:shaclGate over
    # the whole graph -- deliberately NOT collapsed through the pipeline
    # query, so gates on phases outside any audited family still count.
    gates_query = (
        f"SELECT DISTINCT ?phaseId ?gate WHERE {{\n"
        f"  GRAPH <{PHASES_GRAPH}> {{\n"
        f"    ?phase <{PHASE_NS}shaclGate> ?gate ;\n"
        f"           <{PHASE_NS}phaseId> ?phaseId .\n"
        f"  }}\n"
        f"}}"
    )
    gates_by_phase: dict[str, list[str]] = {}
    gate_uris: set[str] = set()
    for row in _sparql(base_url, gates_query).get("results", []):
        phase_id, gate = str(row.get("phaseId", "")), str(row.get("gate", ""))
        if phase_id and gate:
            gates_by_phase.setdefault(phase_id, []).append(gate)
            gate_uris.add(gate)

    if not gate_uris:
        # Hard abort (ADR-002): an empty gate set can only mean the spec
        # graph is missing/wrong. Never proceed, never fall back.
        raise SpecNotLoadedError("spec not loaded")

    # (c) Coverage field names emitted by the D5->P1->P4->P6 hops.
    values = " ".join(f'"{hop}"' for hop in COVERAGE_CHAIN)
    fields_query = (
        f"SELECT ?phaseId ?field WHERE {{\n"
        f"  GRAPH <{PHASES_GRAPH}> {{\n"
        f"    VALUES ?phaseId {{ {values} }}\n"
        f"    ?phase <{PHASE_NS}phaseId> ?phaseId ;\n"
        f"           <{PHASE_NS}emitsIntentField> ?field .\n"
        f"  }}\n"
        f"}}\n"
        f"ORDER BY ?phaseId ?field"
    )
    coverage_fields: dict[str, list[str]] = {hop: [] for hop in COVERAGE_CHAIN}
    for row in _sparql(base_url, fields_query).get("results", []):
        phase_id, field = str(row.get("phaseId", "")), str(row.get("field", ""))
        if phase_id in coverage_fields and field:
            coverage_fields[phase_id].append(field)

    return {
        "pipeline": pipeline,
        "gates_by_phase": {p: sorted(g) for p, g in gates_by_phase.items()},
        "gate_uris": sorted(gate_uris),
        "coverage_fields": coverage_fields,
    }


def _escape_literal(value: str) -> str:
    """Escape *value* for embedding inside a SPARQL ``"..."`` literal.

    Mirror of phase_tools._sparql_escape_literal (not imported, ADR-001):
    guards against quote/backslash/newline injection through idea ids.
    """
    value = value.replace("\\", "\\\\")
    value = value.replace('"', '\\"')
    value = value.replace("\n", "\\n")
    value = value.replace("\r", "\\r")
    return value


def _normalize_idea_id(idea: str) -> str:
    """Match the server's normalization: bare ids get an ``idea-`` prefix."""
    return idea if idea.startswith("idea-") else f"idea-{idea}"


def fetch_phase_listing(base_url: str, idea_id: str, spec: dict) -> list[dict]:
    """List every persisted phase result for *idea_id*, in pipeline order.

    One compact SELECT (URL-length ceiling, ADR-001) mirroring the
    ``?s phase:forRequirement "<idea>"`` shape of phase_tools._build_query,
    narrowed to the two predicates this listing needs.

    Rows are ordered strictly by the runtime-derived pipeline order in
    ``spec["pipeline"]`` (ADR-002) -- never a hardcoded sequence. Persisted
    phases whose producedBy id is absent from the derived pipeline sort
    after all known phases (by phase id) with ``pipeline_index: None``,
    so unexpected graph contents surface instead of vanishing.

    Returns a list of dicts (data, not prints -- ADR-003)::

        {
          "phase_id":       phase:producedBy literal (e.g. "d1"),
          "result_uri":     the PhaseOutput subject URI,
          "traces_to":      sorted trace:tracesTo predecessor URIs ([] if root),
          "pipeline_index": position in spec["pipeline"], or None if unknown,
        }
    """
    idea_id = _normalize_idea_id(idea_id)
    query = (
        f"SELECT ?result ?phaseId ?pred WHERE {{\n"
        f"  GRAPH <{PHASES_GRAPH}> {{\n"
        f'    ?result <{PHASE_NS}forRequirement> "{_escape_literal(idea_id)}" ;\n'
        f"            <{PHASE_NS}producedBy> ?phaseId .\n"
        f"    OPTIONAL {{ ?result <{TRACE_NS}tracesTo> ?pred . }}\n"
        f"  }}\n"
        f"}}"
    )

    # Group the (result, phaseId, pred) bindings by subject: OPTIONAL yields
    # one row per predecessor edge, and a keyed dict keeps a (defensively
    # possible) duplicate producedBy from fanning out into extra rows.
    grouped: dict[tuple[str, str], set[str]] = {}
    for row in _sparql(base_url, query).get("results", []):
        result_uri = str(row.get("result", ""))
        phase_id = str(row.get("phaseId", ""))
        if not result_uri or not phase_id:
            continue
        preds = grouped.setdefault((result_uri, phase_id), set())
        pred = row.get("pred")
        if pred:
            preds.add(str(pred))

    order = {p["phase_id"]: i for i, p in enumerate(spec["pipeline"])}
    unknown = len(order)  # unknown phases sort after every known one
    rows = [
        {
            "phase_id": phase_id,
            "result_uri": result_uri,
            "traces_to": sorted(preds),
            "pipeline_index": order.get(phase_id),
        }
        for (result_uri, phase_id), preds in grouped.items()
    ]
    rows.sort(
        key=lambda r: (
            r["pipeline_index"] if r["pipeline_index"] is not None else unknown,
            r["phase_id"],
            r["result_uri"],
        )
    )
    return rows


def fetch_d5_mode(base_url: str, idea_id: str) -> str | None:
    """Fetch the persisted D5 preserves-mode literal for *idea_id*, if any.

    The D5 mode is the only queryable skip evidence (R3 RQ1): it records
    which family the pipeline was routed to, so its value proves whole
    families were deliberately skipped rather than never reached. Returns
    None when no D5 output is persisted (nothing can then be classified as
    skipped -- absence stays ambiguous).
    """
    idea_id = _normalize_idea_id(idea_id)
    d5 = COVERAGE_CHAIN[0]
    query = (
        f"SELECT ?mode WHERE {{\n"
        f"  GRAPH <{PHASES_GRAPH}> {{\n"
        f'    ?result <{PHASE_NS}forRequirement> "{_escape_literal(idea_id)}" ;\n'
        f'            <{PHASE_NS}producedBy> "{d5}" ;\n'
        f"            <{PHASE_NS}preserves-mode> ?mode .\n"
        f"  }}\n"
        f"}}"
    )
    for row in _sparql(base_url, query).get("results", []):
        mode = str(row.get("mode", ""))
        if mode:
            return mode
    return None


def fetch_coverage_fields(
    base_url: str, idea_id: str, spec: dict
) -> dict[str, dict[str, str] | None]:
    """Fetch the coverage-chain field literals for *idea_id*'s hop nodes.

    One compact SELECT (URL-length ceiling, ADR-001) over the four
    COVERAGE_CHAIN nodes, taking every ``phase:preserves-*`` literal via an
    OPTIONAL + STRSTARTS filter, then narrowed client-side to the
    runtime-derived field names in ``spec["coverage_fields"]`` (ADR-002:
    the graph's phase:emitsIntentField declarations decide which fields the
    audit may read -- never a hardcoded fetch list).

    Returns ``{hop_id: {field_name: raw_literal} | None}`` for every hop in
    COVERAGE_CHAIN: None means the hop node is not persisted at all, while
    an empty/partial dict means the node exists but lacks (some) coverage
    predicates -- the distinction NOT-EVALUATED hinges on. Literals are kept
    RAW (not JSON-parsed): the gates compare raw literals, so hop evaluation
    does too for the sentinel checks.
    """
    idea_id = _normalize_idea_id(idea_id)
    values = " ".join(f'"{hop}"' for hop in COVERAGE_CHAIN)
    prefix = f"{PHASE_NS}preserves-"
    query = (
        f"SELECT ?phaseId ?p ?o WHERE {{\n"
        f"  GRAPH <{PHASES_GRAPH}> {{\n"
        f"    VALUES ?phaseId {{ {values} }}\n"
        f'    ?node <{PHASE_NS}forRequirement> "{_escape_literal(idea_id)}" ;\n'
        f"          <{PHASE_NS}producedBy> ?phaseId .\n"
        f"    OPTIONAL {{\n"
        f"      ?node ?p ?o .\n"
        f'      FILTER(STRSTARTS(STR(?p), "{prefix}"))\n'
        f"    }}\n"
        f"  }}\n"
        f"}}"
    )
    coverage: dict[str, dict[str, str] | None] = {
        hop: None for hop in COVERAGE_CHAIN
    }
    derived = spec["coverage_fields"]
    for row in _sparql(base_url, query).get("results", []):
        hop = str(row.get("phaseId", ""))
        if hop not in coverage:
            continue
        if coverage[hop] is None:  # node exists (row present, even unbound ?p)
            coverage[hop] = {}
        pred = row.get("p")
        if not pred or not str(pred).startswith(prefix):
            continue
        field = str(pred)[len(prefix):]
        if field in derived.get(hop, []):
            coverage[hop][field] = str(row.get("o", ""))
    return coverage


def _json_or(raw: str | None, default):
    """json.loads *raw*, falling back to *default* on absent/invalid input."""
    try:
        return json.loads(raw)  # type: ignore[arg-type]
    except (json.JSONDecodeError, TypeError):
        return default


def _covered_keys(coverage_map, entry_key: str) -> set:
    """Extract the set of covered identifiers from a parsed coverage map.

    Accepts both serializations observed on live post-gate data (the exact
    _literalise output was R6 RQ2's open item; the gates only enforce
    minCount, so agents legitimately emit either):

    - dict  ``{feature: ...}``            -> its keys (R5 exp1 fixture form)
    - list  ``[{entry_key: feature, ...}]`` -> each entry's *entry_key* value
      (live idea-15 form); bare-string entries count as covered ids too.

    Anything else yields the empty set (nothing is covered).
    """
    if isinstance(coverage_map, dict):
        return set(coverage_map.keys())
    if isinstance(coverage_map, list):
        keys = {e.get(entry_key) for e in coverage_map if isinstance(e, dict)}
        keys.discard(None)
        keys.update(e for e in coverage_map if isinstance(e, str))
        return keys
    return set()


def evaluate_hop(
    hop_spec: dict,
    upstream_fields: dict[str, str] | None,
    downstream_fields: dict[str, str] | None,
) -> dict:
    """Evaluate one coverage-chain hop into the frozen v1 hop-state enum.

    Pure function over already-fetched literals -- no I/O (ADR-003: T3.1
    drives this without a live server). *hop_spec* is a COVERAGE_HOP_JOINS
    entry; *upstream_fields*/*downstream_fields* are fetch_coverage_fields()
    values (None = node not persisted).

    R6 RQ2 closed-link conditions, in evaluation order:

    - MISSING-NODE:  downstream node not persisted.
    - NOT-EVALUATED: node persisted but any required coverage predicate
      absent (pre-gate legacy run) -- leniency, NEVER a failure.
    - OPEN: uncovered-list raw literal != "[]"; or (P6) coverage_gate raw
      literal != "pass" (explicit value check -- the shape admits "fail");
      or the client-side JSON join finds an upstream feature that is no key
      of the downstream coverage map (per-instance SHACL structurally
      cannot enforce this cross-node condition).
    - CLOSED: everything above holds; an absent upstream node/field joins
      vacuously (empty requirement set) -- the downstream node carries the
      hop's evidence.

    Returns (stable shape for T3.1/T4.1)::

        {
          "hop", "upstream", "downstream",   # from hop_spec
          "state":    frozen v1 hop state,
          "checks":   [{"check", "ok", "detail"}, ...] itemized R6-RQ2
                      checks; ok is None when never reached/not applicable,
          "unjoined": sorted upstream features absent from the coverage map,
        }
    """
    checks: list[dict] = []
    unjoined: list = []

    def _done(state: str) -> dict:
        return {
            "hop": hop_spec["hop"],
            "upstream": hop_spec["upstream"],
            "downstream": hop_spec["downstream"],
            "state": state,
            "checks": checks,
            "unjoined": unjoined,
        }

    def _check(check: str, ok: bool | None, detail: str = "") -> None:
        checks.append({"check": check, "ok": ok, "detail": detail})

    required = [
        field
        for field in (
            hop_spec["join_map_field"],
            hop_spec["uncovered_field"],
            hop_spec["gate_field"],
        )
        if field
    ]

    # (a) downstream node persisted
    node_ok = downstream_fields is not None
    _check(
        "downstream-node-persisted",
        node_ok,
        f"{hop_spec['downstream']} {'persisted' if node_ok else 'not persisted'}",
    )
    if not node_ok:
        for name in ("coverage-predicates-present", "uncovered-list-empty"):
            _check(name, None, "not reached")
        return _done(HOP_MISSING_NODE)
    assert downstream_fields is not None  # narrowed by node_ok

    # (b) coverage predicates present (absent => pre-gate legacy node)
    missing = [f for f in required if f not in downstream_fields]
    _check(
        "coverage-predicates-present",
        not missing,
        "all present" if not missing else "absent: " + ", ".join(missing),
    )
    if missing:
        _check("uncovered-list-empty", None, "not reached")
        return _done(HOP_NOT_EVALUATED)

    # (c) uncovered-list raw literal equals the "[]" sentinel
    uncovered_raw = downstream_fields[hop_spec["uncovered_field"]]
    uncovered_ok = uncovered_raw == UNCOVERED_EMPTY_SENTINEL
    _check(
        "uncovered-list-empty",
        uncovered_ok,
        f'{hop_spec["uncovered_field"]} == "{UNCOVERED_EMPTY_SENTINEL}"'
        if uncovered_ok
        else f"{hop_spec['uncovered_field']} = {uncovered_raw!r}",
    )
    open_hop = not uncovered_ok

    # (d) P6-only explicit gate value check
    if hop_spec["gate_field"]:
        gate_raw = downstream_fields[hop_spec["gate_field"]]
        gate_ok = gate_raw == COVERAGE_GATE_PASS_SENTINEL
        _check(
            "coverage-gate-pass",
            gate_ok,
            f"{hop_spec['gate_field']} = {gate_raw!r}",
        )
        open_hop = open_hop or not gate_ok

    # (e) client-side JSON join: every upstream feature must appear as a
    # key of the downstream coverage map. Upstream leniency is deliberate
    # (R5 exp1): a missing upstream node/field joins vacuously.
    if hop_spec["join_map_field"]:
        source = _json_or(
            (upstream_fields or {}).get(hop_spec["join_source_field"]), []
        )
        if not isinstance(source, list):
            source = []
        if hop_spec["join_source_key"] is None:
            wanted = {e for e in source if isinstance(e, str)}
        else:
            wanted = {
                e.get(hop_spec["join_source_key"])
                for e in source
                if isinstance(e, dict)
            }
        covered = _covered_keys(
            _json_or(downstream_fields[hop_spec["join_map_field"]], None),
            hop_spec["join_map_key"],
        )
        unjoined.extend(
            sorted(str(w) for w in wanted if w not in covered)
        )
        join_ok = not unjoined
        _check(
            "join-upstream-covered",
            join_ok,
            f"{len(wanted) - len(unjoined)}/{len(wanted)} upstream features "
            f"joined into {hop_spec['join_map_field']}",
        )
        open_hop = open_hop or not join_ok

    return _done(HOP_OPEN if open_hop else HOP_CLOSED)


def evaluate_coverage_chain(
    coverage: dict[str, dict[str, str] | None],
) -> list[dict]:
    """Evaluate every COVERAGE_HOP_JOINS hop over fetched coverage fields.

    Pure convenience wrapper around evaluate_hop(); *coverage* is
    fetch_coverage_fields()'s result. Returns one evaluate_hop() row per
    hop, in chain order.
    """
    return [
        evaluate_hop(
            hop_spec,
            coverage.get(hop_spec["upstream"]),
            coverage.get(hop_spec["downstream"]),
        )
        for hop_spec in COVERAGE_HOP_JOINS
    ]


def coverage_overall(hops: list[dict]) -> str:
    """Fold per-hop states into the overall coverage verdict (R6 RQ2).

    PASS iff every hop is CLOSED. Any OPEN hop is a hard FAIL; otherwise a
    missing node makes the chain INCOMPLETE, and legacy predicate-absent
    hops leave it NOT-EVALUATED (never FAIL -- R5 exp1 precedence order).
    """
    states = [hop["state"] for hop in hops]
    if any(state == HOP_OPEN for state in states):
        return COVERAGE_FAIL
    if any(state == HOP_MISSING_NODE for state in states):
        return COVERAGE_INCOMPLETE
    if any(state == HOP_NOT_EVALUATED for state in states):
        return COVERAGE_NOT_EVALUATED
    return COVERAGE_PASS


def _trace_target_phase_id(
    target_uri: str, idea_id: str, known_phase_ids: set[str]
) -> str | None:
    """Map a trace:tracesTo target URI to a pipeline phase id for *idea_id*.

    Namespace-filtered and pattern-validated (R3 RQ1: malformed targets like
    double-prefixed ids and ideas-namespace URIs exist live): accepts both
    subject conventions observed in production, ``phase#idea-N-<pid>`` and
    ``phase#N-<pid>``. Returns None for foreign-namespace targets, targets
    of other ideas, and suffixes that are not a known pipeline phase id.
    """
    if not target_uri.startswith(PHASE_NS):
        return None
    local = target_uri[len(PHASE_NS):]
    bare = idea_id[len("idea-"):]
    for prefix in (f"{idea_id}-", f"{bare}-"):
        if local.startswith(prefix):
            phase_id = local[len(prefix):]
            if phase_id in known_phase_ids:
                return phase_id
    return None


def classify_phases(
    spec: dict,
    listing: list[dict],
    idea_id: str,
    d5_mode: str | None,
) -> list[dict]:
    """Classify every derived-pipeline phase into the frozen v1 state enum.

    Pure function over already-fetched bindings -- no I/O (ADR-003: verdict
    logic must be importable and drivable by tests without a live server).
    *spec* is derive_spec()'s result, *listing* fetch_phase_listing()'s,
    *d5_mode* fetch_d5_mode()'s; *idea_id* may be bare or idea-prefixed.

    States, in evidence-precedence order (stronger evidence wins):

    - persisted: a phase output node exists. Implies the gate PASSED --
      ADR-130-7 rolls nonconforming outputs back to zero triples, so
      persistence itself is the gate certificate.
    - missing-claimed: no node, but a dangling incoming trace:tracesTo edge
      (from a persisted successor) references this phase's node URI --
      queryable evidence a successor claimed an absent predecessor.
    - skipped: no node, no claim, but the persisted D5 mode routed the
      pipeline around this phase's family (D5_MODE_SKIPPED_FAMILIES).
    - not-persisted: everything else; ALWAYS carries AMBIGUITY_NOTE
      (never-ran and rolled-back are graph-identical read-only).

    Returns one row per derived-pipeline phase, in pipeline order, followed
    by persisted phases whose id is absent from the derived pipeline
    (pipeline_index None, family "" -- surfaced, never dropped)::

        {
          "phase_id":       e.g. "d1",
          "family":         agent family from the derived pipeline,
          "pipeline_index": position in spec["pipeline"] (None if unknown),
          "state":          frozen v1 enum value,
          "gate_shape":     runtime-derived phase:shaclGate URI (None if
                            the graph declares no gate for this phase),
          "results":        [{"result_uri", "traces_to"}] persisted nodes,
          "note":           AMBIGUITY_NOTE for not-persisted, else None,
        }
    """
    idea_id = _normalize_idea_id(idea_id)
    known_phase_ids = {p["phase_id"] for p in spec["pipeline"]}
    persisted_by_phase: dict[str, list[dict]] = {}
    persisted_uris: set[str] = set()
    for row in listing:
        persisted_by_phase.setdefault(row["phase_id"], []).append(
            {"result_uri": row["result_uri"], "traces_to": row["traces_to"]}
        )
        persisted_uris.add(row["result_uri"])

    # Dangling claims: trace targets that are no persisted node's URI but
    # map to a known phase id with no persisted node under EITHER subject
    # convention (a persisted phase stays persisted even when referenced
    # through the other convention's URI).
    claimed: set[str] = set()
    for row in listing:
        for target in row["traces_to"]:
            if target in persisted_uris:
                continue
            phase_id = _trace_target_phase_id(target, idea_id, known_phase_ids)
            if phase_id is not None and phase_id not in persisted_by_phase:
                claimed.add(phase_id)

    skipped_families = D5_MODE_SKIPPED_FAMILIES.get(d5_mode or "", ())

    def _row(phase_id: str, family: str, index: int | None) -> dict:
        if phase_id in persisted_by_phase:
            state = STATE_PERSISTED
        elif phase_id in claimed:
            state = STATE_MISSING_CLAIMED
        elif family in skipped_families:
            state = STATE_SKIPPED
        else:
            state = STATE_NOT_PERSISTED
        gates = spec["gates_by_phase"].get(phase_id, [])
        return {
            "phase_id": phase_id,
            "family": family,
            "pipeline_index": index,
            "state": state,
            "gate_shape": gates[0] if gates else None,
            "results": persisted_by_phase.get(phase_id, []),
            "note": AMBIGUITY_NOTE if state == STATE_NOT_PERSISTED else None,
        }

    rows = [
        _row(p["phase_id"], p["family"], i)
        for i, p in enumerate(spec["pipeline"])
    ]
    rows.extend(
        _row(phase_id, "", None)
        for phase_id in sorted(persisted_by_phase)
        if phase_id not in known_phase_ids
    )
    return rows


def _print_gate_report(idea_id: str, rows: list[dict]) -> None:
    """Render the classification rows as a human-readable table.

    One line per derived-pipeline phase with its frozen v1 state and the
    runtime-derived gate shape URI (persisted = that gate passed, ADR-130-7).
    not-persisted states are starred; the star expands to the full
    ambiguity note (carried on every such row) in a single footnote.
    """
    idea_id = _normalize_idea_id(idea_id)
    persisted = sum(1 for r in rows if r["state"] == STATE_PERSISTED)
    print(f"PHASES ({idea_id}): {persisted} persisted, {len(rows)} total")
    if not rows:
        return

    table = []
    for row in rows:
        state = row["state"]
        if row["note"] is not None:
            state += "*"
        gate = row["gate_shape"] or "-"
        results = row["results"]
        result = ", ".join(r["result_uri"] for r in results) or "-"
        traces = ", ".join(t for r in results for t in r["traces_to"]) or "-"
        table.append((row["phase_id"], row["family"] or "-", state, gate, result, traces))

    header = ("PHASE", "FAMILY", "STATE", "GATE", "RESULT", "TRACES-TO")
    widths = [
        max(len(header[col]), *(len(line[col]) for line in table))
        for col in range(len(header) - 1)
    ]
    print("  ".join(h.ljust(w) for h, w in zip(header, widths)) + f"  {header[-1]}")
    for line in table:
        cells = [cell.ljust(w) for cell, w in zip(line, widths)]
        print("  ".join(cells) + f"  {line[-1]}")
    if any(row["note"] is not None for row in rows):
        print(f"* {AMBIGUITY_NOTE}")


def _print_coverage_report(idea_id: str, hops: list[dict], verdict: str) -> None:
    """Render the coverage-chain hop evaluations as a human-readable table.

    Minimal T2.3 rendering (T4.1 folds this into the unified report object):
    one line per hop with its frozen v1 state and the itemized R6-RQ2 check
    results, then the overall verdict line -- COVERAGE: PASS appears only
    when every hop is CLOSED (coverage_overall guarantees it).
    """
    idea_id = _normalize_idea_id(idea_id)
    print(f"\nCOVERAGE CHAIN ({idea_id}):")
    table = []
    for hop in hops:
        evaluated = [c for c in hop["checks"] if c["ok"] is not None]
        detail = "; ".join(
            f"{c['check']}={'ok' if c['ok'] else 'FAILED (' + c['detail'] + ')'}"
            for c in evaluated
        )
        if hop["unjoined"]:
            detail += f"; unjoined: {', '.join(hop['unjoined'])}"
        table.append((hop["hop"], hop["state"], detail))

    header = ("HOP", "STATE", "CHECKS")
    widths = [
        max(len(header[col]), *(len(line[col]) for line in table))
        for col in range(len(header) - 1)
    ]
    print("  ".join(h.ljust(w) for h, w in zip(header, widths)) + f"  {header[-1]}")
    for line in table:
        cells = [cell.ljust(w) for cell, w in zip(line, widths)]
        print("  ".join(cells) + f"  {line[-1]}")
    print(f"COVERAGE: {verdict}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gate_audit.py",
        description=(
            "Read-only audit of Tulla pipeline gates for one idea: persisted "
            "phases in pipeline order with gate status and trace edges, plus "
            "the D5->P1->P4->P6 feature-coverage chain verdict."
        ),
        epilog=_PORT_CAVEAT,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "idea",
        help='Idea id to audit (e.g. "idea-15").',
    )
    parser.add_argument(
        "--server",
        default=os.environ.get("ONTOLOGY_API_URL", DEFAULT_SERVER),
        help=(
            "Base URL of the ontology server (default: %(default)s, "
            "overridable via ONTOLOGY_API_URL). Beware: the server's own "
            "default port is 8420, not 8100 — see the note below."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the machine-readable JSON report instead of tables.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        spec = derive_spec(args.server)
    except SpecNotLoadedError as exc:
        print(exc, file=sys.stderr)  # "spec not loaded" -- ADR-003: nonzero
        return 2
    except (SparqlError, OSError) as exc:
        # Covers urllib HTTPError/URLError (OSError subclasses) and the
        # endpoint's HTTP-200 {"error"} bodies: fail loudly, no fallback.
        print(f"gate_audit: {exc}", file=sys.stderr)
        return 2

    try:
        listing = fetch_phase_listing(args.server, args.idea, spec)
        d5_mode = fetch_d5_mode(args.server, args.idea)
        coverage = fetch_coverage_fields(args.server, args.idea, spec)
    except (SparqlError, OSError) as exc:
        print(f"gate_audit: {exc}", file=sys.stderr)
        return 2

    phases = classify_phases(spec, listing, args.idea, d5_mode)
    _print_gate_report(args.idea, phases)

    hops = evaluate_coverage_chain(coverage)
    _print_coverage_report(args.idea, hops, coverage_overall(hops))

    # Partial implementation (through task T2.3): the --json report lands
    # in T4.2, and the exit code mirrors the verdict only from T4.3 (after
    # T3.1 validates the hop logic -- until then it is not verdict-affecting).
    if args.json:
        print("gate_audit: --json not implemented yet", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
