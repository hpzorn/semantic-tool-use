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

_PORT_CAVEAT = (
    "Note on ports: this tool defaults to http://localhost:8100 (the port "
    "Tulla deployments conventionally expose the ontology server on), but "
    "the ontology server's own built-in default port is 8420 "
    "(src/ontology_server/config.py). If nothing answers on 8100, retry "
    "with --server http://localhost:8420 or set ONTOLOGY_API_URL."
)


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
    parser.parse_args(argv)
    # Skeleton (task T1.1): spec derivation, classification, and report
    # rendering land in subsequent tasks (T1.2+).
    print("gate_audit: audit logic not implemented yet (skeleton)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
