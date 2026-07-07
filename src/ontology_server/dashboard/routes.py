"""Dashboard route handlers.

Ports all 12 routes from the standalone viewer ``app.py`` into the
dashboard sub-package.  Each handler obtains a :class:`DashboardService`
from ``request.app.state``, calls the appropriate service method, and
renders a Jinja2 template.

Routes
------
- ``GET /``                              — dashboard landing page
- ``GET /instances``                     — instance list (T-Box browser)
- ``GET /instances/{uri:path}``          — instance detail
- ``GET /ideas``                         — ideas list (A-Box)
- ``GET /ideas/{idea_id}``               — idea detail
- ``GET /phases/{idea_id}``              — phase trail for an idea
- ``GET /phases/{idea_id}/{phase_id}``   — single phase detail
- ``GET /facts``                         — facts browser landing
- ``GET /facts/{context}``               — facts for a context
- ``GET /prds``                          — PRD context list
- ``GET /prds/{context}``                — PRD requirement graph
- ``GET /prds/{context}/{subject:path}`` — single requirement detail
- ``GET /projects/{project_id}``         — project detail
- ``GET /partials/instance-rows``        — HTMX partial: instance rows
- ``GET /partials/instance-properties``  — HTMX partial: instance props
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .services import DashboardService

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LIFECYCLE_ORDER = [
    "seed", "backlog", "researching", "planning", "implementing",
    "validating", "completed", "archived", "rejected", "blocked",
]


def _get_service(request: Request) -> DashboardService:
    """Build a :class:`DashboardService` from ``request.app.state`` stores."""
    state = request.app.state
    return DashboardService(
        ontology_store=state.ontology_store,
        kg_store=state.kg_store,
        agent_memory=state.agent_memory,
        ideas_store=state.ideas_store,
    )


# ---------------------------------------------------------------------------
# Dashboard landing page
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    """Render the dashboard landing page with summary stats."""
    service = _get_service(request)
    summary = service.get_dashboard_summary()
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, **summary},
    )


# ---------------------------------------------------------------------------
# Instance browser (T-Box)
# ---------------------------------------------------------------------------


@router.get("/instances", response_class=HTMLResponse)
async def instance_list(
    request: Request,
    class_uri: str | None = None,
    ontology_uri: str | None = None,
) -> HTMLResponse:
    """Render the instance list, optionally filtered by class or ontology."""
    service = _get_service(request)
    classes = service.list_classes(ontology_uri=ontology_uri)
    instances = (
        service.list_instances(class_uri=class_uri, ontology_uri=ontology_uri)
        if class_uri
        else []
    )
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "instance_list.html",
        {
            "request": request,
            "instances": instances,
            "classes": classes,
            "selected_class": class_uri,
            "selected_ontology": ontology_uri,
        },
    )


@router.get("/instances/{instance_uri:path}", response_class=HTMLResponse)
async def instance_detail(
    request: Request,
    instance_uri: str,
    ontology_uri: str | None = None,
) -> HTMLResponse:
    """Render the detail view for a single instance."""
    service = _get_service(request)
    detail = service.get_instance_detail(
        instance_uri=instance_uri,
        ontology_uri=ontology_uri,
    )
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "instance_detail.html",
        {"request": request, **detail},
    )


# ---------------------------------------------------------------------------
# Ideas browser (A-Box)
# ---------------------------------------------------------------------------


@router.get("/ideas", response_class=HTMLResponse)
async def idea_list(
    request: Request,
    lifecycle: str | None = None,
    search: str | None = None,
) -> HTMLResponse:
    """Render the ideas list with optional filtering."""
    service = _get_service(request)
    ideas = service.list_ideas(lifecycle=lifecycle, search=search)
    lifecycle_counts = service.get_idea_lifecycle_summary()
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "idea_list.html",
        {
            "request": request,
            "ideas": ideas,
            "lifecycle_counts": lifecycle_counts,
            "lifecycle_order": LIFECYCLE_ORDER,
            "selected_lifecycle": lifecycle,
            "search_query": search or "",
        },
    )


@router.get("/phases/{idea_id}", response_class=HTMLResponse)
async def phase_trail(
    request: Request,
    idea_id: str,
) -> HTMLResponse:
    """Render the phase trail for an idea showing all phase outputs."""
    service = _get_service(request)
    phase_facts = service.get_phase_facts(idea_id)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "phase_trail.html",
        {"request": request, "idea_id": idea_id, "phase_facts": phase_facts},
    )


@router.get("/phases/{idea_id}/{phase_id}", response_class=HTMLResponse)
async def phase_detail(
    request: Request,
    idea_id: str,
    phase_id: str,
) -> HTMLResponse:
    """Render the detail view for a single phase output."""
    service = _get_service(request)
    detail = service.get_phase_detail(idea_id, phase_id)
    templates = request.app.state.templates

    if detail is None:
        # Fall back to generic detail with raw triples
        uri = f"http://tulla.dev/phase#{idea_id}-{phase_id}"
        triples = service.get_triples_for_uri(uri)
        return templates.TemplateResponse(
            "generic_detail.html",
            {"request": request, "uri": uri, "triples": triples},
        )

    return templates.TemplateResponse(
        "phase_detail.html",
        {"request": request, **detail},
    )


@router.get("/ideas/{idea_id}", response_class=HTMLResponse)
async def idea_detail(request: Request, idea_id: str) -> HTMLResponse:
    """Render the detail view for a single idea."""
    service = _get_service(request)
    detail = service.get_idea_detail(idea_id)
    templates = request.app.state.templates
    if detail is None:
        return templates.TemplateResponse(
            "idea_detail.html",
            {"request": request, "error": f"Idea not found: {idea_id}"},
        )

    # Check for PRD context and compute progress
    prd_context = f"prd-{idea_id}"
    prd_requirements = service.get_prd_requirements(prd_context)
    prd_progress = None
    if prd_requirements:
        total = len(prd_requirements)
        completed = sum(
            1 for req in prd_requirements
            if _first_value(req.get("prd:status")) == "Completed"
        )
        percent = int(100 * completed / total) if total else 0
        prd_progress = {
            "total": total,
            "completed": completed,
            "percent": percent,
        }

    # Build context navigation: check for prd-idea-{id}, arch-idea-{id}, lesson-idea-{id}
    # Per ADR-74-3: try {type}-idea-{id} first, fall back to {type}-{id}
    all_contexts = set(service.list_fact_contexts())
    context_types = ["prd", "arch", "lesson"]
    contexts: dict[str, str | None] = {}
    for ctx_type in context_types:
        # Try standard pattern first: {type}-idea-{id}
        standard_name = f"{ctx_type}-idea-{idea_id}"
        fallback_name = f"{ctx_type}-{idea_id}"
        if standard_name in all_contexts:
            contexts[ctx_type] = standard_name
        elif fallback_name in all_contexts:
            contexts[ctx_type] = fallback_name
        else:
            contexts[ctx_type] = None

    # In-place editing: raw editable string form per field + widget config.
    canonical_id = detail.get("id", idea_id)
    idea = request.app.state.ideas_store.get_idea(canonical_id)
    editable = (
        {name: _idea_field_raw(idea, name) for name in _IDEA_FIELD_INPUTS}
        if idea is not None else {}
    )

    return templates.TemplateResponse(
        "idea_detail.html",
        {
            "request": request, "prd_progress": prd_progress,
            "contexts": contexts, "editable": editable,
            "widgets": _IDEA_FIELD_INPUTS,
            "idea_uri": f"http://semantic-tool-use.org/ideas/{canonical_id}",
            **detail,
        },
    )


def _first_value(val: str | list | None, default: str = "") -> str:
    """Extract the first value from a potentially multi-valued field."""
    if isinstance(val, list):
        return val[0] if val else default
    return val if val is not None else default


# ---------------------------------------------------------------------------
# Facts browser
# ---------------------------------------------------------------------------


@router.get("/facts", response_class=HTMLResponse)
async def facts_browser(request: Request) -> HTMLResponse:
    """Render the facts browser landing page listing all contexts."""
    service = _get_service(request)
    contexts = service.list_fact_contexts()
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "facts_browser.html",
        {"request": request, "contexts": contexts},
    )


@router.get("/facts/{context}", response_class=HTMLResponse)
async def facts_context(
    request: Request,
    context: str,
    subject: str | None = None,
) -> HTMLResponse:
    """Render facts for a context, optionally filtered by subject."""
    service = _get_service(request)
    if subject:
        facts = service.list_facts(context=context, subject=subject)
        subjects: list[str] = []
    else:
        subjects = service.get_fact_subjects(context)
        facts: list = []
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "facts_context.html",
        {
            "request": request,
            "context": context,
            "subjects": subjects,
            "facts": facts,
            "selected_subject": subject,
        },
    )


# ---------------------------------------------------------------------------
# PRD / requirements browser
# ---------------------------------------------------------------------------


@router.get("/prds", response_class=HTMLResponse)
async def prd_list(request: Request) -> HTMLResponse:
    """Render the list of all PRD contexts."""
    service = _get_service(request)
    contexts = service.list_prd_contexts()
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "prd_list.html",
        {"request": request, "contexts": contexts},
    )


@router.get("/prds/{context}", response_class=HTMLResponse)
async def prd_detail(request: Request, context: str) -> HTMLResponse:
    """Render the requirement list / dependency graph for a PRD."""
    service = _get_service(request)
    raw_requirements = service.get_prd_requirements(context)

    # Transform raw fact-property dicts into template-friendly format.
    # Raw keys are predicates like "prd:title", "prd:status", etc.
    # Multi-valued predicates may be lists; take the first value.
    def _first(val: str | list | None, default: str = "") -> str:
        if isinstance(val, list):
            return val[0] if val else default
        return val if val is not None else default

    requirements = []
    for raw in raw_requirements:
        deps = raw.get("prd:dependsOn", [])
        if isinstance(deps, str):
            deps = [deps] if deps else []
        requirements.append({
            "subject": raw.get("subject", ""),
            "taskId": _first(raw.get("prd:taskId")),
            "title": _first(raw.get("prd:title")),
            "phase": _first(raw.get("prd:phase"), "1"),
            "priority": _first(raw.get("prd:priority")).removeprefix("prd:"),
            "status": _first(raw.get("prd:status"), "Pending").removeprefix("prd:"),
            "action": _first(raw.get("prd:action")),
            "depends_on": deps,
        })

    # Group by phase number for the dependency graph
    phases: dict[str, list] = {}
    for req in sorted(requirements, key=lambda r: r["taskId"]):
        phase = req["phase"]
        phases.setdefault(phase, []).append(req)

    # Calculate progress stats
    total = len(requirements)
    completed = sum(
        1 for req in requirements
        if req["status"].lower() in ("completed", "done")
    )
    percent = int(100 * completed / total) if total else 0
    progress = {
        "total": total,
        "completed": completed,
        "percent": percent,
    }

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "prd_detail.html",
        {
            "request": request,
            "context": context,
            "requirements": requirements,
            "phases": phases,
            "progress": progress,
        },
    )


@router.get("/projects/{project_id}", response_class=HTMLResponse)
async def project_detail(
    request: Request,
    project_id: str,
) -> HTMLResponse:
    """Render the detail view for a single project."""
    service = _get_service(request)
    detail = service.get_project_detail(project_id)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "project_detail.html",
        {"request": request, **detail},
    )


@router.get("/prds/{context}/{subject:path}", response_class=HTMLResponse)
async def requirement_detail(
    request: Request,
    context: str,
    subject: str,
) -> HTMLResponse:
    """Render the detail view for a single requirement."""
    service = _get_service(request)
    raw = service.get_requirement_detail(context, subject)
    templates = request.app.state.templates

    # Transform raw fact-property dict into template-friendly format
    def _first(val: str | list | None, default: str = "") -> str:
        if isinstance(val, list):
            return val[0] if val else default
        return val if val is not None else default

    # Check if requirement was found (has rdf:type)
    found = raw.get("rdf:type") == "prd:Requirement"

    # Extract dependencies
    deps = raw.get("prd:dependsOn", [])
    if isinstance(deps, str):
        deps = [deps] if deps else []

    # Fetch dependency details for the deps table
    deps_detail = []
    for dep_subj in deps:
        dep_raw = service.get_requirement_detail(context, dep_subj)
        deps_detail.append({
            "subject": dep_subj,
            "taskId": _first(dep_raw.get("prd:taskId")),
            "title": _first(dep_raw.get("prd:title")),
            "status": _first(dep_raw.get("prd:status"), "Pending").removeprefix("prd:"),
        })

    # Find requirements that depend on this one (reverse dependencies)
    all_reqs = service.get_prd_requirements(context)
    depended_by_detail = []
    for req in all_reqs:
        req_deps = req.get("prd:dependsOn", [])
        if isinstance(req_deps, str):
            req_deps = [req_deps] if req_deps else []
        if subject in req_deps:
            depended_by_detail.append({
                "subject": req.get("subject", ""),
                "taskId": _first(req.get("prd:taskId")),
                "title": _first(req.get("prd:title")),
                "status": _first(req.get("prd:status"), "Pending").removeprefix("prd:"),
            })

    # Fetch phase history for this requirement
    phase_history = service.get_requirement_phase_history(context, subject)

    # Resolve quality focus chain
    quality_focus_raw = _first(raw.get("prd:qualityFocus"))
    quality_focus_chain = service.get_quality_focus_chain(quality_focus_raw)

    # Fact URIs backing this requirement — for the edit link + history.
    req_facts = request.app.state.agent_memory.recall(
        context=context, subject=subject, limit=200,
    )
    fact_targets = [
        f"http://semantic-tool-use.org/memory/fact/{f['fact_id']}"
        for f in req_facts if f.get("fact_id")
    ]

    detail = {
        "subject": raw.get("subject", subject),
        "context": context,
        "found": found,
        "fact_targets": fact_targets,
        "error": f"Requirement not found: {subject}" if not found else None,
        "title": _first(raw.get("prd:title")),
        "taskId": _first(raw.get("prd:taskId")),
        "phase": _first(raw.get("prd:phase"), "1"),
        "priority": _first(raw.get("prd:priority")).removeprefix("prd:"),
        "status": _first(raw.get("prd:status"), "Pending").removeprefix("prd:"),
        "action": _first(raw.get("prd:action")),
        "files": _first(raw.get("prd:files")),
        "description": _first(raw.get("prd:description")),
        "verification": _first(raw.get("prd:verification")),
        "deps_detail": deps_detail,
        "depended_by_detail": depended_by_detail,
        "phase_history": phase_history,
        "quality_focus_chain": quality_focus_chain,
    }

    return templates.TemplateResponse(
        "requirement_detail.html",
        {"request": request, **detail},
    )


# ---------------------------------------------------------------------------
# HTMX partial endpoints (HTML fragments, no base layout)
# ---------------------------------------------------------------------------


@router.get("/partials/instance-rows", response_class=HTMLResponse)
async def partial_instance_rows(
    request: Request,
    class_uri: str | None = None,
    ontology_uri: str | None = None,
) -> HTMLResponse:
    """Return instance table rows for HTMX swap."""
    service = _get_service(request)
    instances = (
        service.list_instances(class_uri=class_uri, ontology_uri=ontology_uri)
        if class_uri
        else []
    )
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "partials/instance_rows.html",
        {"request": request, "instances": instances},
    )


@router.get("/partials/instance-properties", response_class=HTMLResponse)
async def partial_instance_properties(
    request: Request,
    instance_uri: str,
    ontology_uri: str | None = None,
) -> HTMLResponse:
    """Return instance properties table for HTMX swap."""
    service = _get_service(request)
    detail = service.get_instance_detail(
        instance_uri=instance_uri,
        ontology_uri=ontology_uri,
    )
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "partials/instance_properties.html",
        {"request": request, **detail},
    )


# ---------------------------------------------------------------------------
# URI resolver (dispatches to the appropriate detail view)
# ---------------------------------------------------------------------------


@router.get("/resolve/{uri:path}", response_class=HTMLResponse)
async def resolve(request: Request, uri: str) -> HTMLResponse:
    """Resolve a URI to the appropriate detail view.

    Uses :meth:`DashboardService.resolve_uri` to determine the route,
    then either redirects (for known routes) or renders a generic
    detail page.
    """
    service = _get_service(request)
    route_name, params = service.resolve_uri(uri)

    # Redirect for routes that have a dedicated page
    _redirect_map = {
        "phase_detail": lambda p: f"/phases/{p['idea_id']}/{p['phase_id']}",
        "idea_detail": lambda p: f"/ideas/{p['idea_id']}",
        "requirement_detail": lambda p: f"/prds/{p['context']}/{p['subject']}",
        "project_detail": lambda p: f"/projects/{p['project_id']}",
    }
    if route_name in _redirect_map:
        target = _redirect_map[route_name](params)
        return RedirectResponse(url=target, status_code=302)

    # Fallback: render generic detail with all triples
    triples = service.get_triples_for_uri(uri)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "generic_detail.html",
        {"request": request, "uri": uri, "triples": triples},
    )


# ---------------------------------------------------------------------------
# HITL review queue
# ---------------------------------------------------------------------------


def _get_write_client(request: Request):
    """Ontology client for review decisions (writes to the phases graph).

    Carries the SHACL validator so edit-then-approve can re-run the phase
    gate; without one the gate fails closed and edits are rejected.
    """
    from ontology_server.mcp.phase_tools import KGOntologyClient

    state = request.app.state
    return KGOntologyClient(state.kg_store, getattr(state, "validator", None))


def _render_review_detail(
    request: Request,
    idea_id: str,
    phase_id: str,
    *,
    status_code: int = 200,
    violations: list[str] | None = None,
    error: str | None = None,
    submitted: dict[str, str] | None = None,
) -> HTMLResponse:
    service = _get_service(request)
    detail = service.get_review_detail(idea_id, phase_id)
    templates = request.app.state.templates
    if detail is None:
        return templates.TemplateResponse(
            "generic_detail.html",
            {
                "request": request,
                "uri": f"{idea_id}/{phase_id}",
                "triples": [],
            },
            status_code=404,
        )
    if submitted:
        # Re-show the reviewer's (rejected) edits instead of the stored values.
        for field in detail["fields"]:
            if field["name"] in submitted:
                field["display"] = submitted[field["name"]]
    return templates.TemplateResponse(
        "review_detail.html",
        {
            "request": request,
            **detail,
            "violations": violations or [],
            "error": error,
        },
        status_code=status_code,
    )


@router.get("/reviews", response_class=HTMLResponse)
async def review_queue(request: Request) -> HTMLResponse:
    """Render the HITL review queue (pending phase outputs across ideas)."""
    service = _get_service(request)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "reviews.html",
        {"request": request, "reviews": service.list_pending_reviews()},
    )


@router.get("/reviews/{idea_id}/{phase_id}", response_class=HTMLResponse)
async def review_detail(
    request: Request, idea_id: str, phase_id: str,
) -> HTMLResponse:
    """Render the review page for one phase output."""
    return _render_review_detail(request, idea_id, phase_id)


@router.post("/reviews/{idea_id}/{phase_id}/approve")
async def review_approve(request: Request, idea_id: str, phase_id: str):
    """Approve a pending output, applying any field edits first."""
    from ontology_server.phase_approval import (
        ApprovalConflictError,
        approve_phase,
    )

    form = await request.form()
    comment = str(form.get("comment", "")).strip() or None

    # Diff submitted field__<name> values against the stored literals so
    # only genuinely changed fields count as edits.
    service = _get_service(request)
    detail = service.get_review_detail(idea_id, phase_id)
    if detail is None:
        return _render_review_detail(request, idea_id, phase_id)
    stored = {f["name"]: f for f in detail["fields"]}
    submitted: dict[str, str] = {}
    edited_fields: dict[str, str] = {}
    for key, value in form.items():
        if not key.startswith("field__"):
            continue
        name = key[len("field__"):]
        value = str(value)
        submitted[name] = value
        field = stored.get(name)
        if field is None or not field["editable"]:
            continue
        # The textarea shows the pretty-printed form; treat either the raw
        # literal or the pretty form as "unchanged".
        if value.strip() in (field["value"].strip(), field["display"].strip()):
            continue
        edited_fields[name] = value.strip()

    client = _get_write_client(request)
    try:
        result = approve_phase(
            client, client, idea_id, phase_id,
            reviewed_by="dashboard", comment=comment,
            edited_fields=edited_fields or None,
            kg_store=request.app.state.kg_store,
        )
    except (ApprovalConflictError, ValueError) as exc:
        return _render_review_detail(
            request, idea_id, phase_id,
            status_code=422, error=str(exc), submitted=submitted,
        )
    if not result["ok"]:
        return _render_review_detail(
            request, idea_id, phase_id,
            status_code=422, violations=result["violations"],
            submitted=submitted,
        )
    return RedirectResponse(url="/dashboard/reviews", status_code=303)


@router.post("/reviews/{idea_id}/{phase_id}/reject")
async def review_reject(request: Request, idea_id: str, phase_id: str):
    """Reject a pending output with mandatory feedback for the agent re-run."""
    from ontology_server.phase_approval import (
        ApprovalConflictError,
        reject_phase,
    )

    form = await request.form()
    comment = str(form.get("comment", "")).strip()
    if not comment:
        return _render_review_detail(
            request, idea_id, phase_id,
            status_code=422,
            error="A rejection needs a feedback comment — it becomes the "
                  "agent's revision brief.",
        )
    client = _get_write_client(request)
    try:
        reject_phase(
            client, client, idea_id, phase_id, comment,
            reviewed_by="dashboard",
        )
    except (ApprovalConflictError, ValueError) as exc:
        return _render_review_detail(
            request, idea_id, phase_id, status_code=422, error=str(exc),
        )
    return RedirectResponse(url="/dashboard/reviews", status_code=303)


@router.get("/settings/phases", response_class=HTMLResponse)
async def phase_settings(request: Request) -> HTMLResponse:
    """Render the per-phase HITL gate toggles."""
    service = _get_service(request)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "phase_settings.html",
        {"request": request, "phases": service.list_phase_definitions()},
    )


@router.post("/settings/phases/{phase_id}/approval")
async def phase_settings_toggle(request: Request, phase_id: str):
    """Toggle phase:requiresApproval on a phase definition."""
    from ontology_server.phase_approval import set_requires_approval

    form = await request.form()
    required = str(form.get("required", "")).lower() in ("on", "true", "1")
    set_requires_approval(_get_write_client(request), phase_id, required)
    return RedirectResponse(url="/dashboard/settings/phases", status_code=303)


@router.get("/partials/review-rows", response_class=HTMLResponse)
async def partial_review_rows(request: Request) -> HTMLResponse:
    """HTMX partial: refresh the review-queue rows."""
    service = _get_service(request)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "partials/review_rows.html",
        {"request": request, "reviews": service.list_pending_reviews()},
    )


@router.get("/partials/review-badge", response_class=HTMLResponse)
async def partial_review_badge(request: Request) -> HTMLResponse:
    """HTMX partial: pending-review count for the nav badge."""
    service = _get_service(request)
    count = service.count_pending_reviews()
    html_out = (
        f'<span class="review-badge">{count}</span>' if count else ""
    )
    return HTMLResponse(html_out)


# ---------------------------------------------------------------------------
# In-place editing (ideas, facts) + change history
# ---------------------------------------------------------------------------

# Input widget per editable idea field (field set = EDITABLE_IDEA_FIELDS).
_IDEA_FIELD_INPUTS: dict[str, dict] = {
    "title": {"multiline": False},
    "description": {"multiline": True},
    "content": {"multiline": True, "pre": True},
    "vision": {"multiline": True},
    "priority": {"multiline": False},
    "tags": {"multiline": False, "hint": "comma-separated"},
    "requirements": {"multiline": True, "hint": "one per line"},
    "considerations": {"multiline": True, "hint": "one per line"},
    "use_cases": {"multiline": True, "hint": "one per line"},
}


def _idea_field_raw(idea, field: str) -> str:
    """The raw editable string form of an idea field."""
    value = getattr(idea, field)
    if field == "tags":
        return ", ".join(value)
    if field in ("requirements", "considerations", "use_cases"):
        return "\n".join(value)
    if value is None:
        return ""
    return str(value)


def _render_idea_field(
    request: Request, idea_id: str, field: str, template: str,
    status_code: int = 200, error: str | None = None,
    headers: dict | None = None,
) -> HTMLResponse:
    ideas_store = request.app.state.ideas_store
    idea = ideas_store.get_idea(idea_id)
    templates = request.app.state.templates
    if idea is None or field not in _IDEA_FIELD_INPUTS:
        return HTMLResponse("not found", status_code=404)
    return templates.TemplateResponse(
        template,
        {
            "request": request,
            "idea_id": idea_id,
            "field": field,
            "value": _idea_field_raw(idea, field),
            "widget": _IDEA_FIELD_INPUTS[field],
            "error": error,
        },
        status_code=status_code,
        headers=headers,
    )


@router.get("/ideas/{idea_id}/field/{field}", response_class=HTMLResponse)
async def idea_field_display(
    request: Request, idea_id: str, field: str,
) -> HTMLResponse:
    """HTMX partial: display view of one idea field (also 'cancel')."""
    return _render_idea_field(request, idea_id, field, "partials/idea_field.html")


@router.get("/ideas/{idea_id}/edit/{field}", response_class=HTMLResponse)
async def idea_field_edit_form(
    request: Request, idea_id: str, field: str,
) -> HTMLResponse:
    """HTMX partial: edit form for one idea field."""
    return _render_idea_field(
        request, idea_id, field, "partials/idea_field_form.html",
    )


@router.post("/ideas/{idea_id}/edit/{field}", response_class=HTMLResponse)
async def idea_field_edit(
    request: Request, idea_id: str, field: str,
) -> HTMLResponse:
    """Save one idea field; returns the refreshed display partial."""
    form = await request.form()
    value = str(form.get("value", ""))
    ideas_store = request.app.state.ideas_store
    try:
        ideas_store.update_idea_fields(
            idea_id, {field: value}, changed_by="dashboard",
        )
    except ValueError as exc:
        return _render_idea_field(
            request, idea_id, field, "partials/idea_field_form.html",
            status_code=422, error=str(exc),
        )
    # HX-Trigger lets the page's history section refresh itself.
    return _render_idea_field(
        request, idea_id, field, "partials/idea_field.html",
        headers={"HX-Trigger": "entity-edited"},
    )


def _render_fact_row(
    request: Request, fact_id: str, context: str,
    template: str = "partials/fact_row.html",
    status_code: int = 200, error: str | None = None,
    headers: dict | None = None,
) -> HTMLResponse:
    fact = request.app.state.agent_memory.get_fact(fact_id)
    if fact is None:
        return HTMLResponse("not found", status_code=404)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        template,
        {"request": request, "fact": fact, "context": context, "error": error},
        status_code=status_code,
        headers=headers,
    )


@router.get("/partials/fact-row/{fact_id}", response_class=HTMLResponse)
async def partial_fact_row(
    request: Request, fact_id: str, context: str = "",
) -> HTMLResponse:
    """HTMX partial: display row for one fact (also 'cancel')."""
    return _render_fact_row(request, fact_id, context)


@router.get("/partials/fact-edit/{fact_id}", response_class=HTMLResponse)
async def partial_fact_edit(
    request: Request, fact_id: str, context: str = "",
) -> HTMLResponse:
    """HTMX partial: edit row for one fact."""
    return _render_fact_row(
        request, fact_id, context, template="partials/fact_edit_row.html",
    )


@router.post("/facts-edit/{fact_id}", response_class=HTMLResponse)
async def fact_edit_save(
    request: Request, fact_id: str, context: str = "",
) -> HTMLResponse:
    """Save an in-place fact edit; returns the refreshed display row."""
    form = await request.form()
    new_object = str(form.get("object", ""))
    confidence_raw = str(form.get("confidence", "")).strip()
    try:
        new_confidence = float(confidence_raw) if confidence_raw else None
        request.app.state.agent_memory.update_fact(
            fact_id,
            new_object=new_object,
            new_confidence=new_confidence,
            changed_by="dashboard",
        )
    except ValueError as exc:
        return _render_fact_row(
            request, fact_id, context,
            template="partials/fact_edit_row.html",
            status_code=422, error=str(exc),
        )
    return _render_fact_row(
        request, fact_id, context, headers={"HX-Trigger": "entity-edited"},
    )


@router.get("/phases/{idea_id}/{phase_id}/edit", response_class=HTMLResponse)
async def phase_edit(
    request: Request, idea_id: str, phase_id: str,
) -> HTMLResponse:
    """Full-page field editor for a phase output at ANY approval status."""
    return _render_phase_edit(request, idea_id, phase_id)


def _render_phase_edit(
    request: Request, idea_id: str, phase_id: str,
    *, status_code: int = 200, violations: list[str] | None = None,
    error: str | None = None, submitted: dict[str, str] | None = None,
    saved_fields: list[str] | None = None, stale_phases: list[str] | None = None,
) -> HTMLResponse:
    from ontology_server.phase_approval import consumers_of_fields

    service = _get_service(request)
    detail = service.get_review_detail(idea_id, phase_id)
    templates = request.app.state.templates
    if detail is None:
        return HTMLResponse("phase output not found", status_code=404)
    if submitted:
        for field in detail["fields"]:
            if field["name"] in submitted:
                field["display"] = submitted[field["name"]]
    consumers = consumers_of_fields([f["name"] for f in detail["fields"]])
    return templates.TemplateResponse(
        "phase_edit.html",
        {
            "request": request,
            **detail,
            "consumers": consumers,
            "violations": violations or [],
            "error": error,
            "saved_fields": saved_fields or [],
            "stale_phases": stale_phases or [],
        },
        status_code=status_code,
    )


@router.post("/phases/{idea_id}/{phase_id}/edit")
async def phase_edit_save(request: Request, idea_id: str, phase_id: str):
    """Apply phase-output field edits (SHACL-revalidated, change-logged)."""
    from ontology_server.phase_approval import (
        ApprovalConflictError,
        edit_phase_output,
    )

    form = await request.form()
    reason = str(form.get("reason", "")).strip() or None

    service = _get_service(request)
    detail = service.get_review_detail(idea_id, phase_id)
    if detail is None:
        return HTMLResponse("phase output not found", status_code=404)
    stored = {f["name"]: f for f in detail["fields"]}
    submitted: dict[str, str] = {}
    edited_fields: dict[str, str] = {}
    for key, value in form.items():
        if not key.startswith("field__"):
            continue
        name = key[len("field__"):]
        value = str(value)
        submitted[name] = value
        field = stored.get(name)
        if field is None or not field["editable"]:
            continue
        if value.strip() in (field["value"].strip(), field["display"].strip()):
            continue
        edited_fields[name] = value.strip()

    if not edited_fields:
        return _render_phase_edit(
            request, idea_id, phase_id, error="No fields were changed.",
        )

    client = _get_write_client(request)
    try:
        result = edit_phase_output(
            client, client, idea_id, phase_id, edited_fields,
            kg_store=request.app.state.kg_store,
            changed_by="dashboard", reason=reason,
        )
    except (ApprovalConflictError, ValueError) as exc:
        return _render_phase_edit(
            request, idea_id, phase_id,
            status_code=422, error=str(exc), submitted=submitted,
        )
    if not result["ok"]:
        return _render_phase_edit(
            request, idea_id, phase_id,
            status_code=422, violations=result["violations"],
            submitted=submitted,
        )
    return _render_phase_edit(
        request, idea_id, phase_id,
        saved_fields=result["edited_fields"],
        stale_phases=result["stale_phases"],
    )


@router.get("/partials/history", response_class=HTMLResponse)
async def partial_history(request: Request) -> HTMLResponse:
    """HTMX partial: change history for one or more target URIs.

    Query params: repeated `target=<uri>`, optional `limit`.
    """
    from knowledge_graph.core.changelog import get_history_for_targets

    targets = request.query_params.getlist("target")
    limit = int(request.query_params.get("limit", "10"))
    rows = get_history_for_targets(
        request.app.state.kg_store, targets, limit=limit,
    ) if targets else []
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "partials/history_section.html",
        {"request": request, "history": rows, "targets": targets},
    )


@router.get("/changes", response_class=HTMLResponse)
async def changes_feed(
    request: Request, entity_kind: str | None = None,
) -> HTMLResponse:
    """Global human-edit changelog feed."""
    from knowledge_graph.core.changelog import recent_changes

    rows = recent_changes(
        request.app.state.kg_store, limit=100, entity_kind=entity_kind,
    )
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "changes.html",
        {"request": request, "changes": rows, "entity_kind": entity_kind},
    )


@router.get("/partials/change-rows", response_class=HTMLResponse)
async def partial_change_rows(
    request: Request, entity_kind: str | None = None,
) -> HTMLResponse:
    """HTMX partial: refresh the global changes feed rows."""
    from knowledge_graph.core.changelog import recent_changes

    rows = recent_changes(
        request.app.state.kg_store, limit=100, entity_kind=entity_kind,
    )
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "partials/change_rows.html",
        {"request": request, "changes": rows},
    )


# ---------------------------------------------------------------------------
# Authentication (cookie session for browser access)
# ---------------------------------------------------------------------------


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str | None = None) -> HTMLResponse:
    """Render the login form."""
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": error},
    )


@router.post("/login")
async def login_submit(request: Request, api_key: str = Form(...)):
    """Validate the API key and set a session cookie."""
    verifier = getattr(request.app.state, "token_verifier", None)
    if verifier is None:
        # Auth not enabled on parent app — shouldn't reach here
        return RedirectResponse(url="/dashboard/", status_code=302)

    access_token = await verifier.verify_token(api_key)
    if access_token is None:
        templates = request.app.state.templates
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid API key"},
            status_code=401,
        )

    cookie_value = request.app.state.session_cookie_value
    response = RedirectResponse(url="/dashboard/", status_code=302)
    response.set_cookie(
        key="dashboard_session",
        value=cookie_value,
        httponly=True,
        samesite="lax",
        path="/dashboard",
    )
    return response


@router.post("/logout")
async def logout(request: Request):
    """Clear the session cookie."""
    response = RedirectResponse(url="/dashboard/login", status_code=302)
    response.delete_cookie(key="dashboard_session", path="/dashboard")
    return response
