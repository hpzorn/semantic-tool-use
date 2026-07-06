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

    # Skeleton (through task T1.2): classification and report rendering land
    # in subsequent tasks (T1.3+).
    print(
        "gate_audit: spec derived ({} phases, {} gate shapes); "
        "audit logic not implemented yet".format(
            len(spec["pipeline"]), len(spec["gate_uris"])
        ),
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
