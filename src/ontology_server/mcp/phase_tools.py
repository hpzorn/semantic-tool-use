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
        lines.append(f"SHACL Gate: {abbr} — {seen[shape_uri]}")
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
        shape_uri = str(binding.get("shape", ""))
        label = str(binding.get("label", ""))
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
        field = str(binding.get("field", ""))
        ftype = str(binding.get("type", ""))
        fdesc = str(binding.get("desc", ""))
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
        field = str(binding.get("field", ""))
        intent = str(binding.get("intent", ""))
        if field:
            rows.append(
                (
                    field,
                    str(binding.get("type", "")),
                    str(binding.get("desc", "")),
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
        phase_id = str(binding.get("phaseId", ""))
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
        next_id = str(bindings[0].get("phaseId", ""))
        return {"next_id": next_id or TERMINATE}

    for binding in bindings:
        branch = str(binding.get("verdict", ""))
        if branch == verdict:
            next_id = str(binding.get("phaseId", ""))
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
    shape_uri = _lookup_shacl_gate(ontology, phase_id)
    if shape_uri is None:
        return {"ok": True, "violations": []}

    try:
        validation = ontology.validate_instance(subject, shape_uri)
    except Exception as exc:
        logger.error(
            "validate_instance raised for %s shape %s: %s",
            subject,
            shape_uri,
            exc,
        )
        try:
            ontology.remove_triples_by_subject(subject)
        except Exception:
            logger.exception("rollback after validate_instance exception failed")
        return {"ok": False, "violations": [str(exc)]}

    conforms = bool(validation.get("conforms", True))
    violations = validation.get("violations", []) or []
    if conforms:
        return {"ok": True, "violations": []}

    error_strs = [str(v) for v in violations]
    logger.warning(
        "SHACL validation failed for %s — rolling back.  Violations (%d): %s",
        subject,
        len(error_strs),
        "; ".join(error_strs) or "(no detail returned)",
    )
    try:
        ontology.remove_triples_by_subject(subject)
    except Exception:
        logger.exception("rollback after SHACL violation failed")
    return {"ok": False, "violations": error_strs}


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

    def validate_instance(
        self,
        instance_uri: str,
        shape_uri: str,
    ) -> dict[str, Any]:
        if self._validator is None:
            logger.warning(
                "validate_instance called but no SHACLValidator configured; "
                "reporting conforms=True"
            )
            return {"conforms": True, "violations": []}

        instance_ttl = self._store.export_turtle(graph=PHASES_GRAPH, subject=instance_uri)
        result = self._validator.validate(instance_ttl, shapes_uri=shape_uri)
        rd = result.to_dict()
        # Normalise violations to strings for record_phase_result.
        violations = [
            v.get("message", str(v)) if isinstance(v, dict) else str(v)
            for v in rd.get("violations", [])
        ]
        return {"conforms": rd["conforms"], "violations": violations}


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
    sparql_client = KGSparqlClient(kg_store)
    ontology_client = KGOntologyClient(kg_store, validator)

    @mcp.tool()
    def collect_upstream_facts_tool(
        idea_id: str,
        consuming_phase_id: str | None = None,
    ) -> dict[str, Any]:
        """Collect all phase facts for an idea grouped by phase.

        Pass consuming_phase_id to filter results to only the fields the
        consuming phase declared it needs (reduces context size).

        Args:
            idea_id: The requirement / idea identifier (e.g. "130").
            consuming_phase_id: Optional phase id of the consuming phase;
                when provided, output is filtered to only the fields that
                phase declared it needs via PHASE_CONSUMED_FIELDS.
        """
        return collect_upstream_facts(sparql_client, idea_id, consuming_phase_id)

    @mcp.tool()
    def render_methodology_tool(phase_id: str) -> str:
        """Return the markdown procedure body for a phase.

        Args:
            phase_id: Phase identifier (e.g. "r3").
        """
        return render_methodology(sparql_client, phase_id)

    @mcp.tool()
    def render_tools_tool(phase_id: str) -> str:
        """Return the markdown two-section tool list for a phase.

        Args:
            phase_id: Phase identifier.
        """
        return render_tools(sparql_client, phase_id)

    @mcp.tool()
    def render_gates_tool(phase_id: str) -> str:
        """Return the markdown SHACL gate list for a phase.

        Args:
            phase_id: Phase identifier.
        """
        return render_gates(sparql_client, phase_id)

    @mcp.tool()
    def render_input_contract_tool(phase_id: str) -> str:
        """Return the markdown input contract table for a phase.

        Args:
            phase_id: Phase identifier.
        """
        return render_input_contract(sparql_client, phase_id)

    @mcp.tool()
    def render_output_contract_tool(phase_id: str) -> str:
        """Return the markdown output contract for a phase.

        Args:
            phase_id: Phase identifier.
        """
        return render_output_contract(sparql_client, phase_id)

    @mcp.tool()
    def render_phase_prompt_tool(phase_id: str) -> str:
        """Return the composed initial-seed prompt body for a phase.

        Args:
            phase_id: Phase identifier.
        """
        return render_phase_prompt(sparql_client, phase_id)

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

    logger.info("Registered 10 phase pipeline tools")
