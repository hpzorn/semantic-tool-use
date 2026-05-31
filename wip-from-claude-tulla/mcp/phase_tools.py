"""Server-side reimplementation of phase fact collection and grouping.

Reimplements :func:`tulla.core.phase_facts.collect_upstream_facts` and
:func:`tulla.core.phase_facts.group_upstream_facts` for execution inside the
ontology-server process.  Because the server cannot import the ``tulla.*``
package, the coercion semantics of ``tulla.core.phase_facts._try_coerce` are
mirrored here verbatim.

Behaviour must be **byte-identical** to the in-process variant for any idea
whose phase facts are stored in the ``phases`` named graph.

Architecture decisions: arch:adr-73-1, arch:adr-73-5, arch:adr-130-7
Quality focus: isaqb:FunctionalCorrectness
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol


logger = logging.getLogger(__name__)


# Namespace and predicate prefixes are duplicated from tulla.namespaces on
# purpose — the server side does not depend on the tulla package.
PHASE_NS = "http://tulla.dev/phase#"
TRACE_NS = "http://tulla.dev/trace#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
PHASES_GRAPH = "http://semantic-tool-use.org/graphs/phases"
_PRESERVES_PREFIX = f"{PHASE_NS}preserves-"


class SparqlClient(Protocol):
    """Minimal contract for the SPARQL backend the server passes in.

    Any object exposing a ``sparql_query(query: str) -> dict[str, Any]`` method
    that returns ``{"results": [...]}`` satisfies this protocol.
    """

    def sparql_query(self, query: str) -> dict[str, Any]:  # pragma: no cover
        ...


class OntologyClient(Protocol):
    """Extended contract for record_phase_result.

    Adds the triple-mutation and SHACL-validation methods on top of
    :class:`SparqlClient` so the persist-validate-rollback cycle of
    :func:`record_phase_result` can be expressed without leaking the
    raw SPARQL transport.  Compatible with
    :class:`tulla.ports.ontology.OntologyPort` and any adapter that
    exposes the same surface.
    """

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


def _try_coerce(value: str) -> Any:
    """Attempt to coerce a string value to a richer Python type.

    Mirrors ``tulla.core.phase_facts._try_coerce`` byte-for-byte: tries int,
    then float, then RDF/SPARQL canonical bool (``"true"``/``"false"``), then
    JSON for compound (list/dict) values, then falls back to the original
    string.
    """
    try:
        return int(value)
    except (ValueError, TypeError):
        pass

    try:
        return float(value)
    except (ValueError, TypeError):
        pass

    if value.lower() in ("true", "false"):
        return value.lower() == "true"

    try:
        parsed = json.loads(value)
        if isinstance(parsed, (list, dict)):
            return parsed
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    return value


def _build_query(idea_id: str) -> str:
    """Return the SPARQL SELECT for all triples in the ``phases`` graph that
    belong to the given idea (matched via ``phase:forRequirement``).
    """
    return (
        f"SELECT ?s ?p ?o WHERE {{\n"
        f"  GRAPH <{PHASES_GRAPH}> {{\n"
        f'    ?s <{PHASE_NS}forRequirement> "{idea_id}" .\n'
        f"    ?s ?p ?o .\n"
        f"  }}\n"
        f"}}"
    )


def collect_upstream_facts(
    sparql: SparqlClient,
    idea_id: str,
) -> dict[str, dict[str, Any]]:
    """Collect and group all phase facts for *idea_id* in one call.

    Equivalent to ``group_upstream_facts(collect_upstream_facts(...))`` from
    :mod:`tulla.core.phase_facts` when the upstream filter accepts every
    phase.  Returns ``{phase_id: {field_name: typed_value}}``.

    Only ``phase:preserves-*`` predicates contribute fields; metadata
    predicates (``producedBy``, ``forRequirement``, ``rdf:type``,
    ``trace:tracesTo``) are silently skipped, matching the in-process
    grouping logic.

    On query failure, returns an empty dict with a log warning.
    """
    query = _build_query(idea_id)

    try:
        result = sparql.sparql_query(query)
    except Exception as exc:
        logger.warning(
            "SPARQL query for upstream facts failed (idea=%s): %s",
            idea_id,
            exc,
        )
        return {}

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

    return grouped


# ---------------------------------------------------------------------------
# render_methodology (req-130-2-2)
# ---------------------------------------------------------------------------


def _build_methodology_query(phase_id: str) -> str:
    """Return the SPARQL SELECT for ``phase:procedure`` of *phase_id*."""
    return (
        f"SELECT ?proc WHERE {{\n"
        f"  GRAPH <{PHASES_GRAPH}> {{\n"
        f"    <{PHASE_NS}{phase_id}> <{PHASE_NS}procedure> ?proc .\n"
        f"  }}\n"
        f"}}"
    )


def render_methodology(sparql: SparqlClient, phase_id: str) -> str:
    """Return the markdown body of ``phase:<phase_id> phase:procedure``.

    Issues a single SPARQL SELECT against the ``phases`` named graph and
    returns the literal value of the ``?proc`` binding verbatim.

    Edge cases (per req-130-2-2):
        * A falsy *phase_id* raises :class:`ValueError` so the HTTP twin
          can map it onto a 404.
        * A missing ``phase:procedure`` triple (no bindings) returns the
          empty string and emits a warning log — callers treat the phase
          as having no agent-driven methodology.
        * Any SPARQL transport failure also returns the empty string with
          a warning log, matching the resilience profile of
          :func:`collect_upstream_facts`.
    """
    if not phase_id:
        raise ValueError("phase_id is required")

    query = _build_methodology_query(phase_id)

    try:
        result = sparql.sparql_query(query)
    except Exception as exc:
        logger.warning(
            "SPARQL query for phase methodology failed (phase=%s): %s",
            phase_id,
            exc,
        )
        return ""

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
    """Return the SPARQL SELECT UNION-ing ``phase:requiresTool`` and
    ``phase:requiresMcp`` literal values for *phase_id*.
    """
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
    """Group *values* into Tools vs MCP Tools and emit the two-section markdown.

    Values whose name starts with ``mcp__`` are classified as MCP tools;
    everything else is a native tool.  Within each section the names are
    de-duplicated and lexically sorted to produce a deterministic body.
    """
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
    """Return the markdown two-section bullet list of tools for *phase_id*.

    Issues a single SPARQL UNION SELECT against the ``phases`` named graph
    over ``phase:requiresTool`` and ``phase:requiresMcp``.  The resulting
    literals are grouped into a ``## Tools`` section (native names) and a
    ``## MCP Tools`` section (``mcp__server__tool`` form).

    Edge cases (mirroring :func:`render_methodology`):
        * Falsy *phase_id* raises :class:`ValueError` so the HTTP twin can
          map it onto a 404.
        * No bindings: returns the two empty sections (still markdown).
        * SPARQL transport failure: also returns the two empty sections
          with a warning log, matching the resilience profile of
          :func:`collect_upstream_facts`.
    """
    if not phase_id:
        raise ValueError("phase_id is required")

    query = _build_tools_query(phase_id)

    try:
        result = sparql.sparql_query(query)
    except Exception as exc:
        logger.warning(
            "SPARQL query for phase tools failed (phase=%s): %s",
            phase_id,
            exc,
        )
        return _format_tools_markdown([])

    bindings = result.get("results", []) if isinstance(result, dict) else []
    values = [str(b.get("val", "")) for b in bindings]
    return _format_tools_markdown(values)


# ---------------------------------------------------------------------------
# render_gates (req-130-2-4)
# ---------------------------------------------------------------------------


def _build_gates_query(phase_id: str) -> str:
    """Return the SPARQL SELECT for ``phase:shaclGate`` shapes of *phase_id*.

    Includes the optional ``rdfs:label`` so a missing label still binds the
    shape URI.  The query targets the ``phases`` named graph; shape labels,
    however, typically live in the phase ontology — the OPTIONAL clause is
    unscoped so the engine resolves labels from any graph that asserts them.
    """
    return (
        f"SELECT ?shape ?label WHERE {{\n"
        f"  GRAPH <{PHASES_GRAPH}> {{\n"
        f"    <{PHASE_NS}{phase_id}> <{PHASE_NS}shaclGate> ?shape .\n"
        f"    OPTIONAL {{ ?shape <http://www.w3.org/2000/01/rdf-schema#label> ?label }}\n"
        f"  }}\n"
        f"}}"
    )


def _abbreviate_shape_uri(uri: str) -> str:
    """Return *uri* with the ``phase:`` prefix substituted when applicable.

    Keeps the verification criterion deterministic by rendering shapes that
    live in the phase namespace as ``phase:Local`` while passing other URIs
    through unchanged.
    """
    if uri.startswith(PHASE_NS):
        return f"phase:{uri[len(PHASE_NS):]}"
    return uri


def _format_gates_markdown(rows: list[tuple[str, str]]) -> str:
    """Render *rows* as one ``SHACL Gate: <uri> — <label>`` line per gate.

    Shapes are deduplicated by URI and sorted lexically for determinism.
    The label segment renders an empty string when no ``rdfs:label`` is
    available, matching the spec format verbatim.
    """
    seen: dict[str, str] = {}
    for shape_uri, label in rows:
        if not shape_uri:
            continue
        # Keep first non-empty label encountered.
        if shape_uri not in seen or (not seen[shape_uri] and label):
            seen[shape_uri] = label
    lines: list[str] = []
    for shape_uri in sorted(seen.keys()):
        abbr = _abbreviate_shape_uri(shape_uri)
        lines.append(f"SHACL Gate: {abbr} — {seen[shape_uri]}")
    return "\n".join(lines)


def render_gates(sparql: SparqlClient, phase_id: str) -> str:
    """Return the markdown gate list for *phase_id* (one line per shape).

    Issues a single SPARQL SELECT against the ``phases`` named graph for
    ``phase:shaclGate`` triples, joining each shape with its optional
    ``rdfs:label``.  Output format mirrors the requirement spec verbatim::

        SHACL Gate: <shape_uri> — <label>

    Edge cases (mirroring :func:`render_methodology`):
        * Falsy *phase_id* raises :class:`ValueError` so the HTTP twin can
          map it onto a 404.
        * No bindings: returns the empty string (still a successful body).
        * SPARQL transport failure: returns the empty string with a warning
          log, matching the resilience profile of
          :func:`collect_upstream_facts`.
    """
    if not phase_id:
        raise ValueError("phase_id is required")

    query = _build_gates_query(phase_id)

    try:
        result = sparql.sparql_query(query)
    except Exception as exc:
        logger.warning(
            "SPARQL query for phase gates failed (phase=%s): %s",
            phase_id,
            exc,
        )
        return ""

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
    """Return the SPARQL SELECT for the ``phase:inputContract`` fields of
    *phase_id*.

    Joins the phase to its contract node, the contract to each
    ``phase:requiresField`` literal and the matching ``phase:fieldType``
    literal, and OPTIONALly the ``phase:fieldDescription``.  The literal
    of the SELECT mirrors the spec verbatim so the verification criterion
    can be checked against the query text directly.
    """
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
    """Render *rows* as a three-column markdown table.

    Columns are ``Field | Type | Description``.  Rows are de-duplicated by
    field name (first non-empty type/description wins) and sorted lexically
    for determinism.  When *rows* is empty the function returns the empty
    string so callers can distinguish "no contract" from "header-only".
    """
    seen: dict[str, tuple[str, str]] = {}
    for field, ftype, fdesc in rows:
        if not field:
            continue
        cur = seen.get(field)
        if cur is None:
            seen[field] = (ftype, fdesc)
        else:
            cur_type, cur_desc = cur
            seen[field] = (
                cur_type or ftype,
                cur_desc or fdesc,
            )

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
    """Return the markdown table of the input contract for *phase_id*.

    Issues a single SPARQL SELECT against the ``phases`` named graph for
    ``phase:inputContract`` and its ``phase:requiresField`` /
    ``phase:fieldType`` / optional ``phase:fieldDescription`` fields.
    Result is a three-column markdown table::

        | Field | Type | Description |
        |-------|------|-------------|
        | <field> | <type> | <desc> |

    Edge cases (mirroring :func:`render_gates`):
        * Falsy *phase_id* raises :class:`ValueError` so the HTTP twin can
          map it onto a 404.
        * No bindings: returns the empty string.
        * SPARQL transport failure: returns the empty string with a warning
          log, matching the resilience profile of
          :func:`collect_upstream_facts`.
    """
    if not phase_id:
        raise ValueError("phase_id is required")

    query = _build_input_contract_query(phase_id)

    try:
        result = sparql.sparql_query(query)
    except Exception as exc:
        logger.warning(
            "SPARQL query for phase input contract failed (phase=%s): %s",
            phase_id,
            exc,
        )
        return ""

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
    """Return the SPARQL SELECT for the ``phase:outputContract`` fields and
    the ``phase:emitsIntentField`` literals of *phase_id*.

    A single UNION SELECT keeps the function at one round-trip — one branch
    captures the (field, type, desc) shape of the contract proper, the
    other captures the intent-field names the subagent must emit (the keys
    expected in its JSON response, sourced from the triples populated by
    the extractor in Task 1.2 from ``PHASE_PREDICATE_NAMES``).
    """
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
    """Render the output-contract table and the emits-intent-field block.

    The contract table reuses the same three-column ``Field | Type |
    Description`` layout as :func:`_format_input_contract_markdown` so
    downstream renderers can pattern-match on a single header.  Rows are
    de-duplicated by field name (first non-empty type/description wins)
    and sorted lexically for determinism.

    The intent-field block lists each ``phase:emitsIntentField`` value as
    a bullet item under a ``## Emits Intent Fields`` heading.  Intent
    field names are de-duplicated **while preserving first-seen order**
    so that the Pydantic order recorded by the extractor (Task 1.2)
    survives the round trip — this is the load-bearing invariant for the
    requirement's verification criterion.

    Returns the empty string when both the table and the intent-field
    list are empty, so callers can distinguish "no output contract" from
    "header-only table".
    """
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
    """Return the markdown output contract for *phase_id*.

    Issues a single SPARQL UNION SELECT against the ``phases`` named
    graph for ``phase:outputContract`` (with its
    ``phase:requiresField`` / ``phase:fieldType`` / optional
    ``phase:fieldDescription``) and for ``phase:emitsIntentField``.

    The resulting markdown is a three-column table of the output
    contract followed by a ``## Emits Intent Fields`` bullet list whose
    order mirrors the Pydantic field order recorded by the extractor
    (Task 1.2).  The intent block is what tells the phase subagent
    which keys it must put in its JSON response.

    Edge cases (mirroring :func:`render_input_contract`):
        * Falsy *phase_id* raises :class:`ValueError` so the HTTP twin
          can map it onto a 404.
        * No bindings: returns the empty string.
        * SPARQL transport failure: returns the empty string with a
          warning log, matching the resilience profile of
          :func:`collect_upstream_facts`.
    """
    if not phase_id:
        raise ValueError("phase_id is required")

    query = _build_output_contract_query(phase_id)

    try:
        result = sparql.sparql_query(query)
    except Exception as exc:
        logger.warning(
            "SPARQL query for phase output contract failed (phase=%s): %s",
            phase_id,
            exc,
        )
        return ""

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
# render_phase_prompt (req-130-2-7) — coarse default
# ---------------------------------------------------------------------------


# Canonical section order — see the requirement description.  The phase
# subagent's static .md body calls ``render_phase_prompt(phase_id)`` at
# step 1, so this ordering doubles as the contract between the renderer
# and every downstream prompt template.
PHASE_PROMPT_SECTIONS: tuple[tuple[str, str], ...] = (
    ("Methodology", "render_methodology"),
    ("Tools", "render_tools"),
    ("Gates", "render_gates"),
    ("Input Contract", "render_input_contract"),
    ("Output Contract", "render_output_contract"),
)


def render_phase_prompt(sparql: SparqlClient, phase_id: str) -> str:
    """Return the composed initial-seed prompt body for *phase_id*.

    Composition of the five granular renderers (req-130-2-2 .. 2-6) in
    canonical order::

        ## Methodology

        <render_methodology output>

        ## Tools

        <render_tools output>

        ## Gates

        <render_gates output>

        ## Input Contract

        <render_input_contract output>

        ## Output Contract

        <render_output_contract output>

    Each granular renderer is invoked exactly once; their bodies are
    inlined verbatim under the canonical H2 header.  Sections whose
    granular renderer returns the empty string still emit the header so
    the downstream prompt template can rely on a stable skeleton — the
    body is the renderer's own resilience signal (e.g. "no procedure
    set"), not the composer's.

    Edge cases:
        * Falsy *phase_id* raises :class:`ValueError` so the HTTP twin
          can map it onto a 404.
        * Granular renderer failures (SPARQL transport errors) are
          surfaced as empty bodies by the renderers themselves; the
          composer remains side-effect free.
    """
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
# list_pipeline (req-130-2-8) — DAG topo sort by ancestor depth
# ---------------------------------------------------------------------------


def _build_list_pipeline_query(agent_family: str) -> str:
    """Return the SPARQL SELECT for the *agent_family* pipeline.

    Counts each phase's transitive upstream ancestors via the
    ``phase:upstreamPhase+`` property path so the result can be ordered
    topologically (by ancestor depth ascending, breaking ties by
    ``phase:phaseId`` for determinism).  Both the phase under
    consideration and its ancestors are constrained to the same
    *agent_family* so that the closure stays within the family DAG even
    when the underlying graph holds cross-family edges.
    """
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
    """Return the ordered phase_id list for *agent_family*.

    Issues a single SPARQL SELECT against the ``phases`` named graph that
    computes the transitive closure over ``phase:upstreamPhase+`` for
    every phase whose ``phase:agentFamily`` matches *agent_family*, then
    orders the result topologically by ancestor depth (depth 0 first).
    The returned list contains the ``phase:phaseId`` literals — the same
    string identifiers accepted by :func:`render_methodology` and friends.

    Edge cases:
        * Falsy *agent_family* raises :class:`ValueError` so the HTTP twin
          can map it onto a 404.
        * An agent family with no phases returns ``[]`` (a successful
          empty pipeline, not an error).
        * SPARQL transport failure also returns ``[]`` with a warning log,
          matching the resilience profile of :func:`collect_upstream_facts`.
    """
    if not agent_family:
        raise ValueError("agent_family is required")

    query = _build_list_pipeline_query(agent_family)

    try:
        result = sparql.sparql_query(query)
    except Exception as exc:
        logger.warning(
            "SPARQL query for pipeline list failed (agent_family=%s): %s",
            agent_family,
            exc,
        )
        return []

    bindings = result.get("results", []) if isinstance(result, dict) else []
    pipeline: list[str] = []
    for binding in bindings:
        phase_id = str(binding.get("phaseId", ""))
        if phase_id:
            pipeline.append(phase_id)
    return pipeline


# ---------------------------------------------------------------------------
# next_phase (req-130-2-9) — inverse-phase:upstreamPhase + verdict branch
# ---------------------------------------------------------------------------


TERMINATE = "terminate"


def _build_next_phase_query(agent_family: str, current_id: str) -> str:
    """Return the SPARQL SELECT for the successors of *current_id* within
    *agent_family*.

    The inverse of ``phase:upstreamPhase`` is computed by binding the
    current phase via its ``phase:phaseId`` literal, then matching every
    ``?next phase:upstreamPhase ?current`` triple whose ``?next`` shares
    the same ``phase:agentFamily``.  The optional
    ``phase:verdictBranch`` literal allows the caller to disambiguate
    between multiple successor edges (e.g. ``"proceed"`` vs
    ``"retry"``).  The phase_id of each successor is projected so the
    callable can return the verdict-matching one to the user.
    """
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
    """Return ``{"next_id": <phase_id> | "terminate"}`` for *current_id*.

    Resolves the successor phase via the inverse of
    ``phase:upstreamPhase`` within *agent_family*:

    * A single successor edge (linear pipeline step) is returned
      verbatim, **regardless of *verdict*** — the verdict is only
      consulted when the DAG branches.
    * Multiple successor edges qualified by ``phase:verdictBranch`` are
      filtered by *verdict* — the first edge whose literal matches is
      returned.
    * No successor at all (or no verdict match in a branching node)
      returns ``{"next_id": "terminate"}`` so the runner can halt the
      pipeline cleanly.

    Edge cases:
        * Falsy *agent_family* or *current_id* raises :class:`ValueError`
          so the HTTP twin can map them onto a 404 / MCP error.
        * SPARQL transport failure returns ``{"next_id": "terminate"}``
          with a warning log, matching the resilience profile of
          :func:`collect_upstream_facts`.
    """
    if not agent_family:
        raise ValueError("agent_family is required")
    if not current_id:
        raise ValueError("current_id is required")

    query = _build_next_phase_query(agent_family, current_id)

    try:
        result = sparql.sparql_query(query)
    except Exception as exc:
        logger.warning(
            "SPARQL query for next phase failed (current=%s, family=%s): %s",
            current_id,
            agent_family,
            exc,
        )
        return {"next_id": TERMINATE}

    bindings = result.get("results", []) if isinstance(result, dict) else []
    if not bindings:
        return {"next_id": TERMINATE}

    if len(bindings) == 1:
        next_id = str(bindings[0].get("phaseId", ""))
        return {"next_id": next_id or TERMINATE}

    for binding in bindings:
        branch = str(binding.get("verdict", ""))
        if branch and branch == verdict:
            next_id = str(binding.get("phaseId", ""))
            if next_id:
                return {"next_id": next_id}

    return {"next_id": TERMINATE}


# ---------------------------------------------------------------------------
# record_phase_result (req-130-3-3) — ADR-130-7's 8-step persist sequence
# ---------------------------------------------------------------------------


def _allowed_intent_fields(phase_id: str) -> frozenset[str]:
    """Return the local-name set of ``phase:preserves-*`` keys for *phase_id*.

    Resolves against :data:`tulla.ontology.phase_predicate_names.PHASE_PREDICATE_NAMES`
    via the ``get_predicates_for_phase`` helper so dynamic
    ``p6-iter-{N}`` iteration ids fall back to the canonical ``p6-iter``
    stem.  Returns an empty frozenset for unknown phase ids — record
    still proceeds, but no ``preserves-*`` triples are written.

    The import is deliberately lazy so the server-side module remains
    importable in deployments where the ``tulla`` package is unavailable;
    in that scenario the returned set is empty and the caller is
    expected to provide an allow-list via another mechanism.
    """
    try:
        from tulla.ontology.phase_predicate_names import (
            get_predicates_for_phase,
        )
    except Exception:  # pragma: no cover - defensive for embedded use
        return frozenset()
    return get_predicates_for_phase(phase_id)


def _build_shacl_gate_query(phase_id: str) -> str:
    """Return the SPARQL SELECT for the ``phase:shaclGate`` of *phase_id*.

    Limits to a single binding because :func:`record_phase_result`
    validates against at most one shape per persist (matching the
    single ``shacl_shape_id`` parameter of
    :class:`tulla.core.phase_facts.PhaseFactPersister.persist`).
    """
    return (
        f"SELECT ?shape WHERE {{\n"
        f"  GRAPH <{PHASES_GRAPH}> {{\n"
        f"    <{PHASE_NS}{phase_id}> <{PHASE_NS}shaclGate> ?shape .\n"
        f"  }}\n"
        f"}}\n"
        f"LIMIT 1"
    )


def _lookup_shacl_gate(ontology: OntologyClient, phase_id: str) -> str | None:
    """Look up the SHACL gate shape URI for *phase_id*, or ``None``."""
    query = _build_shacl_gate_query(phase_id)
    try:
        result = ontology.sparql_query(query)
    except Exception as exc:
        logger.warning(
            "SPARQL lookup of shaclGate failed (phase=%s): %s", phase_id, exc,
        )
        return None
    bindings = result.get("results", []) if isinstance(result, dict) else []
    if not bindings:
        return None
    shape = str(bindings[0].get("shape", ""))
    return shape or None


def _literalise(value: Any) -> str:
    """Convert *value* to its RDF literal string form.

    Scalars round-trip through ``str()``; compound values (list / dict)
    are JSON-stringified so that :func:`_try_coerce` on the read path
    can recover the original Python structure.  Mirrors
    :meth:`PhaseFactPersister.persist`'s ``str(value)`` for scalars and
    the JSON-stringify discipline documented by ADR-130-7 for compounds.
    """
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
    """Persist a phase subagent's intent-field JSON to the phases graph.

    Implements ADR-130-7's 8-step persist-validate-rollback sequence in
    order — behaviour matches
    :meth:`tulla.core.phase_facts.PhaseFactPersister.persist`:

    1. Compute the subject URI ``{PHASE_NS}{idea_id}-{phase_id}``.
    2. Idempotent cleanup — ``remove_triples_by_subject(subject)``.
       This is load-bearing for both RQ1 re-entry and RQ2
       self-baseline measurement (see arch:adr-130-7).
    3. ``rdf:type phase:PhaseOutput`` for SHACL ``sh:targetClass``.
    4. For every ``key`` in *result_json* whose name is in
       :data:`PHASE_PREDICATE_NAMES[phase_id]`, add
       ``subject phase:preserves-<key> str(value)`` (compounds are
       JSON-stringified so :func:`_try_coerce` can recover the
       original Python value on the read path).  Keys outside the
       allow-list are silently dropped — they would not survive the
       drift harness round-trip in any case.
    5. ``phase:producedBy <phase_id>`` metadata edge.
    6. ``phase:forRequirement <idea_id>`` metadata edge.
    7. ``trace:tracesTo phase:<idea_id>-<predecessor_phase_id>`` when
       a predecessor is given.
    8. Look up ``phase:shaclGate``; when present, validate the
       subject against the shape and, on violation, roll back via a
       second ``remove_triples_by_subject(subject)`` so the persist is
       atomic.

    Arguments:
        ontology: Client exposing the four mutation/validation methods
            of :class:`OntologyClient`.
        phase_id: The phase identifier (``r5``, ``p3``, ``p6-iter-3``).
        idea_id: The requirement identifier (``130``, ``73``).
        artifact_path: Path of the on-disk artefact produced by the
            subagent.  Audit/logging only — *not* persisted as a triple.
        result_json: The JSON object the subagent emitted; only
            intent-field keys (per :data:`PHASE_PREDICATE_NAMES`) are
            persisted as ``phase:preserves-*`` triples.
        predecessor_phase_id: Optional upstream phase id to link via
            ``trace:tracesTo``.

    Returns:
        ``{"ok": True, "violations": []}`` on a clean persist (or when
        no SHACL gate is attached to the phase).  On SHACL violation —
        or on an exception from :func:`validate_instance` — the
        persisted triples are rolled back and the function returns
        ``{"ok": False, "violations": [...]}`` with the violation
        messages collected from the SHACL report.

    Edge cases:
        * Falsy *phase_id* or *idea_id* raises :class:`ValueError` so
          the HTTP twin can map it onto a 404.
        * *result_json* is treated as empty when not a dict — the
          metadata triples (rdf:type / producedBy / forRequirement /
          tracesTo) are still emitted so the audit trail records the
          attempt.
    """
    if not phase_id:
        raise ValueError("phase_id is required")
    if not idea_id:
        raise ValueError("idea_id is required")

    logger.info(
        "record_phase_result phase=%s idea=%s artifact=%s",
        phase_id,
        idea_id,
        artifact_path,
    )

    # (1) Compute subject URI.
    subject = f"{PHASE_NS}{idea_id}-{phase_id}"

    # (2) Idempotent cleanup — FIRST.  Load-bearing per ADR-130-7.
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

    # (3) rdf:type phase:PhaseOutput so SHACL sh:targetClass matches.
    ontology.add_triple(subject, RDF_TYPE, f"{PHASE_NS}PhaseOutput")

    # (4) phase:preserves-<name> edges for each known intent field.
    allowed = _allowed_intent_fields(phase_id)
    fields = result_json if isinstance(result_json, dict) else {}
    for key, value in fields.items():
        if key not in allowed:
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
