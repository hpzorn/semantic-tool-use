"""Server-side MCP bootstrap for the phase-tool surface.

Provides :func:`create_mcp_server` — the entry point the ontology-server
process calls at start-up — and :func:`register_phase_tools`, which binds
every phase-tool callable in :mod:`mcp.phase_tools` to the MCP server
instance under its public tool name.

The module is intentionally substrate-neutral.  An ``mcp`` object is
duck-typed: any object exposing either a ``tool()`` decorator (FastMCP /
``mcp`` library style) or an ``add_tool(name, fn)`` method satisfies the
contract.  This mirrors the equivalent duck typing used by
:func:`api.routes.phases.register` so a single binary can host both
surfaces without pulling in either an MCP-server framework or a web
framework as a hard dependency.

Quality focus: isaqb:Operability — the registration step is a pure
function call with no side effects beyond the tool list of the MCP
server instance, so a restart that bypasses it would be observable
immediately via ``list_tools``.

Architecture decisions: arch:adr-73-1 (single source of truth — phase
tool callables live in ``mcp.phase_tools``; this module only wires).
"""

from __future__ import annotations

from typing import Any, Callable, Protocol

from mcp.phase_tools import (
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


# Canonical tool name → callable factory.  The factory binds the *sparql*
# client into a single-argument (or kwargs-only) callable so the MCP
# framework can introspect the signature without leaking the SPARQL
# transport into the tool surface.  Order is the canonical pipeline
# ordering — list_tools therefore yields a deterministic enumeration.
def _tool_factories(
    sparql: SparqlClient,
) -> list[tuple[str, Callable[..., Any]]]:
    return [
        (
            "collect_upstream_facts",
            lambda idea_id: collect_upstream_facts(sparql, idea_id),
        ),
        (
            "render_methodology",
            lambda phase_id: render_methodology(sparql, phase_id),
        ),
        (
            "render_tools",
            lambda phase_id: render_tools(sparql, phase_id),
        ),
        (
            "render_gates",
            lambda phase_id: render_gates(sparql, phase_id),
        ),
        (
            "render_input_contract",
            lambda phase_id: render_input_contract(sparql, phase_id),
        ),
        (
            "render_output_contract",
            lambda phase_id: render_output_contract(sparql, phase_id),
        ),
        (
            "render_phase_prompt",
            lambda phase_id: render_phase_prompt(sparql, phase_id),
        ),
        (
            "list_pipeline",
            lambda agent_family: list_pipeline(sparql, agent_family),
        ),
        (
            "next_phase",
            lambda agent_family, current_id, verdict: next_phase(
                sparql, agent_family, current_id, verdict,
            ),
        ),
        (
            "record_phase_result",
            lambda phase_id, idea_id, artifact_path, result_json,
            predecessor_phase_id=None: record_phase_result(
                sparql,
                phase_id,
                idea_id,
                artifact_path,
                result_json,
                predecessor_phase_id,
            ),
        ),
    ]


class _McpLike(Protocol):
    """Minimal MCP server contract — see module docstring."""

    def tool(
        self, *args: Any, **kwargs: Any,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]: ...


def register_phase_tools(mcp: Any, sparql: SparqlClient) -> list[str]:
    """Register every phase tool on *mcp* and return their tool names.

    Idempotent in the sense that calling it twice on the same *mcp*
    instance binds each name twice — frameworks that disallow this raise
    on the second call, which is the desired loud failure mode for an
    accidental double-mount.  The returned list mirrors the canonical
    ordering of :func:`_tool_factories` so callers can assert against
    ``list_tools`` deterministically.

    Two registration styles are supported:

    * ``mcp.tool(name=...)`` decorator (FastMCP / ``mcp`` library).
    * ``mcp.add_tool(name, fn)`` direct binding (lighter wrappers used
      in tests and embedded deployments).
    """
    names: list[str] = []
    has_decorator = hasattr(mcp, "tool")
    has_add_tool = hasattr(mcp, "add_tool")
    if not has_decorator and not has_add_tool:
        raise TypeError(
            "register_phase_tools requires an mcp with .tool() or "
            f".add_tool(); got {type(mcp).__name__}",
        )

    for name, fn in _tool_factories(sparql):
        if has_decorator:
            mcp.tool(name=name)(fn)
        else:
            mcp.add_tool(name, fn)
        names.append(name)
    return names


def create_mcp_server(
    sparql: SparqlClient,
    *,
    mcp_factory: Callable[[], Any] | None = None,
) -> Any:
    """Create and return an MCP server with the phase tools registered.

    *mcp_factory* is the framework-specific constructor (e.g.
    ``lambda: FastMCP("tulla-phase-tools")``).  When omitted, a minimal
    in-process registry is used — this keeps the unit tests substrate-
    neutral while the production deployment can pass in a real factory.

    The function performs the exact wiring step prescribed by req-130-2-11:
    ``register_phase_tools(mcp, sparql)`` is called once during server
    construction so that ``list_tools`` on the returned instance shows
    every phase tool.
    """
    mcp = mcp_factory() if mcp_factory is not None else _InMemoryMcp()
    register_phase_tools(mcp, sparql)
    return mcp


class _InMemoryMcp:
    """Minimal MCP-like registry for embedded deployments and tests.

    Exposes both registration styles supported by
    :func:`register_phase_tools` so the wiring can be exercised without
    a real MCP framework.  ``list_tools`` returns the registered names
    in insertion order — the same ordering :func:`register_phase_tools`
    returns, which is the contract the verification criterion checks.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., Any]] = {}

    def add_tool(self, name: str, fn: Callable[..., Any]) -> None:
        self._tools[name] = fn

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def call_tool(self, name: str, /, *args: Any, **kwargs: Any) -> Any:
        return self._tools[name](*args, **kwargs)
