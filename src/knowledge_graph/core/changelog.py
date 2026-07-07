"""Human-edit change log — reified change records in the knowledge graph.

Every field edit a human makes through the dashboard or REST API is recorded
as one ``change:Change`` resource in the changes named graph
(``http://semantic-tool-use.org/graphs/changes``): target subject + graph,
entity kind, field, old value, new value, attribution, time, optional reason.
Edits submitted together share a ``change:batch`` id.

Scope rule: ONLY human edits are logged.  Agent writes
(``record_phase_result``, MCP ``update_idea``, ``store_facts``) are not —
their provenance lives in the phases/memory graphs themselves.  Because the
change log is a separate graph, history survives phase re-records (which
wipe and rewrite the output subject).

Plain reification (no RDF-star) so the fleet and dashboard can query history
with ordinary SPARQL, matching the ``memory:Fact`` pattern.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from .store import GRAPH_CHANGES, KnowledgeGraphStore, NAMESPACES

logger = logging.getLogger(__name__)

RDF = NAMESPACES["rdf"]
XSD = NAMESPACES["xsd"]
CHANGE = NAMESPACES["change"]
PROV = NAMESPACES["prov"]
AGENTS = NAMESPACES["agents"]

# "default" marks the store's default graph (ideas), which has no URI.
DEFAULT_GRAPH_MARKER = "default"


def _escape(value: str) -> str:
    """Escape a string for safe embedding as a SPARQL plain-literal value."""
    value = value.replace("\\", "\\\\")
    value = value.replace('"', '\\"')
    value = value.replace("\n", "\\n")
    value = value.replace("\r", "\\r")
    return value


def new_batch_id() -> str:
    """Batch id shared by all changes of one form submit / API call."""
    return str(uuid.uuid4())[:8]


def record_change(
    kg_store: KnowledgeGraphStore,
    *,
    target: str,
    target_graph: str,
    field: str,
    old: str | None,
    new: str,
    changed_by: str,
    entity_kind: str,
    predicate: str | None = None,
    reason: str | None = None,
    batch_id: str | None = None,
) -> str:
    """Record one field edit as a change:Change resource.

    Args:
        target: URI of the edited resource (idea, phase output, fact).
        target_graph: Named graph holding the edited triple, or "default".
        field: Human-readable field name (e.g. "target_audience", "title").
        old: Previous literal value; None when the field was absent before.
        new: New literal value, stored verbatim (JSON stays JSON).
        changed_by: Attribution (e.g. "dashboard", a user name, "api").
        entity_kind: "phase_output" | "idea" | "fact".
        predicate: Optional predicate URI the field maps to.
        reason: Optional free-text justification.
        batch_id: Shared id linking the edits of one submit (new_batch_id()).

    Returns:
        The change resource URI.
    """
    change_uri = f"{CHANGE}change/{uuid.uuid4().hex[:8]}"
    g = GRAPH_CHANGES

    kg_store.add_triple(change_uri, f"{RDF}type", f"{CHANGE}Change", graph=g)
    kg_store.add_triple(
        change_uri, f"{CHANGE}targetSubject", target, graph=g,
    )
    kg_store.add_triple(
        change_uri, f"{CHANGE}targetGraph", target_graph or DEFAULT_GRAPH_MARKER,
        is_literal=True, graph=g,
    )
    kg_store.add_triple(
        change_uri, f"{CHANGE}entityKind", entity_kind, is_literal=True, graph=g,
    )
    kg_store.add_triple(
        change_uri, f"{CHANGE}field", field, is_literal=True, graph=g,
    )
    if predicate:
        kg_store.add_triple(
            change_uri, f"{CHANGE}predicate", predicate, graph=g,
        )
    if old is not None:
        kg_store.add_triple(
            change_uri, f"{CHANGE}oldValue", old, is_literal=True, graph=g,
        )
    kg_store.add_triple(
        change_uri, f"{CHANGE}newValue", new, is_literal=True, graph=g,
    )
    kg_store.add_triple(
        change_uri, f"{CHANGE}batch", batch_id or new_batch_id(),
        is_literal=True, graph=g,
    )
    if reason:
        kg_store.add_triple(
            change_uri, f"{CHANGE}reason", reason, is_literal=True, graph=g,
        )
    kg_store.add_triple(
        change_uri, f"{PROV}wasAttributedTo", f"{AGENTS}{changed_by}", graph=g,
    )
    kg_store.add_triple(
        change_uri, f"{PROV}atTime",
        datetime.now(timezone.utc).isoformat(),
        datatype=f"{XSD}dateTime", graph=g,
    )

    logger.info(
        "record_change %s %s.%s by %s", entity_kind, target, field, changed_by,
    )
    return change_uri


_SELECT_BODY = (
    "  ?c a <{change}Change> ;\n"
    "     <{change}targetSubject> ?target ;\n"
    "     <{change}entityKind> ?kind ;\n"
    "     <{change}field> ?field ;\n"
    "     <{change}newValue> ?new ;\n"
    "     <{change}batch> ?batch ;\n"
    "     <{prov}atTime> ?at .\n"
    "  OPTIONAL {{ ?c <{change}oldValue> ?old }}\n"
    "  OPTIONAL {{ ?c <{change}reason> ?reason }}\n"
    "  OPTIONAL {{ ?c <{prov}wasAttributedTo> ?by }}\n"
)


def _rows_to_dicts(bindings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for b in bindings:
        by = b.get("by") or ""
        rows.append({
            "change_uri": b.get("c", ""),
            "target": b.get("target", ""),
            "entity_kind": b.get("kind", ""),
            "field": b.get("field", ""),
            "old": b.get("old") if "old" in b and b.get("old") is not None else None,
            "new": b.get("new", ""),
            "batch": b.get("batch", ""),
            "at": b.get("at", ""),
            "by": by[len(AGENTS):] if by.startswith(AGENTS) else by,
            "reason": b.get("reason") or None,
        })
    return rows


def get_history(
    kg_store: KnowledgeGraphStore,
    target: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Change history for one resource, most recent first."""
    return get_history_for_targets(kg_store, [target], limit=limit)


def get_history_for_targets(
    kg_store: KnowledgeGraphStore,
    targets: list[str],
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Change history across several resources (e.g. a PRD requirement's
    fact URIs), most recent first."""
    if not targets:
        return []
    values = " ".join(f"<{t}>" for t in targets)
    body = _SELECT_BODY.format(change=CHANGE, prov=PROV)
    query = (
        f"SELECT ?c ?target ?kind ?field ?old ?new ?batch ?at ?by ?reason\n"
        f"WHERE {{ GRAPH <{GRAPH_CHANGES}> {{\n"
        f"  VALUES ?target {{ {values} }}\n"
        f"{body}"
        f"}} }}\n"
        f"ORDER BY DESC(?at) DESC(?c)\n"
        f"LIMIT {int(limit)}"
    )
    return _rows_to_dicts(kg_store.query(query).bindings)


def recent_changes(
    kg_store: KnowledgeGraphStore,
    limit: int = 100,
    entity_kind: str | None = None,
) -> list[dict[str, Any]]:
    """Global changelog feed, most recent first, optionally kind-filtered."""
    body = _SELECT_BODY.format(change=CHANGE, prov=PROV)
    kind_filter = (
        f'  FILTER(?kind = "{_escape(entity_kind)}")\n' if entity_kind else ""
    )
    query = (
        f"SELECT ?c ?target ?kind ?field ?old ?new ?batch ?at ?by ?reason\n"
        f"WHERE {{ GRAPH <{GRAPH_CHANGES}> {{\n"
        f"{body}"
        f"{kind_filter}"
        f"}} }}\n"
        f"ORDER BY DESC(?at) DESC(?c)\n"
        f"LIMIT {int(limit)}"
    )
    return _rows_to_dicts(kg_store.query(query).bindings)
