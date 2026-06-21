"""Phase pipeline HTTP routes.

Exposes the 10 phase-pipeline functions as FastAPI endpoints alongside
the existing HTML dashboard view.  The ``handle_*`` functions are
framework-agnostic business-logic wrappers (returning (status, body)
tuples) that the FastAPI endpoints delegate to.
"""

from __future__ import annotations

import html
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ...mcp.phase_tools import (
    KGOntologyClient,
    KGSparqlClient,
    OntologyClient,
    SparqlClient,
    collect_upstream_facts,
    list_pipeline,
    next_phase,
    record_phase_result,
    render_gates,
    render_input_contract,
    render_methodology,
    render_output_contract,
    render_phase_prompt,
    render_tools,
)
from ...phase_constants import PHASE_NS  # shared constant — do NOT redefine

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Framework-agnostic handler functions (also used by tests)
# ---------------------------------------------------------------------------


def handle_collect_upstream_facts(
    sparql: SparqlClient,
    idea_id: str,
) -> dict[str, Any]:
    """Handle GET /phases/upstream-facts/{idea_id}."""
    if not idea_id:
        return {"idea_id": idea_id, "phases": {}, "error": "missing idea_id"}
    grouped = collect_upstream_facts(sparql, idea_id)
    return {"idea_id": idea_id, "phases": grouped}


def handle_render_methodology(
    sparql: SparqlClient,
    body: dict[str, Any] | None,
) -> tuple[int, dict[str, Any]]:
    """Handle POST /phase/render-methodology."""
    if not isinstance(body, dict):
        return 404, {"error": "missing phase_id"}
    phase_id = body.get("phase_id", "")
    if not phase_id or not isinstance(phase_id, str):
        return 404, {"error": "missing phase_id"}
    return 200, {"markdown": render_methodology(sparql, phase_id)}


def handle_render_tools(
    sparql: SparqlClient,
    body: dict[str, Any] | None,
) -> tuple[int, dict[str, Any]]:
    """Handle POST /phase/render-tools."""
    if not isinstance(body, dict):
        return 404, {"error": "missing phase_id"}
    phase_id = body.get("phase_id", "")
    if not phase_id or not isinstance(phase_id, str):
        return 404, {"error": "missing phase_id"}
    return 200, {"markdown": render_tools(sparql, phase_id)}


def handle_render_gates(
    sparql: SparqlClient,
    body: dict[str, Any] | None,
) -> tuple[int, dict[str, Any]]:
    """Handle POST /phase/render-gates."""
    if not isinstance(body, dict):
        return 404, {"error": "missing phase_id"}
    phase_id = body.get("phase_id", "")
    if not phase_id or not isinstance(phase_id, str):
        return 404, {"error": "missing phase_id"}
    return 200, {"markdown": render_gates(sparql, phase_id)}


def handle_render_input_contract(
    sparql: SparqlClient,
    body: dict[str, Any] | None,
) -> tuple[int, dict[str, Any]]:
    """Handle POST /phase/render-input-contract."""
    if not isinstance(body, dict):
        return 404, {"error": "missing phase_id"}
    phase_id = body.get("phase_id", "")
    if not phase_id or not isinstance(phase_id, str):
        return 404, {"error": "missing phase_id"}
    return 200, {"markdown": render_input_contract(sparql, phase_id)}


def handle_render_output_contract(
    sparql: SparqlClient,
    body: dict[str, Any] | None,
) -> tuple[int, dict[str, Any]]:
    """Handle POST /phase/render-output-contract."""
    if not isinstance(body, dict):
        return 404, {"error": "missing phase_id"}
    phase_id = body.get("phase_id", "")
    if not phase_id or not isinstance(phase_id, str):
        return 404, {"error": "missing phase_id"}
    return 200, {"markdown": render_output_contract(sparql, phase_id)}


def handle_render_phase_prompt(
    sparql: SparqlClient,
    body: dict[str, Any] | None,
) -> tuple[int, dict[str, Any]]:
    """Handle POST /phase/render-phase-prompt."""
    if not isinstance(body, dict):
        return 404, {"error": "missing phase_id"}
    phase_id = body.get("phase_id", "")
    if not phase_id or not isinstance(phase_id, str):
        return 404, {"error": "missing phase_id"}
    return 200, {"markdown": render_phase_prompt(sparql, phase_id)}


def handle_list_pipeline(
    sparql: SparqlClient,
    body: dict[str, Any] | None,
) -> tuple[int, dict[str, Any]]:
    """Handle POST /phase/list-pipeline."""
    if not isinstance(body, dict):
        return 404, {"error": "missing agent_family"}
    agent_family = body.get("agent_family", "")
    if not agent_family or not isinstance(agent_family, str):
        return 404, {"error": "missing agent_family"}
    return 200, {"pipeline": list_pipeline(sparql, agent_family)}


def handle_next_phase(
    sparql: SparqlClient,
    body: dict[str, Any] | None,
) -> tuple[int, dict[str, Any]]:
    """Handle POST /phase/next-phase."""
    if not isinstance(body, dict):
        return 404, {"error": "missing agent_family"}
    agent_family = body.get("agent_family", "")
    if not agent_family or not isinstance(agent_family, str):
        return 404, {"error": "missing agent_family"}
    current_id = body.get("current_id", "")
    if not current_id or not isinstance(current_id, str):
        return 404, {"error": "missing current_id"}
    verdict = body.get("verdict", "")
    if not isinstance(verdict, str):
        verdict = ""
    return 200, next_phase(sparql, agent_family, current_id, verdict)


def handle_record_phase_result(
    ontology: OntologyClient,
    body: dict[str, Any] | None,
) -> tuple[int, dict[str, Any]]:
    """Handle POST /phase/record-phase-result."""
    if not isinstance(body, dict):
        return 404, {"error": "missing phase_id"}
    phase_id = body.get("phase_id", "")
    if not phase_id or not isinstance(phase_id, str):
        return 404, {"error": "missing phase_id"}
    idea_id = body.get("idea_id", "")
    if not idea_id or not isinstance(idea_id, str):
        return 404, {"error": "missing idea_id"}

    artifact_path = body.get("artifact_path", "")
    if not isinstance(artifact_path, str):
        artifact_path = ""

    result_json = body.get("result_json", {})
    if not isinstance(result_json, dict):
        result_json = {}

    predecessor_phase_id = body.get("predecessor_phase_id")
    if predecessor_phase_id is not None and not isinstance(predecessor_phase_id, str):
        predecessor_phase_id = None

    result = record_phase_result(
        ontology,
        phase_id,
        idea_id,
        artifact_path,
        result_json,
        predecessor_phase_id,
    )
    return 200, result


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------


def _get_sparql(request: Request) -> KGSparqlClient:
    return KGSparqlClient(request.app.state.kg_store)


def _get_ontology(request: Request) -> KGOntologyClient:
    validator = getattr(request.app.state, "validator", None)
    return KGOntologyClient(request.app.state.kg_store, validator)


# ---------------------------------------------------------------------------
# JSON API endpoints
# ---------------------------------------------------------------------------


@router.get("/phases/upstream-facts/{idea_id}")
async def upstream_facts(request: Request, idea_id: str) -> JSONResponse:
    """Collect all phase facts for an idea."""
    sparql = _get_sparql(request)
    body = handle_collect_upstream_facts(sparql, idea_id)
    return JSONResponse(body)


@router.post("/phase/render-methodology")
async def render_methodology_endpoint(request: Request) -> JSONResponse:
    """Render the procedure markdown for a phase."""
    sparql = _get_sparql(request)
    status, payload = handle_render_methodology(sparql, await request.json())
    return JSONResponse(payload, status_code=status)


@router.post("/phase/render-tools")
async def render_tools_endpoint(request: Request) -> JSONResponse:
    """Render the tool list markdown for a phase."""
    sparql = _get_sparql(request)
    status, payload = handle_render_tools(sparql, await request.json())
    return JSONResponse(payload, status_code=status)


@router.post("/phase/render-gates")
async def render_gates_endpoint(request: Request) -> JSONResponse:
    """Render the SHACL gate list markdown for a phase."""
    sparql = _get_sparql(request)
    status, payload = handle_render_gates(sparql, await request.json())
    return JSONResponse(payload, status_code=status)


@router.post("/phase/render-input-contract")
async def render_input_contract_endpoint(request: Request) -> JSONResponse:
    """Render the input contract table markdown for a phase."""
    sparql = _get_sparql(request)
    status, payload = handle_render_input_contract(sparql, await request.json())
    return JSONResponse(payload, status_code=status)


@router.post("/phase/render-output-contract")
async def render_output_contract_endpoint(request: Request) -> JSONResponse:
    """Render the output contract markdown for a phase."""
    sparql = _get_sparql(request)
    status, payload = handle_render_output_contract(sparql, await request.json())
    return JSONResponse(payload, status_code=status)


@router.post("/phase/render-phase-prompt")
async def render_phase_prompt_endpoint(request: Request) -> JSONResponse:
    """Render the composed phase prompt markdown."""
    sparql = _get_sparql(request)
    status, payload = handle_render_phase_prompt(sparql, await request.json())
    return JSONResponse(payload, status_code=status)


@router.post("/phase/list-pipeline")
async def list_pipeline_endpoint(request: Request) -> JSONResponse:
    """List phases in an agent family in topological order."""
    sparql = _get_sparql(request)
    status, payload = handle_list_pipeline(sparql, await request.json())
    return JSONResponse(payload, status_code=status)


@router.post("/phase/next-phase")
async def next_phase_endpoint(request: Request) -> JSONResponse:
    """Return the next phase_id or terminate for the current phase."""
    sparql = _get_sparql(request)
    status, payload = handle_next_phase(sparql, await request.json())
    return JSONResponse(payload, status_code=status)


@router.post("/phase/record-phase-result")
async def record_phase_result_endpoint(request: Request) -> JSONResponse:
    """Persist a phase result using the 8-step ADR-130-7 sequence."""
    ontology = _get_ontology(request)
    status, payload = handle_record_phase_result(ontology, await request.json())
    return JSONResponse(payload, status_code=status)


# ---------------------------------------------------------------------------
# HTML dashboard (existing, preserved)
# ---------------------------------------------------------------------------


def _short(uri: str) -> str:
    if uri.startswith(PHASE_NS):
        return "phase:" + uri[len(PHASE_NS):]
    return uri


@router.get("/dashboard/phases/{phase_id}", response_class=HTMLResponse)
async def phase_content_view(request: Request, phase_id: str) -> HTMLResponse:
    """Render the RDF state of a single phase as read-only HTML."""
    store = request.app.state.store
    subject = f"{PHASE_NS}{phase_id}"

    sparql_q = f"SELECT ?p ?o WHERE {{ <{subject}> ?p ?o . }}"
    try:
        results = store.query(sparql_q)
    except Exception as exc:
        logger.exception("phase_content_view query failed for %s", subject)
        return HTMLResponse(
            f"<h1>Error</h1><p>{html.escape(str(exc))}</p>", status_code=500
        )

    procedure: str = ""
    tools: list[str] = []
    mcps: list[str] = []
    gate: str = ""
    input_contract: str = ""
    output_contract: str = ""
    other: list[tuple[str, str]] = []

    for row in results:
        pred = str(row[0]) if row[0] is not None else ""
        obj = str(row[1]) if row[1] is not None else ""

        if pred == f"{PHASE_NS}procedure":
            procedure = obj
        elif pred == f"{PHASE_NS}requiresTool":
            tools.append(obj)
        elif pred == f"{PHASE_NS}requiresMcp":
            mcps.append(obj)
        elif pred == f"{PHASE_NS}shaclGate":
            gate = obj
        elif pred == f"{PHASE_NS}inputContract":
            input_contract = obj
        elif pred == f"{PHASE_NS}outputContract":
            output_contract = obj
        else:
            other.append((pred, obj))

    found = bool(procedure or tools or mcps or gate or input_contract
                 or output_contract or other)

    if not found:
        return HTMLResponse(
            f"<!doctype html><html><head><title>phase:{html.escape(phase_id)}</title></head>"
            f"<body><h1>Phase not found: phase:{html.escape(phase_id)}</h1>"
            f"<p>No triples found for subject <code>{html.escape(subject)}</code>.</p>"
            f"</body></html>",
            status_code=404,
        )

    tools_html = "".join(
        f"<li><code>{html.escape(t)}</code></li>" for t in sorted(tools)
    ) or "<li><em>(none)</em></li>"
    mcps_html = "".join(
        f"<li><code>{html.escape(m)}</code></li>" for m in sorted(mcps)
    ) or "<li><em>(none)</em></li>"
    other_html = "".join(
        f"<tr><td><code>{html.escape(_short(p))}</code></td>"
        f"<td><code>{html.escape(_short(o))}</code></td></tr>"
        for p, o in sorted(other)
    )

    body = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>phase:{html.escape(phase_id)}</title>
  <style>
    body {{ font-family: -apple-system, sans-serif; max-width: 960px;
            margin: 2rem auto; padding: 0 1rem; color: #222; }}
    h1 {{ margin-bottom: 0.25rem; }}
    h2 {{ border-bottom: 1px solid #ccc; padding-bottom: 0.25rem;
          margin-top: 2rem; }}
    pre {{ background: #f5f5f5; padding: 1rem; overflow-x: auto;
           white-space: pre-wrap; word-wrap: break-word; }}
    code {{ background: #f5f5f5; padding: 0.1rem 0.3rem; border-radius: 3px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ text-align: left; padding: 0.3rem 0.6rem;
              border-bottom: 1px solid #eee; }}
    .empty {{ color: #888; font-style: italic; }}
  </style>
</head>
<body>
  <h1>phase:{html.escape(phase_id)}</h1>
  <p><code>{html.escape(subject)}</code></p>

  <h2>Procedure</h2>
  <pre>{html.escape(procedure) if procedure else '<span class="empty">(none)</span>'}</pre>

  <h2>Required Tools ({len(tools)})</h2>
  <ul>{tools_html}</ul>

  <h2>Required MCP Servers ({len(mcps)})</h2>
  <ul>{mcps_html}</ul>

  <h2>SHACL Gate</h2>
  <p>{f'<code>{html.escape(_short(gate))}</code>' if gate else '<span class="empty">(none)</span>'}</p>

  <h2>Contracts</h2>
  <p>Input: {f'<code>{html.escape(_short(input_contract))}</code>' if input_contract else '<span class="empty">(none)</span>'}</p>
  <p>Output: {f'<code>{html.escape(_short(output_contract))}</code>' if output_contract else '<span class="empty">(none)</span>'}</p>

  <h2>Other Properties ({len(other)})</h2>
  <table>
    <thead><tr><th>Predicate</th><th>Object</th></tr></thead>
    <tbody>{other_html or '<tr><td colspan="2" class="empty">(none)</td></tr>'}</tbody>
  </table>
</body>
</html>"""
    return HTMLResponse(body)
