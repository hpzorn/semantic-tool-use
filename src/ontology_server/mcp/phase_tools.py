"""Phase pipeline MCP tools.

Contains the 10 core phase-pipeline functions (ported from
``wip-from-claude-tulla/mcp/phase_tools.py``), adapter classes that
bridge the ``KnowledgeGraphStore`` to the ``SparqlClient`` /
``OntologyClient`` protocols, and the ``register_phase_tools`` entry
point used by ``mcp/server.py``.

Architecture decisions: arch:adr-73-1, arch:adr-73-5, arch:adr-130-7
Quality focus: isaqb:FunctionalCorrectness
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
    from knowledge_graph.core.store import KnowledgeGraphStore
    from ontology_server.core.validation import SHACLValidator

logger = logging.getLogger(__name__)


class PipelineDataError(RuntimeError):
    """Raised when ontology data required for phase dispatch cannot be loaded."""


# ---------------------------------------------------------------------------
# Namespace constants  (imported from shared module — do NOT redefine here)
# ---------------------------------------------------------------------------

from ontology_server.phase_constants import (  # noqa: E402
    PHASE_NS,
    TRACE_NS,
    PHASES_GRAPH,
    _PRESERVES_PREFIX,
    APPROVAL_STATUS_PRED,
    RECORDED_AT_PRED,
    REQUIRES_APPROVAL_PRED,
    APPROVAL_PENDING,
    APPROVAL_APPROVED,
)

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


# ---------------------------------------------------------------------------
# Protocol definitions
# ---------------------------------------------------------------------------


class SparqlClient(Protocol):
    """Minimal contract for the SPARQL backend the server passes in."""

    def sparql_query(self, query: str) -> dict[str, Any]:  # pragma: no cover
        ...


class OntologyClient(Protocol):
    """Extended contract for record_phase_result."""

    def sparql_query(self, query: str) -> dict[str, Any]:  # pragma: no cover
        ...

    def add_triple(  # pragma: no cover
        self,
        subject: str,
        predicate: str,
        object: str,
        *,
        is_literal: bool = False,
    ) -> Any:
        ...

    def remove_triples_by_subject(  # pragma: no cover
        self,
        subject: str,
    ) -> int:
        ...

    def remove_triples(  # pragma: no cover
        self,
        subject: str,
        predicate: str,
    ) -> int:
        ...

    def validate_instance(  # pragma: no cover
        self,
        instance_uri: str,
        shape_uri: str,
    ) -> dict[str, Any]:
        ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sparql_escape_literal(value: str) -> str:
    """Escape *value* for safe embedding inside a SPARQL ``"..."`` literal.

    Prevents injection through idea-ids or phase-ids that contain quote or
    backslash characters.  All internal callers pass only validated
    application-controlled strings; this guard handles edge-cases.
    """
    value = value.replace("\\", "\\\\")
    value = value.replace('"', '\\"')
    value = value.replace("\n", "\\n")
    value = value.replace("\r", "\\r")
    return value


def _try_coerce(value: str) -> Any:
    """Coerce a string value to int, float, bool, JSON, or keep as str."""
    try:
        return int(value)
    except (ValueError, TypeError):
        pass

    try:
        return float(value)
    except (ValueError, TypeError):
        pass

    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"

    try:
        parsed = json.loads(value)
        if isinstance(parsed, (list, dict)):
            return parsed
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    return value


def _build_query(idea_id: str) -> str:
    return (
        f"SELECT ?s ?p ?o WHERE {{\n"
        f"  GRAPH <{PHASES_GRAPH}> {{\n"
        f'    ?s <{PHASE_NS}forRequirement> "{_sparql_escape_literal(idea_id)}" .\n'
        f"    ?s ?p ?o .\n"
        f"  }}\n"
        f"}}"
    )


# ---------------------------------------------------------------------------
# collect_upstream_facts
# ---------------------------------------------------------------------------


def collect_upstream_facts(
    sparql: SparqlClient,
    idea_id: str | None,
    consuming_phase_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Collect and group all phase facts for *idea_id* in one call.

    Pass consuming_phase_id to filter results to only the fields the
    consuming phase declared it needs (reduces context size).
    """
    if not idea_id:
        return {}
    if not idea_id.startswith("idea-"):
        idea_id = f"idea-{idea_id}"

    query = _build_query(idea_id)

    try:
        result = sparql.sparql_query(query)
    except Exception as exc:
        raise PipelineDataError(f"collect_upstream_facts: {exc}") from exc

    bindings = result.get("results", [])
    grouped: dict[str, dict[str, Any]] = {}
    subject_prefix = f"{PHASE_NS}{idea_id}-"

    for binding in bindings:
        predicate = binding.get("p", "")
        if not predicate.startswith(_PRESERVES_PREFIX):
            continue

        subject = binding.get("s", "")
        if not subject.startswith(subject_prefix):
            continue
        phase_id = subject[len(subject_prefix):]
        if not phase_id:
            continue

        field_name = predicate[len(_PRESERVES_PREFIX):]
        raw_value = binding.get("o", "")
        typed_value = _try_coerce(raw_value)

        bucket = grouped.setdefault(phase_id, {})
        bucket[field_name] = typed_value

    if consuming_phase_id is not None:
        try:
            from ontology_server.phase_predicate_names import PHASE_CONSUMED_FIELDS
            needed = PHASE_CONSUMED_FIELDS.get(consuming_phase_id)
        except ImportError:
            needed = None
        if needed:
            filtered = {
                phase_id: {k: v for k, v in fields.items() if k in needed}
                for phase_id, fields in grouped.items()
                if any(k in needed for k in fields)
            }
            if filtered:
                grouped = filtered
            else:
                logger.warning(
                    "consuming_phase_id=%r consumed-field set matched no stored "
                    "fields for idea %s; returning unfiltered facts",
                    consuming_phase_id,
                    idea_id,
                )

    return grouped


def get_phase_fact(
    sparql: SparqlClient,
    idea_id: str,
    phase_id: str,
    field: str,
) -> dict[str, Any]:
    """Fetch ONE preserved field's full value (targeted drill-down).

    The cheap escape hatch for agents whose collect_upstream_facts call was
    filtered by consuming_phase_id: reach any specific upstream field
    without re-pulling the full multi-phase dump.
    """
    if not idea_id or not phase_id or not field:
        raise ValueError("idea_id, phase_id and field are required")
    if not idea_id.startswith("idea-"):
        idea_id = f"idea-{idea_id}"
    subject = f"{PHASE_NS}{idea_id}-{phase_id}"
    predicate = f"{_PRESERVES_PREFIX}{field}"
    query = (
        f"SELECT ?o WHERE {{\n"
        f"  GRAPH <{PHASES_GRAPH}> {{ <{subject}> <{predicate}> ?o . }}\n"
        f"}}\n"
        f"LIMIT 1"
    )
    try:
        result = sparql.sparql_query(query)
    except Exception as exc:
        raise PipelineDataError(f"get_phase_fact: {exc}") from exc
    bindings = result.get("results", []) if isinstance(result, dict) else []
    if not bindings:
        return {
            "idea_id": idea_id, "phase_id": phase_id, "field": field,
            "found": False, "value": None,
        }
    return {
        "idea_id": idea_id, "phase_id": phase_id, "field": field,
        "found": True, "value": _try_coerce(str(bindings[0].get("o", ""))),
    }


# ---------------------------------------------------------------------------
# render_methodology (req-130-2-2)
# ---------------------------------------------------------------------------


def _build_methodology_query(phase_id: str) -> str:
    return (
        f"SELECT ?proc WHERE {{\n"
        f"  GRAPH <{PHASES_GRAPH}> {{\n"
        f"    <{PHASE_NS}{phase_id}> <{PHASE_NS}procedure> ?proc .\n"
        f"  }}\n"
        f"}}"
    )


def render_methodology(sparql: SparqlClient, phase_id: str) -> str:
    """Return the markdown body of phase:procedure for *phase_id*."""
    if not phase_id:
        raise ValueError("phase_id is required")

    query = _build_methodology_query(phase_id)

    try:
        result = sparql.sparql_query(query)
    except Exception as exc:
        raise PipelineDataError(f"render_methodology: {exc}") from exc

    bindings = result.get("results", [])
    if not bindings:
        logger.warning(
            "No phase:procedure literal for phase_id=%r in graph %s",
            phase_id,
            PHASES_GRAPH,
        )
        return ""

    return str(bindings[0].get("proc", ""))


# ---------------------------------------------------------------------------
# render_tools (req-130-2-3)
# ---------------------------------------------------------------------------


_MCP_PREFIX = "mcp__"


def _build_tools_query(phase_id: str) -> str:
    return (
        f"SELECT ?val WHERE {{\n"
        f"  GRAPH <{PHASES_GRAPH}> {{\n"
        f"    {{ <{PHASE_NS}{phase_id}> <{PHASE_NS}requiresTool> ?val . }}\n"
        f"    UNION\n"
        f"    {{ <{PHASE_NS}{phase_id}> <{PHASE_NS}requiresMcp> ?val . }}\n"
        f"  }}\n"
        f"}}"
    )


def _format_tools_markdown(values: list[str]) -> str:
    tools: set[str] = set()
    mcps: set[str] = set()
    for raw in values:
        if not raw:
            continue
        if raw.startswith(_MCP_PREFIX):
            mcps.add(raw)
        else:
            tools.add(raw)

    lines: list[str] = ["## Tools", ""]
    for name in sorted(tools):
        lines.append(f"- {name}")
    lines.extend(["", "## MCP Tools", ""])
    for name in sorted(mcps):
        lines.append(f"- {name}")
    return "\n".join(lines)


def render_tools(sparql: SparqlClient, phase_id: str) -> str:
    """Return the markdown two-section tool list for *phase_id*."""
    if not phase_id:
        raise ValueError("phase_id is required")

    query = _build_tools_query(phase_id)

    try:
        result = sparql.sparql_query(query)
    except Exception as exc:
        raise PipelineDataError(f"render_tools: {exc}") from exc

    bindings = result.get("results", []) if isinstance(result, dict) else []
    values = [str(b.get("val", "")) for b in bindings]
    return _format_tools_markdown(values)


# ---------------------------------------------------------------------------
# render_gates (req-130-2-4)
# ---------------------------------------------------------------------------


def _build_gates_query(phase_id: str) -> str:
    return (
        f"SELECT ?shape ?label WHERE {{\n"
        f"  GRAPH <{PHASES_GRAPH}> {{\n"
        f"    <{PHASE_NS}{phase_id}> <{PHASE_NS}shaclGate> ?shape .\n"
        f"    OPTIONAL {{ ?shape <http://www.w3.org/2000/01/rdf-schema#label> ?label }}\n"
        f"  }}\n"
        f"}}"
    )


def _abbreviate_shape_uri(uri: str) -> str:
    if uri.startswith(PHASE_NS):
        return f"phase:{uri[len(PHASE_NS):]}"
    return uri


def _format_gates_markdown(rows: list[tuple[str, str]]) -> str:
    seen: dict[str, str] = {}
    for shape_uri, label in rows:
        if not shape_uri:
            continue
        if shape_uri not in seen or (not seen[shape_uri] and label):
            seen[shape_uri] = label
    lines: list[str] = []
    for shape_uri in sorted(seen.keys()):
        abbr = _abbreviate_shape_uri(shape_uri)
        label_part = f" — {seen[shape_uri]}" if seen[shape_uri] else ""
        lines.append(f"SHACL Gate: {abbr}{label_part}")
    return "\n".join(lines)


def render_gates(sparql: SparqlClient, phase_id: str) -> str:
    """Return the markdown gate list for *phase_id*."""
    if not phase_id:
        raise ValueError("phase_id is required")

    query = _build_gates_query(phase_id)

    try:
        result = sparql.sparql_query(query)
    except Exception as exc:
        raise PipelineDataError(f"render_gates: {exc}") from exc

    bindings = result.get("results", []) if isinstance(result, dict) else []
    rows: list[tuple[str, str]] = []
    for binding in bindings:
        shape_uri = binding.get("shape") or ""
        label = binding.get("label") or ""
        rows.append((shape_uri, label))
    return _format_gates_markdown(rows)


# ---------------------------------------------------------------------------
# render_input_contract (req-130-2-5)
# ---------------------------------------------------------------------------


def _build_input_contract_query(phase_id: str) -> str:
    return (
        f"SELECT ?field ?type ?desc WHERE {{\n"
        f"  GRAPH <{PHASES_GRAPH}> {{\n"
        f"    <{PHASE_NS}{phase_id}> <{PHASE_NS}inputContract> ?c .\n"
        f"    ?c <{PHASE_NS}requiresField> ?field ;\n"
        f"       <{PHASE_NS}fieldType> ?type .\n"
        f"    OPTIONAL {{ ?c <{PHASE_NS}fieldDescription> ?desc }}\n"
        f"  }}\n"
        f"}}"
    )


def _format_input_contract_markdown(rows: list[tuple[str, str, str]]) -> str:
    seen: dict[str, tuple[str, str]] = {}
    for field, ftype, fdesc in rows:
        if not field:
            continue
        cur = seen.get(field)
        if cur is None:
            seen[field] = (ftype, fdesc)
        else:
            cur_type, cur_desc = cur
            seen[field] = (cur_type or ftype, cur_desc or fdesc)

    if not seen:
        return ""

    lines: list[str] = [
        "| Field | Type | Description |",
        "|-------|------|-------------|",
    ]
    for field in sorted(seen.keys()):
        ftype, fdesc = seen[field]
        lines.append(f"| {field} | {ftype} | {fdesc} |")
    return "\n".join(lines)


def render_input_contract(sparql: SparqlClient, phase_id: str) -> str:
    """Return the markdown input contract table for *phase_id*."""
    if not phase_id:
        raise ValueError("phase_id is required")

    query = _build_input_contract_query(phase_id)

    try:
        result = sparql.sparql_query(query)
    except Exception as exc:
        raise PipelineDataError(f"render_input_contract: {exc}") from exc

    bindings = result.get("results", []) if isinstance(result, dict) else []
    rows: list[tuple[str, str, str]] = []
    for binding in bindings:
        field = str(binding.get("field") or "")
        ftype = str(binding.get("type") or "")
        fdesc = str(binding.get("desc") or "")
        rows.append((field, ftype, fdesc))
    return _format_input_contract_markdown(rows)


# ---------------------------------------------------------------------------
# render_output_contract (req-130-2-6)
# ---------------------------------------------------------------------------


def _build_output_contract_query(phase_id: str) -> str:
    return (
        f"SELECT ?field ?type ?desc ?intent WHERE {{\n"
        f"  GRAPH <{PHASES_GRAPH}> {{\n"
        f"    {{\n"
        f"      <{PHASE_NS}{phase_id}> <{PHASE_NS}outputContract> ?c .\n"
        f"      ?c <{PHASE_NS}requiresField> ?field ;\n"
        f"         <{PHASE_NS}fieldType> ?type .\n"
        f"      OPTIONAL {{ ?c <{PHASE_NS}fieldDescription> ?desc }}\n"
        f"    }}\n"
        f"    UNION\n"
        f"    {{ <{PHASE_NS}{phase_id}> <{PHASE_NS}emitsIntentField> ?intent . }}\n"
        f"  }}\n"
        f"}}"
    )


def _format_output_contract_markdown(
    rows: list[tuple[str, str, str]],
    intent_fields: list[str],
) -> str:
    seen_rows: dict[str, tuple[str, str]] = {}
    for field, ftype, fdesc in rows:
        if not field:
            continue
        cur = seen_rows.get(field)
        if cur is None:
            seen_rows[field] = (ftype, fdesc)
        else:
            cur_type, cur_desc = cur
            seen_rows[field] = (cur_type or ftype, cur_desc or fdesc)

    deduped_intents: list[str] = []
    seen_intents: set[str] = set()
    for name in intent_fields:
        if not name or name in seen_intents:
            continue
        seen_intents.add(name)
        deduped_intents.append(name)

    if not seen_rows and not deduped_intents:
        return ""

    sections: list[str] = []
    if seen_rows:
        lines = [
            "| Field | Type | Description |",
            "|-------|------|-------------|",
        ]
        for field in sorted(seen_rows.keys()):
            ftype, fdesc = seen_rows[field]
            lines.append(f"| {field} | {ftype} | {fdesc} |")
        sections.append("\n".join(lines))

    if deduped_intents:
        block = ["## Emits Intent Fields", ""]
        for name in deduped_intents:
            block.append(f"- {name}")
        sections.append("\n".join(block))

    return "\n\n".join(sections)


def render_output_contract(sparql: SparqlClient, phase_id: str) -> str:
    """Return the markdown output contract for *phase_id*."""
    if not phase_id:
        raise ValueError("phase_id is required")

    query = _build_output_contract_query(phase_id)

    try:
        result = sparql.sparql_query(query)
    except Exception as exc:
        raise PipelineDataError(f"render_output_contract: {exc}") from exc

    bindings = result.get("results", []) if isinstance(result, dict) else []
    rows: list[tuple[str, str, str]] = []
    intent_fields: list[str] = []
    for binding in bindings:
        field = str(binding.get("field") or "")
        intent = str(binding.get("intent") or "")
        if field:
            rows.append(
                (
                    field,
                    str(binding.get("type") or ""),
                    str(binding.get("desc") or ""),
                )
            )
        elif intent:
            intent_fields.append(intent)
    return _format_output_contract_markdown(rows, intent_fields)


# ---------------------------------------------------------------------------
# render_phase_prompt (req-130-2-7)
# ---------------------------------------------------------------------------


PHASE_PROMPT_SECTIONS: tuple[tuple[str, str], ...] = (
    ("Methodology", "render_methodology"),
    ("Tools", "render_tools"),
    ("Gates", "render_gates"),
    ("Input Contract", "render_input_contract"),
    ("Output Contract", "render_output_contract"),
)


def render_phase_prompt(sparql: SparqlClient, phase_id: str) -> str:
    """Return the composed initial-seed prompt body for *phase_id*."""
    if not phase_id:
        raise ValueError("phase_id is required")

    renderers = {
        "render_methodology": render_methodology,
        "render_tools": render_tools,
        "render_gates": render_gates,
        "render_input_contract": render_input_contract,
        "render_output_contract": render_output_contract,
    }

    sections: list[str] = []
    for header, renderer_name in PHASE_PROMPT_SECTIONS:
        body = renderers[renderer_name](sparql, phase_id)
        if renderer_name == "render_tools":
            # render_tools already includes its own ## Tools / ## MCP Tools headers
            sections.append(body)
        else:
            sections.append(f"## {header}\n\n{body}")
    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# list_pipeline (req-130-2-8)
# ---------------------------------------------------------------------------


def _build_list_pipeline_query(agent_family: str) -> str:
    return (
        f"SELECT ?phaseId (COUNT(?ancestor) AS ?depth) WHERE {{\n"
        f"  GRAPH <{PHASES_GRAPH}> {{\n"
        f'    ?phase <{PHASE_NS}agentFamily> "{agent_family}" ;\n'
        f"           <{PHASE_NS}phaseId> ?phaseId .\n"
        f"    OPTIONAL {{\n"
        f"      ?phase <{PHASE_NS}upstreamPhase>+ ?ancestor .\n"
        f'      ?ancestor <{PHASE_NS}agentFamily> "{agent_family}" .\n'
        f"    }}\n"
        f"  }}\n"
        f"}}\n"
        f"GROUP BY ?phaseId\n"
        f"ORDER BY ?depth ?phaseId"
    )


def list_pipeline(sparql: SparqlClient, agent_family: str) -> list[str]:
    """Return the ordered phase_id list for *agent_family*."""
    if not agent_family:
        raise ValueError("agent_family is required")

    query = _build_list_pipeline_query(agent_family)

    try:
        result = sparql.sparql_query(query)
    except Exception as exc:
        raise PipelineDataError(f"list_pipeline: {exc}") from exc

    bindings = result.get("results", []) if isinstance(result, dict) else []
    pipeline: list[str] = []
    for binding in bindings:
        phase_id = binding.get("phaseId") or ""
        if phase_id:
            pipeline.append(phase_id)
    return pipeline


# ---------------------------------------------------------------------------
# next_phase (req-130-2-9)
# ---------------------------------------------------------------------------


TERMINATE = "terminate"


def _build_next_phase_query(agent_family: str, current_id: str) -> str:
    return (
        f"SELECT ?phaseId ?verdict WHERE {{\n"
        f"  GRAPH <{PHASES_GRAPH}> {{\n"
        f'    ?current <{PHASE_NS}phaseId> "{current_id}" ;\n'
        f'             <{PHASE_NS}agentFamily> "{agent_family}" .\n'
        f"    ?next <{PHASE_NS}upstreamPhase> ?current ;\n"
        f'          <{PHASE_NS}agentFamily> "{agent_family}" ;\n'
        f"          <{PHASE_NS}phaseId> ?phaseId .\n"
        f"    OPTIONAL {{ ?next <{PHASE_NS}verdictBranch> ?verdict }}\n"
        f"  }}\n"
        f"}}"
    )


def next_phase(
    sparql: SparqlClient,
    agent_family: str,
    current_id: str,
    verdict: str,
) -> dict[str, str]:
    """Return {\"next_id\": phase_id | \"terminate\"} for *current_id*."""
    if not agent_family:
        raise ValueError("agent_family is required")
    if not current_id:
        raise ValueError("current_id is required")

    query = _build_next_phase_query(agent_family, current_id)

    try:
        result = sparql.sparql_query(query)
    except Exception as exc:
        raise PipelineDataError(f"next_phase: {exc}") from exc

    bindings = result.get("results", []) if isinstance(result, dict) else []
    if not bindings:
        return {"next_id": TERMINATE}

    if len(bindings) == 1:
        next_id = bindings[0].get("phaseId") or ""
        return {"next_id": next_id or TERMINATE}

    for binding in bindings:
        branch = binding.get("verdict") or ""
        if branch == verdict:
            next_id = binding.get("phaseId") or ""
            if next_id:
                return {"next_id": next_id}

    logger.warning(
        "No verdictBranch=%r successor for phase=%s family=%s; terminating",
        verdict,
        current_id,
        agent_family,
    )
    return {"next_id": TERMINATE}


# ---------------------------------------------------------------------------
# record_phase_result (req-130-3-3, ADR-130-7)
# ---------------------------------------------------------------------------


def _allowed_intent_fields(phase_id: str) -> frozenset[str] | None:
    """Return the allowed ``phase:preserves-*`` key set for *phase_id*.

    Returns ``None`` when the tulla package is not installed, which signals
    callers to allow all fields rather than silently dropping everything.
    """
    try:
        from ontology_server.phase_predicate_names import get_predicates_for_phase
    except Exception:
        return None
    return get_predicates_for_phase(phase_id)


def _build_shacl_gate_query(phase_id: str) -> str:
    return (
        f"SELECT ?shape WHERE {{\n"
        f"  GRAPH <{PHASES_GRAPH}> {{\n"
        f"    <{PHASE_NS}{phase_id}> <{PHASE_NS}shaclGate> ?shape .\n"
        f"  }}\n"
        f"}}\n"
        f"LIMIT 1"
    )


def _lookup_shacl_gate(ontology: OntologyClient, phase_id: str) -> str | None:
    query = _build_shacl_gate_query(phase_id)
    try:
        result = ontology.sparql_query(query)
    except Exception as exc:
        raise PipelineDataError(f"_lookup_shacl_gate: {exc}") from exc
    bindings = result.get("results", []) if isinstance(result, dict) else []
    if not bindings:
        return None
    shape = str(bindings[0].get("shape", ""))
    return shape or None


def _lookup_requires_approval(ontology: SparqlClient, phase_id: str) -> bool:
    """Return True when the phase definition carries phase:requiresApproval."""
    query = (
        f"SELECT ?flag WHERE {{\n"
        f"  GRAPH <{PHASES_GRAPH}> {{\n"
        f"    <{PHASE_NS}{phase_id}> <{REQUIRES_APPROVAL_PRED}> ?flag .\n"
        f"  }}\n"
        f"}}\n"
        f"LIMIT 1"
    )
    try:
        result = ontology.sparql_query(query)
    except Exception as exc:
        raise PipelineDataError(f"_lookup_requires_approval: {exc}") from exc
    bindings = result.get("results", []) if isinstance(result, dict) else []
    if not bindings:
        return False
    return str(bindings[0].get("flag", "")).strip().lower() in ("true", "1")


def _run_shacl_gate(
    ontology: OntologyClient,
    phase_id: str,
    subject: str,
) -> list[str] | None:
    """Validate *subject* against the phase's declared SHACL gate.

    Returns ``None`` when the phase declares no gate, otherwise the list of
    violation strings (empty list == conforms).  A validate_instance
    exception counts as a violation — a declared gate never silently passes.
    """
    shape_uri = _lookup_shacl_gate(ontology, phase_id)
    if shape_uri is None:
        return None
    try:
        validation = ontology.validate_instance(subject, shape_uri)
    except Exception as exc:
        logger.error(
            "validate_instance raised for %s shape %s: %s",
            subject,
            shape_uri,
            exc,
        )
        return [str(exc)]
    conforms = bool(validation.get("conforms", True))
    violations = validation.get("violations", []) or []
    if conforms:
        return []
    return [str(v) for v in violations]


def _write_approval_status(
    ontology: OntologyClient,
    subject: str,
    phase_id: str,
    *,
    force_approved: bool = False,
) -> str:
    """Write phase:approvalStatus + phase:recordedAt on a validated output.

    Returns the status written: "pending" when the phase definition carries
    phase:requiresApproval (HITL gate point), else "approved".
    """
    from datetime import datetime, timezone

    if force_approved:
        status = APPROVAL_APPROVED
    else:
        status = (
            APPROVAL_PENDING
            if _lookup_requires_approval(ontology, phase_id)
            else APPROVAL_APPROVED
        )
    ontology.add_triple(subject, APPROVAL_STATUS_PRED, status, is_literal=True)
    ontology.add_triple(
        subject,
        RECORDED_AT_PRED,
        datetime.now(timezone.utc).isoformat(),
        is_literal=True,
    )
    return status


def _literalise(value: Any) -> str:
    """Convert *value* to its RDF literal string form."""
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def record_phase_result(
    ontology: OntologyClient,
    phase_id: str,
    idea_id: str,
    artifact_path: str,
    result_json: dict[str, Any],
    predecessor_phase_id: str | None = None,
) -> dict[str, Any]:
    """Persist a phase result using ADR-130-7's 8-step sequence."""
    if not phase_id:
        raise ValueError("phase_id is required")
    if not idea_id:
        raise ValueError("idea_id is required")
    if not idea_id.startswith("idea-"):
        idea_id = f"idea-{idea_id}"

    logger.info(
        "record_phase_result phase=%s idea=%s artifact=%s",
        phase_id,
        idea_id,
        artifact_path,
    )

    # (1) Compute subject URI.
    subject = f"{PHASE_NS}{idea_id}-{phase_id}"

    # (2) Idempotent cleanup — FIRST.
    try:
        cleared = ontology.remove_triples_by_subject(subject)
    except Exception as exc:
        logger.warning(
            "remove_triples_by_subject failed for %s before write: %s",
            subject,
            exc,
        )
        cleared = 0
    if cleared:
        logger.info("Cleared %d existing triples for subject %s", cleared, subject)

    # (3) rdf:type phase:PhaseOutput.
    ontology.add_triple(subject, RDF_TYPE, f"{PHASE_NS}PhaseOutput")

    # (4) phase:preserves-<name> edges for known intent fields.
    # allowed=None means tulla package absent → allow all fields.
    allowed = _allowed_intent_fields(phase_id)
    fields = result_json if isinstance(result_json, dict) else {}
    for key, value in fields.items():
        if allowed is not None and key not in allowed:
            continue
        if value is None:
            continue
        ontology.add_triple(
            subject,
            f"{PHASE_NS}preserves-{key}",
            _literalise(value),
            is_literal=True,
        )

    # (5) phase:producedBy metadata edge.
    ontology.add_triple(
        subject, f"{PHASE_NS}producedBy", phase_id, is_literal=True,
    )

    # (6) phase:forRequirement metadata edge.
    ontology.add_triple(
        subject, f"{PHASE_NS}forRequirement", idea_id, is_literal=True,
    )

    # (7) Optional trace:tracesTo predecessor edge.
    if predecessor_phase_id:
        pred_uri = f"{PHASE_NS}{idea_id}-{predecessor_phase_id}"
        ontology.add_triple(subject, f"{TRACE_NS}tracesTo", pred_uri)

    # (8) Optional SHACL validation + rollback.
    # ONTOLOGY_DISABLE_GATES exists for controlled ablation experiments
    # (SDLC-bench arm b: same fleet, gates off — a single-variable change).
    # NEVER set it in normal operation; it is logged loudly per call.
    # HITL approval is part of gating, so ablation mode always writes
    # "approved" — the arm stays a single-variable change.
    import os
    if os.environ.get("ONTOLOGY_DISABLE_GATES", "").lower() in ("1", "true", "yes"):
        logger.warning(
            "ONTOLOGY_DISABLE_GATES is set — SHACL gate SKIPPED for %s "
            "(ablation mode; do not use in production)",
            subject,
        )
        approval = _write_approval_status(
            ontology, subject, phase_id, force_approved=True
        )
        return {
            "ok": True, "violations": [], "gate_skipped": True,
            "approval": approval,
        }

    violations = _run_shacl_gate(ontology, phase_id, subject)
    if violations:
        logger.warning(
            "SHACL validation failed for %s — rolling back.  Violations (%d): %s",
            subject,
            len(violations),
            "; ".join(violations) or "(no detail returned)",
        )
        try:
            ontology.remove_triples_by_subject(subject)
        except Exception:
            logger.exception("rollback after SHACL violation failed")
        return {"ok": False, "violations": violations}

    # (9) HITL: mark the validated output pending when the phase is a
    # configured human gate point, else approved.  Either way ok=True —
    # the recording agent's job is done; waiting is the orchestrator's job.
    approval = _write_approval_status(ontology, subject, phase_id)
    return {"ok": True, "violations": [], "approval": approval}


# ---------------------------------------------------------------------------
# KnowledgeGraphStore adapters
# ---------------------------------------------------------------------------


class KGSparqlClient:
    """Adapts ``KnowledgeGraphStore.query()`` to the ``SparqlClient`` protocol.

    ``kg_store.query()`` returns a ``QueryResult`` with ``.bindings`` as
    ``[{var: value}]`` (already Python-native).  This adapter wraps it
    as ``{"results": bindings}`` so the phase functions above can call
    ``result.get("results", [])``.
    """

    def __init__(self, kg_store: "KnowledgeGraphStore") -> None:
        self._store = kg_store

    def sparql_query(self, query: str) -> dict[str, Any]:
        result = self._store.query(query)
        return {"results": result.bindings}


class KGOntologyClient(KGSparqlClient):
    """Extends ``KGSparqlClient`` with triple-mutation and SHACL validation.

    Wraps ``KnowledgeGraphStore`` methods to satisfy the ``OntologyClient``
    protocol used by ``record_phase_result``.  All mutations target
    ``GRAPH_PHASES`` (``http://semantic-tool-use.org/graphs/phases``).
    """

    def __init__(
        self,
        kg_store: "KnowledgeGraphStore",
        validator: "SHACLValidator | None" = None,
    ) -> None:
        super().__init__(kg_store)
        self._validator = validator

    def add_triple(
        self,
        subject: str,
        predicate: str,
        object: str,
        *,
        is_literal: bool = False,
    ) -> None:
        self._store.add_triple(
            subject, predicate, object,
            is_literal=is_literal,
            graph=PHASES_GRAPH,
        )

    def remove_triples_by_subject(self, subject: str) -> int:
        return self._store.remove_triple(subject=subject, graph=PHASES_GRAPH)

    def remove_triples(self, subject: str, predicate: str) -> int:
        return self._store.remove_triple(
            subject=subject, predicate=predicate, graph=PHASES_GRAPH,
        )

    def validate_instance(
        self,
        instance_uri: str,
        shape_uri: str,
    ) -> dict[str, Any]:
        # A phase that declares a shaclGate must never pass unvalidated —
        # missing validator or missing shape is a gate FAILURE, not a skip.
        if self._validator is None:
            logger.error(
                "validate_instance called for gated phase but no SHACLValidator "
                "configured; failing the gate"
            )
            return {
                "conforms": False,
                "violations": [
                    "SHACL gate declared but no validator is configured on the "
                    "server — refusing to persist unvalidated phase output"
                ],
            }

        # Scope validation to the ONE shape the phase declares.  All phase
        # output shapes share sh:targetClass phase:PhaseOutput, so validating
        # against a directory of shapes would apply every phase's shape to
        # every phase's output.  export_cbd_turtle follows sh:property
        # blank nodes, which export_turtle(subject=...) would corrupt.
        shapes_ttl = self._store.export_cbd_turtle(shape_uri, graph=PHASES_GRAPH)
        if not shapes_ttl:
            logger.error(
                "SHACL gate shape %s not found in phases graph; failing the gate",
                shape_uri,
            )
            return {
                "conforms": False,
                "violations": [
                    f"SHACL gate shape <{shape_uri}> not found in the phases "
                    "graph — seed phase-content.trig before running gated phases"
                ],
            }

        instance_ttl = self._store.export_turtle(graph=PHASES_GRAPH, subject=instance_uri)
        result = self._validator.validate(instance_ttl, shapes_ttl=shapes_ttl)
        rd = result.to_dict()
        # Normalise violations to strings for record_phase_result.
        violations = [
            v.get("message", str(v)) if isinstance(v, dict) else str(v)
            for v in rd.get("violations", [])
        ]
        return {"conforms": rd["conforms"], "violations": violations}


# ---------------------------------------------------------------------------
# Phase-content seeding
# ---------------------------------------------------------------------------


# Idempotency probe: a (subject, predicate) pair present only in the CURRENT
# trig version.  Older stores that lack it re-seed automatically (the upsert
# below clears each trig-declared subject first, so stale definitions are
# replaced, never duplicated).
#
# BUMP RULE: change this probe whenever phase-content.trig gains triples that
# existing stores must receive — otherwise deployed stores silently keep the
# old content.  Current probe: phase:requiresApproval ship-defaults (HITL).
_SEED_PROBE_SUBJECT = f"{PHASE_NS}d5"
_SEED_PROBE_PREDICATE = REQUIRES_APPROVAL_PRED


def _default_phase_content_path() -> "Path":
    from pathlib import Path
    import os

    override = os.environ.get("ONTOLOGY_PHASE_CONTENT_PATH")
    if override:
        return Path(override)
    # repo layout: <root>/src/ontology_server/mcp/phase_tools.py
    #              <root>/tulla/ontologies/phase-content.trig
    return Path(__file__).resolve().parents[3] / "tulla" / "ontologies" / "phase-content.trig"


def seed_phase_content(
    kg_store: "KnowledgeGraphStore",
    trig_path: "Path | None" = None,
) -> int:
    """Load phase definitions + SHACL gate shapes into the phases graph.

    Idempotent: skipped when the current trig's gate shapes are already
    present.  Returns the number of quads loaded (0 when skipped or the
    file is absent).

    Without this seed every phase that declares a ``phase:shaclGate`` fails
    hard at record time (missing shape == gate failure, never a silent pass),
    so the server logs an explicit error when the file cannot be found.
    """
    path = trig_path or _default_phase_content_path()

    ask = (
        f"ASK {{ GRAPH <{PHASES_GRAPH}> {{ "
        f"<{_SEED_PROBE_SUBJECT}> <{_SEED_PROBE_PREDICATE}> ?o . }} }}"
    )
    try:
        already = kg_store.ask(ask)
    except Exception:
        already = False
    if already:
        logger.debug(
            "Phase content already seeded (found %s %s)",
            _SEED_PROBE_SUBJECT, _SEED_PROBE_PREDICATE,
        )
        return 0

    if not path.exists():
        logger.error(
            "phase-content.trig not found at %s — SHACL gate shapes are missing "
            "and every gated phase will fail at record_phase_result. Set "
            "ONTOLOGY_PHASE_CONTENT_PATH or place the file.",
            path,
        )
        return 0

    trig = path.read_text(encoding="utf-8")

    # Upsert: an existing store may hold an OLDER version of these definition
    # subjects (e.g. a superseded phase:procedure literal). Clear each subject
    # the trig itself declares before loading, so re-seeding replaces stale
    # definitions instead of accumulating duplicates.  Live phase OUTPUTS
    # (phase:idea-*-*) are never among the trig's subjects and are untouched.
    import pyoxigraph as ox

    trig_format = getattr(ox, "RdfFormat", None)
    fmt = trig_format.TRIG if trig_format else "application/trig"
    subjects = {
        quad.subject.value
        for quad in ox.parse(trig, fmt)
        if isinstance(quad.subject, ox.NamedNode)
    }
    for subject in subjects:
        kg_store.remove_triple(subject=subject, graph=PHASES_GRAPH)

    quads = kg_store.load_trig(trig)
    logger.info(
        "Seeded phase content from %s (%d quads, %d subjects upserted)",
        path, quads, len(subjects),
    )
    return quads


if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register_phase_tools(
    mcp: "FastMCP",
    kg_store: "KnowledgeGraphStore",
    validator: "SHACLValidator | None" = None,
) -> None:
    """Register the 10 phase pipeline tools against *mcp*.

    Args:
        mcp: FastMCP server instance to attach tools to.
        kg_store: Knowledge graph store (backing the SPARQL transport).
        validator: Optional SHACL validator (needed for record_phase_result).
    """
    seed_phase_content(kg_store)

    sparql_client = KGSparqlClient(kg_store)
    ontology_client = KGOntologyClient(kg_store, validator)

    @mcp.tool()
    def collect_upstream_facts_tool(
        idea_id: str,
        consuming_phase_id: str | None = None,
    ) -> dict[str, Any]:
        """Collect upstream phase facts for an idea, grouped by phase.

        ALWAYS pass consuming_phase_id (your own phase id): the result is
        then filtered to the fields your phase declared it consumes, which
        cuts the payload by 60-95% on mature ideas. Without it you get
        EVERY field of EVERY completed phase (tens of thousands of tokens).
        Need a field outside your declared set? Fetch just that one with
        get_phase_fact instead of re-calling unfiltered.

        Args:
            idea_id: The requirement / idea identifier (e.g. "130").
            consuming_phase_id: Phase id of the CALLING phase; filters
                output to that phase's declared PHASE_CONSUMED_FIELDS.
                Falls back to unfiltered when nothing matches.
        """
        return collect_upstream_facts(sparql_client, idea_id, consuming_phase_id)

    @mcp.tool()
    def get_phase_fact_tool(
        idea_id: str,
        phase_id: str,
        field: str,
    ) -> dict[str, Any]:
        """Fetch ONE upstream phase field's full value (targeted drill-down).

        Cheap escape hatch when your filtered collect_upstream_facts_tool
        result lacks a field you genuinely need — never re-call the
        collector unfiltered.

        Args:
            idea_id: The requirement / idea identifier (e.g. "idea-16").
            phase_id: The phase that PRODUCED the field (e.g. "r3").
            field: The preserved field name (e.g. "findings").
        """
        return get_phase_fact(sparql_client, idea_id, phase_id, field)

    @mcp.tool()
    def list_pipeline_tool(agent_family: str) -> list[str]:
        """Return the topologically ordered phase_id list for an agent family.

        Args:
            agent_family: Agent family name (e.g. "research").
        """
        return list_pipeline(sparql_client, agent_family)

    @mcp.tool()
    def next_phase_tool(
        agent_family: str,
        current_id: str,
        verdict: str = "",
    ) -> dict[str, str]:
        """Return the next phase_id or "terminate" for the current phase.

        Args:
            agent_family: Agent family name.
            current_id: Current phase identifier.
            verdict: Optional verdict string for branching DAGs.
        """
        return next_phase(sparql_client, agent_family, current_id, verdict)

    @mcp.tool()
    def record_phase_result_tool(
        phase_id: str,
        idea_id: str,
        artifact_path: str = "",
        result_json: dict[str, Any] | None = None,
        predecessor_phase_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist a phase subagent's result (8-step ADR-130-7 sequence).

        Args:
            phase_id: Phase identifier (e.g. "r3").
            idea_id: Requirement / idea identifier (e.g. "130").
            artifact_path: Path of the on-disk artefact (audit only).
            result_json: The JSON object the subagent emitted.
            predecessor_phase_id: Optional upstream phase id for trace edge.
        """
        return record_phase_result(
            ontology_client,
            phase_id,
            idea_id,
            artifact_path,
            result_json or {},
            predecessor_phase_id,
        )

    @mcp.tool()
    def render_phase_spec(phase_id: str, section: str = "all") -> str:
        """Return one section (or all) of a phase's specification as markdown.

        Consolidates render_gates/input/output/methodology/tools/prompt behind a
        single tool. Dispatches to the same underlying renderers, so output is
        identical to the individual render_*_tool variants.

        Args:
            phase_id: Phase identifier (e.g. "r3").
            section: One of "gates", "input", "output", "methodology", "tools",
                "prompt", or "all" (default). "all" concatenates every section.
        """
        renderers = {
            "gates": render_gates,
            "input": render_input_contract,
            "output": render_output_contract,
            "methodology": render_methodology,
            "tools": render_tools,
            "prompt": render_phase_prompt,
        }
        sec = (section or "all").strip().lower()
        if sec == "all":
            parts = []
            for name in ("methodology", "input", "output", "gates", "tools", "prompt"):
                parts.append(renderers[name](sparql_client, phase_id))
            return "\n\n".join(p for p in parts if p)
        if sec not in renderers:
            valid = ", ".join(sorted(renderers) + ["all"])
            raise ValueError(f"unknown section {section!r}; expected one of: {valid}")
        return renderers[sec](sparql_client, phase_id)

    @mcp.tool()
    async def await_approval_tool(
        idea_id: str,
        phase_id: str,
        timeout_s: float = 50,
    ) -> dict[str, Any]:
        """Long-poll the HITL approval decision for a recorded phase output.

        Blocks server-side (async, cheap) until a human approves or rejects
        the output in the dashboard, or timeout_s elapses.  Read-only: the
        decision itself can only be made via the dashboard/REST — never
        through MCP, so agents cannot approve their own output.

        Args:
            idea_id: Requirement / idea identifier (e.g. "idea-15").
            phase_id: Phase identifier whose output awaits review (e.g. "p1").
            timeout_s: Max seconds to wait before returning "pending"
                (clamped to 5–110).

        Returns:
            {"status": "approved"|"rejected"|"pending"|"missing",
             "comment": str|None}
        """
        # Lazy import: phase_approval imports helpers from this module at
        # module level; importing it here keeps the cycle one-directional.
        from ontology_server.phase_approval import await_approval

        return await await_approval(
            sparql_client, idea_id, phase_id, timeout_s=timeout_s,
        )

    logger.info(
        "Registered 7 phase pipeline tools (incl. render_phase_spec, "
        "await_approval_tool, get_phase_fact_tool)"
    )
