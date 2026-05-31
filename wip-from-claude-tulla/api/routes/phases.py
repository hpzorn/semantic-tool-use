"""HTTP route handlers for phase-related ontology-server endpoints.

Exposes :func:`mcp.phase_tools.collect_upstream_facts` over HTTP at::

    GET /phases/upstream-facts/{idea_id}

and :func:`mcp.phase_tools.render_methodology` (req-130-2-2) at::

    POST /phase/render-methodology   { "phase_id": "..." }

The handlers are framework-agnostic: they accept a SPARQL client (any
object implementing ``sparql_query(query) -> dict``) plus the relevant
payload and return JSON-serialisable dicts.

A thin ``register(app)`` shim is provided for the common case of a Flask /
FastAPI-compatible router; servers using a different framework can call
:func:`handle_collect_upstream_facts` or
:func:`handle_render_methodology` directly.

The ``/phase/render-output-contract`` twin (req-130-2-6) sits alongside
the input-contract twin: same shape on ``phase:outputContract`` plus an
``## Emits Intent Fields`` block sourced from the
``phase:emitsIntentField`` triples populated by the extractor in
Task 1.2 from ``PHASE_PREDICATE_NAMES``.
"""

from __future__ import annotations

from typing import Any

from mcp.phase_tools import (
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


_ROUTE_PATH = "/phases/upstream-facts/{idea_id}"
_RENDER_METHODOLOGY_PATH = "/phase/render-methodology"
_RENDER_TOOLS_PATH = "/phase/render-tools"
_RENDER_GATES_PATH = "/phase/render-gates"
_RENDER_INPUT_CONTRACT_PATH = "/phase/render-input-contract"
_RENDER_OUTPUT_CONTRACT_PATH = "/phase/render-output-contract"
_RENDER_PHASE_PROMPT_PATH = "/phase/render-phase-prompt"
_LIST_PIPELINE_PATH = "/phase/list-pipeline"
_NEXT_PHASE_PATH = "/phase/next-phase"
_RECORD_PHASE_RESULT_PATH = "/phase/record-phase-result"


def handle_collect_upstream_facts(
    sparql: SparqlClient,
    idea_id: str,
) -> dict[str, Any]:
    """Handle ``GET /phases/upstream-facts/{idea_id}``.

    Returns a JSON-serialisable response body of the form::

        {"idea_id": "...", "phases": {phase_id: {field: typed_value}}}

    Empty result is reported as ``"phases": {}`` (not an error).  Coercion
    semantics are inherited from :func:`mcp.phase_tools._try_coerce`.
    """
    if not idea_id:
        return {"idea_id": idea_id, "phases": {}, "error": "missing idea_id"}

    grouped = collect_upstream_facts(sparql, idea_id)
    return {"idea_id": idea_id, "phases": grouped}


def handle_render_methodology(
    sparql: SparqlClient,
    body: dict[str, Any] | None,
) -> tuple[int, dict[str, Any]]:
    """Handle ``POST /phase/render-methodology``.

    Request body is a JSON object with a single ``phase_id`` field.
    Returns a ``(status_code, response_body)`` tuple so framework
    adapters can map the status onto the underlying HTTP response:

    * ``200`` with ``{"markdown": "..."}`` on success, including the
      empty-string case when the phase exists but has no
      ``phase:procedure`` literal (the warning is emitted by
      :func:`mcp.phase_tools.render_methodology`).
    * ``404`` with ``{"error": "missing phase_id"}`` when the body is
      missing or omits a non-empty ``phase_id``; this mirrors the
      "missing phase_id returns 404 / MCP error" edge case spelled out
      by req-130-2-2.
    """
    if not isinstance(body, dict):
        return 404, {"error": "missing phase_id"}
    phase_id = body.get("phase_id", "")
    if not phase_id or not isinstance(phase_id, str):
        return 404, {"error": "missing phase_id"}

    markdown = render_methodology(sparql, phase_id)
    return 200, {"markdown": markdown}


def handle_render_tools(
    sparql: SparqlClient,
    body: dict[str, Any] | None,
) -> tuple[int, dict[str, Any]]:
    """Handle ``POST /phase/render-tools``.

    Mirrors :func:`handle_render_methodology`: a JSON object with a
    ``phase_id`` field yields ``200`` with ``{"markdown": "..."}``, while
    a missing or non-string ``phase_id`` yields ``404`` with
    ``{"error": "missing phase_id"}``.  An empty tool list is still a
    successful response — the markdown body just contains the two empty
    sections.
    """
    if not isinstance(body, dict):
        return 404, {"error": "missing phase_id"}
    phase_id = body.get("phase_id", "")
    if not phase_id or not isinstance(phase_id, str):
        return 404, {"error": "missing phase_id"}

    markdown = render_tools(sparql, phase_id)
    return 200, {"markdown": markdown}


def handle_render_gates(
    sparql: SparqlClient,
    body: dict[str, Any] | None,
) -> tuple[int, dict[str, Any]]:
    """Handle ``POST /phase/render-gates``.

    Mirrors :func:`handle_render_methodology`: a JSON object with a
    ``phase_id`` field yields ``200`` with ``{"markdown": "..."}`` (one
    ``SHACL Gate: <uri> — <label>`` line per gate), while a missing or
    non-string ``phase_id`` yields ``404`` with
    ``{"error": "missing phase_id"}``.  A phase without any
    ``phase:shaclGate`` triple is a successful 200 with empty markdown.
    """
    if not isinstance(body, dict):
        return 404, {"error": "missing phase_id"}
    phase_id = body.get("phase_id", "")
    if not phase_id or not isinstance(phase_id, str):
        return 404, {"error": "missing phase_id"}

    markdown = render_gates(sparql, phase_id)
    return 200, {"markdown": markdown}


def handle_render_input_contract(
    sparql: SparqlClient,
    body: dict[str, Any] | None,
) -> tuple[int, dict[str, Any]]:
    """Handle ``POST /phase/render-input-contract``.

    Mirrors :func:`handle_render_methodology`: a JSON object with a
    ``phase_id`` field yields ``200`` with ``{"markdown": "..."}`` (a
    three-column markdown table of Field | Type | Description), while a
    missing or non-string ``phase_id`` yields ``404`` with
    ``{"error": "missing phase_id"}``.  A phase without any
    ``phase:inputContract`` is a successful 200 with empty markdown.
    """
    if not isinstance(body, dict):
        return 404, {"error": "missing phase_id"}
    phase_id = body.get("phase_id", "")
    if not phase_id or not isinstance(phase_id, str):
        return 404, {"error": "missing phase_id"}

    markdown = render_input_contract(sparql, phase_id)
    return 200, {"markdown": markdown}


def handle_render_output_contract(
    sparql: SparqlClient,
    body: dict[str, Any] | None,
) -> tuple[int, dict[str, Any]]:
    """Handle ``POST /phase/render-output-contract``.

    Mirrors :func:`handle_render_input_contract`: a JSON object with a
    ``phase_id`` field yields ``200`` with ``{"markdown": "..."}`` (a
    three-column Field | Type | Description table followed by an
    ``## Emits Intent Fields`` bullet block listing the JSON keys the
    phase subagent must emit, in Pydantic order), while a missing or
    non-string ``phase_id`` yields ``404`` with
    ``{"error": "missing phase_id"}``.  A phase without any
    ``phase:outputContract`` and without any ``phase:emitsIntentField``
    is a successful 200 with empty markdown.
    """
    if not isinstance(body, dict):
        return 404, {"error": "missing phase_id"}
    phase_id = body.get("phase_id", "")
    if not phase_id or not isinstance(phase_id, str):
        return 404, {"error": "missing phase_id"}

    markdown = render_output_contract(sparql, phase_id)
    return 200, {"markdown": markdown}


def handle_render_phase_prompt(
    sparql: SparqlClient,
    body: dict[str, Any] | None,
) -> tuple[int, dict[str, Any]]:
    """Handle ``POST /phase/render-phase-prompt``.

    Coarse default renderer (req-130-2-7) — composition of the five
    granular renderers in canonical order under their canonical H2
    section headers.  Phase subagents call this at step 1 of their
    static ``.md`` body to seed their initial context.

    A JSON object with a ``phase_id`` field yields ``200`` with
    ``{"markdown": "..."}``; a missing or non-string ``phase_id``
    yields ``404`` with ``{"error": "missing phase_id"}``.  A phase
    whose granular renderers all return empty bodies is still a
    successful 200 with a header-only skeleton.
    """
    if not isinstance(body, dict):
        return 404, {"error": "missing phase_id"}
    phase_id = body.get("phase_id", "")
    if not phase_id or not isinstance(phase_id, str):
        return 404, {"error": "missing phase_id"}

    markdown = render_phase_prompt(sparql, phase_id)
    return 200, {"markdown": markdown}


def handle_list_pipeline(
    sparql: SparqlClient,
    body: dict[str, Any] | None,
) -> tuple[int, dict[str, Any]]:
    """Handle ``POST /phase/list-pipeline``.

    Request body is a JSON object with a single ``agent_family`` field.
    Returns a ``(status_code, response_body)`` tuple:

    * ``200`` with ``{"pipeline": [phase_id, ...]}`` on success — the list
      is sorted topologically by ancestor depth (depth 0 first) per
      req-130-2-8.  An agent family with no phases returns
      ``{"pipeline": []}`` (still a 200).
    * ``404`` with ``{"error": "missing agent_family"}`` when the body is
      missing or omits a non-empty ``agent_family`` string.
    """
    if not isinstance(body, dict):
        return 404, {"error": "missing agent_family"}
    agent_family = body.get("agent_family", "")
    if not agent_family or not isinstance(agent_family, str):
        return 404, {"error": "missing agent_family"}

    pipeline = list_pipeline(sparql, agent_family)
    return 200, {"pipeline": pipeline}


def handle_next_phase(
    sparql: SparqlClient,
    body: dict[str, Any] | None,
) -> tuple[int, dict[str, Any]]:
    """Handle ``POST /phase/next-phase``.

    Request body is a JSON object with ``agent_family``, ``current_id``,
    and ``verdict`` fields.  Returns a ``(status_code, response_body)``
    tuple:

    * ``200`` with ``{"next_id": "<phase_id>" | "terminate"}`` on
      success — single-successor edges return verbatim regardless of
      verdict, branching nodes return the verdict-matching successor,
      and a missing successor (or unmatched verdict on a branching
      node) returns ``"terminate"``.
    * ``404`` with ``{"error": "missing agent_family"}`` or
      ``{"error": "missing current_id"}`` when those fields are missing
      or non-string in the body.  ``verdict`` is treated as the empty
      string when absent or non-string, since the linear-successor case
      ignores it anyway.
    """
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

    result = next_phase(sparql, agent_family, current_id, verdict)
    return 200, result


def handle_record_phase_result(
    ontology: OntologyClient,
    body: dict[str, Any] | None,
) -> tuple[int, dict[str, Any]]:
    """Handle ``POST /phase/record-phase-result``.

    Implements the HTTP twin of :func:`mcp.phase_tools.record_phase_result`
    (req-130-3-3 / ADR-130-7).  Request body fields:

    * ``phase_id`` (required, non-empty string) — phase identifier.
    * ``idea_id`` (required, non-empty string) — requirement identifier.
    * ``artifact_path`` (optional, defaults to the empty string) — used
      for audit/logging only; never persisted as a triple.
    * ``result_json`` (optional dict, defaults to ``{}``) — the
      structured JSON the subagent emitted; only intent-field keys in
      ``PHASE_PREDICATE_NAMES[phase_id]`` are persisted as
      ``phase:preserves-*`` triples.
    * ``predecessor_phase_id`` (optional string) — upstream phase id
      to link via ``trace:tracesTo``.

    Returns a ``(status_code, response_body)`` tuple:

    * ``200`` with ``{"ok": true, "violations": []}`` on a clean
      persist (or when the phase has no SHACL gate attached).
    * ``200`` with ``{"ok": false, "violations": [...]}`` when SHACL
      validation fails — the persisted triples are rolled back by the
      underlying tool, so a violation response is still a successful
      HTTP exchange (the failure is in the *content*, not the
      transport).
    * ``404`` with ``{"error": "missing phase_id"}`` or
      ``{"error": "missing idea_id"}`` when those fields are missing
      or non-string, mirroring the rest of the phase HTTP twins.
    """
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


def register(app: Any, sparql: SparqlClient) -> None:
    """Register the phase routes on a Flask/FastAPI-compatible *app*.

    The registration is opt-in: callers using a different web framework
    can wire up :func:`handle_collect_upstream_facts` or
    :func:`handle_render_methodology` themselves.  The shim looks for an
    ``app.get`` / ``app.post`` decorator first (FastAPI / Starlette style)
    and falls back to ``app.route`` (Flask style).
    """
    upstream_handler = lambda idea_id: handle_collect_upstream_facts(sparql, idea_id)  # noqa: E731
    render_handler = lambda body: handle_render_methodology(sparql, body)  # noqa: E731
    tools_handler = lambda body: handle_render_tools(sparql, body)  # noqa: E731
    gates_handler = lambda body: handle_render_gates(sparql, body)  # noqa: E731
    input_contract_handler = lambda body: handle_render_input_contract(sparql, body)  # noqa: E731
    output_contract_handler = lambda body: handle_render_output_contract(sparql, body)  # noqa: E731
    phase_prompt_handler = lambda body: handle_render_phase_prompt(sparql, body)  # noqa: E731
    list_pipeline_handler = lambda body: handle_list_pipeline(sparql, body)  # noqa: E731
    next_phase_handler = lambda body: handle_next_phase(sparql, body)  # noqa: E731
    record_phase_result_handler = lambda body: handle_record_phase_result(sparql, body)  # noqa: E731

    if hasattr(app, "get") and hasattr(app, "post"):
        app.get(_ROUTE_PATH)(upstream_handler)
        app.post(_RENDER_METHODOLOGY_PATH)(render_handler)
        app.post(_RENDER_TOOLS_PATH)(tools_handler)
        app.post(_RENDER_GATES_PATH)(gates_handler)
        app.post(_RENDER_INPUT_CONTRACT_PATH)(input_contract_handler)
        app.post(_RENDER_OUTPUT_CONTRACT_PATH)(output_contract_handler)
        app.post(_RENDER_PHASE_PROMPT_PATH)(phase_prompt_handler)
        app.post(_LIST_PIPELINE_PATH)(list_pipeline_handler)
        app.post(_NEXT_PHASE_PATH)(next_phase_handler)
        app.post(_RECORD_PHASE_RESULT_PATH)(record_phase_result_handler)
    elif hasattr(app, "route"):
        app.route(_ROUTE_PATH, methods=["GET"])(upstream_handler)
        app.route(_RENDER_METHODOLOGY_PATH, methods=["POST"])(render_handler)
        app.route(_RENDER_TOOLS_PATH, methods=["POST"])(tools_handler)
        app.route(_RENDER_GATES_PATH, methods=["POST"])(gates_handler)
        app.route(_RENDER_INPUT_CONTRACT_PATH, methods=["POST"])(input_contract_handler)
        app.route(_RENDER_OUTPUT_CONTRACT_PATH, methods=["POST"])(output_contract_handler)
        app.route(_RENDER_PHASE_PROMPT_PATH, methods=["POST"])(phase_prompt_handler)
        app.route(_LIST_PIPELINE_PATH, methods=["POST"])(list_pipeline_handler)
        app.route(_NEXT_PHASE_PATH, methods=["POST"])(next_phase_handler)
        app.route(_RECORD_PHASE_RESULT_PATH, methods=["POST"])(record_phase_result_handler)
    else:
        raise TypeError(
            "register() requires an app with .get+.post or .route; "
            f"got {type(app).__name__}",
        )
