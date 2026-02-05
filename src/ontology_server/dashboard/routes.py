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
- ``GET /facts``                         — facts browser landing
- ``GET /facts/{context}``               — facts for a context
- ``GET /prds``                          — PRD context list
- ``GET /prds/{context}``                — PRD requirement graph
- ``GET /prds/{context}/{subject:path}`` — single requirement detail
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

    return templates.TemplateResponse(
        "idea_detail.html",
        {"request": request, "prd_progress": prd_progress, "contexts": contexts, **detail},
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

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "prd_detail.html",
        {
            "request": request,
            "context": context,
            "requirements": requirements,
            "phases": phases,
        },
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

    detail = {
        "subject": raw.get("subject", subject),
        "context": context,
        "found": found,
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
        "idea_detail": lambda p: f"/ideas/{p['idea_id']}",
        "requirement_detail": lambda p: f"/prds/{p['context']}/{p['subject']}",
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
