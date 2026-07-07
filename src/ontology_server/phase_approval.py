"""HITL phase-approval core (framework-agnostic).

A phase definition carrying ``phase:requiresApproval "true"`` makes
``record_phase_result`` write its validated output with
``phase:approvalStatus "pending"``.  The functions here implement the human
side of that gate: reviewing (optionally editing) the output in the
dashboard, approving or rejecting it, and letting the orchestrator long-poll
the decision.

Both the REST endpoints (api/routes/phases.py) and the dashboard
(dashboard/routes.py) call these functions; the MCP surface exposes ONLY
``await_approval`` — approve/reject must never be callable by agents.

Import direction: this module imports from ``mcp.phase_tools``;
``phase_tools`` imports this module only lazily inside its tool closure.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from ontology_server.mcp.phase_tools import (
    OntologyClient,
    PipelineDataError,
    SparqlClient,
    _allowed_intent_fields,
    _run_shacl_gate,
    _sparql_escape_literal,
)
from ontology_server.phase_constants import (
    APPROVAL_APPROVED,
    APPROVAL_PENDING,
    APPROVAL_REJECTED,
    APPROVAL_STATUS_PRED,
    EDITED_BY_REVIEWER_PRED,
    PHASE_NS,
    PHASES_GRAPH,
    RECORDED_AT_PRED,
    REQUIRES_APPROVAL_PRED,
    REVIEW_COMMENT_PRED,
    REVIEWED_AT_PRED,
    REVIEWED_BY_PRED,
    _PRESERVES_PREFIX,
)

logger = logging.getLogger(__name__)


class ApprovalConflictError(RuntimeError):
    """Raised when a decision targets an output not awaiting review."""


def _normalise_idea_id(idea_id: str) -> str:
    if not idea_id.startswith("idea-"):
        return f"idea-{idea_id}"
    return idea_id


def _output_subject(idea_id: str, phase_id: str) -> str:
    return f"{PHASE_NS}{_normalise_idea_id(idea_id)}-{phase_id}"


def get_approval(
    sparql: SparqlClient,
    idea_id: str,
    phase_id: str,
) -> dict[str, Any] | None:
    """Return the approval state of a recorded phase output.

    ``None`` when no output subject exists.  An output without an
    approvalStatus triple (recorded before HITL existed) reports "approved".
    """
    subject = _output_subject(idea_id, phase_id)
    query = (
        f"SELECT ?p ?o WHERE {{\n"
        f"  GRAPH <{PHASES_GRAPH}> {{ <{subject}> ?p ?o . }}\n"
        f"}}"
    )
    try:
        result = sparql.sparql_query(query)
    except Exception as exc:
        raise PipelineDataError(f"get_approval: {exc}") from exc
    bindings = result.get("results", []) if isinstance(result, dict) else []
    if not bindings:
        return None

    by_pred = {str(b.get("p", "")): str(b.get("o", "")) for b in bindings}
    return {
        "idea_id": _normalise_idea_id(idea_id),
        "phase_id": phase_id,
        "status": by_pred.get(APPROVAL_STATUS_PRED, APPROVAL_APPROVED),
        "comment": by_pred.get(REVIEW_COMMENT_PRED),
        "recorded_at": by_pred.get(RECORDED_AT_PRED),
        "reviewed_at": by_pred.get(REVIEWED_AT_PRED),
        "reviewed_by": by_pred.get(REVIEWED_BY_PRED),
    }


def _get_preserves_fields(
    sparql: SparqlClient,
    subject: str,
) -> dict[str, str]:
    """Return {field-name: literal} for every phase:preserves-* triple."""
    query = (
        f"SELECT ?p ?o WHERE {{\n"
        f"  GRAPH <{PHASES_GRAPH}> {{ <{subject}> ?p ?o . }}\n"
        f"}}"
    )
    result = sparql.sparql_query(query)
    bindings = result.get("results", []) if isinstance(result, dict) else []
    fields: dict[str, str] = {}
    for b in bindings:
        pred = str(b.get("p", ""))
        if pred.startswith(_PRESERVES_PREFIX):
            fields[pred[len(_PRESERVES_PREFIX):]] = str(b.get("o", ""))
    return fields


def _set_review_metadata(
    ontology: OntologyClient,
    subject: str,
    status: str,
    *,
    comment: str | None,
    reviewed_by: str,
) -> None:
    """Remove-then-add the decision triples on the output subject."""
    for pred in (
        APPROVAL_STATUS_PRED,
        REVIEW_COMMENT_PRED,
        REVIEWED_AT_PRED,
        REVIEWED_BY_PRED,
    ):
        ontology.remove_triples(subject, pred)
    ontology.add_triple(subject, APPROVAL_STATUS_PRED, status, is_literal=True)
    if comment:
        ontology.add_triple(
            subject, REVIEW_COMMENT_PRED, comment, is_literal=True,
        )
    ontology.add_triple(
        subject,
        REVIEWED_AT_PRED,
        datetime.now(timezone.utc).isoformat(),
        is_literal=True,
    )
    ontology.add_triple(subject, REVIEWED_BY_PRED, reviewed_by, is_literal=True)


def _apply_field_edits(
    ontology: OntologyClient,
    sparql: SparqlClient,
    phase_id: str,
    subject: str,
    edited_fields: dict[str, str],
) -> tuple[dict[str, str], list[str]]:
    """Rewrite edited preserves-* literals, re-run the SHACL gate.

    Returns ``(snapshot, violations)``.  On violations the caller must
    restore the snapshot — the pending output has to survive a failed edit.
    Raises ValueError on non-allowlisted field names or a JSON-typed field
    edited to something unparseable.
    """
    allowed = _allowed_intent_fields(phase_id)
    current = _get_preserves_fields(sparql, subject)

    for name, new_value in edited_fields.items():
        if allowed is not None and name not in allowed:
            raise ValueError(
                f"field {name!r} is not in the {phase_id} allowlist"
            )
        old_value = current.get(name)
        if old_value is not None:
            try:
                json.loads(old_value)
                was_json = True
            except (ValueError, TypeError):
                was_json = False
            if was_json:
                try:
                    json.loads(new_value)
                except (ValueError, TypeError) as exc:
                    raise ValueError(
                        f"field {name!r} holds JSON but the edited value "
                        f"does not parse: {exc}"
                    ) from exc

    snapshot = {
        name: current[name] for name in edited_fields if name in current
    }
    for name, new_value in edited_fields.items():
        ontology.remove_triples(subject, f"{_PRESERVES_PREFIX}{name}")
        ontology.add_triple(
            subject, f"{_PRESERVES_PREFIX}{name}", new_value, is_literal=True,
        )

    violations = _run_shacl_gate(ontology, phase_id, subject) or []
    return snapshot, violations


def _restore_snapshot(
    ontology: OntologyClient,
    subject: str,
    edited_fields: dict[str, str],
    snapshot: dict[str, str],
) -> None:
    # Per-predicate restore — never remove_triples_by_subject here: that is
    # record-time rollback semantics; a failed EDIT must leave the pending
    # output intact for another attempt.
    for name in edited_fields:
        ontology.remove_triples(subject, f"{_PRESERVES_PREFIX}{name}")
        if name in snapshot:
            ontology.add_triple(
                subject,
                f"{_PRESERVES_PREFIX}{name}",
                snapshot[name],
                is_literal=True,
            )


def approve_phase(
    ontology: OntologyClient,
    sparql: SparqlClient,
    idea_id: str,
    phase_id: str,
    *,
    reviewed_by: str = "dashboard",
    comment: str | None = None,
    edited_fields: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Approve a pending/rejected phase output, optionally editing fields.

    Edited fields are re-validated against the phase's SHACL gate before the
    approval lands; on violations the original literals are restored and
    ``{"ok": False, "violations": [...]}`` is returned.
    """
    subject = _output_subject(idea_id, phase_id)
    state = get_approval(sparql, idea_id, phase_id)
    if state is None:
        raise ApprovalConflictError(
            f"no phase output recorded for {idea_id}/{phase_id}"
        )
    if state["status"] not in (APPROVAL_PENDING, APPROVAL_REJECTED):
        raise ApprovalConflictError(
            f"{idea_id}/{phase_id} is {state['status']!r}, not awaiting review"
        )

    edited = bool(edited_fields)
    if edited_fields:
        snapshot, violations = _apply_field_edits(
            ontology, sparql, phase_id, subject, edited_fields,
        )
        if violations:
            _restore_snapshot(ontology, subject, edited_fields, snapshot)
            logger.warning(
                "approve_phase edit failed SHACL gate for %s: %s",
                subject, "; ".join(violations),
            )
            return {
                "ok": False,
                "violations": violations,
                "status": state["status"],
            }

    _set_review_metadata(
        ontology, subject, APPROVAL_APPROVED,
        comment=comment, reviewed_by=reviewed_by,
    )
    if edited:
        ontology.remove_triples(subject, EDITED_BY_REVIEWER_PRED)
        ontology.add_triple(
            subject, EDITED_BY_REVIEWER_PRED, "true", is_literal=True,
        )
    logger.info(
        "approve_phase %s/%s by %s (edited=%s)",
        idea_id, phase_id, reviewed_by, edited,
    )
    return {"ok": True, "violations": [], "status": APPROVAL_APPROVED}


def reject_phase(
    ontology: OntologyClient,
    sparql: SparqlClient,
    idea_id: str,
    phase_id: str,
    comment: str,
    *,
    reviewed_by: str = "dashboard",
) -> dict[str, Any]:
    """Reject a pending phase output with mandatory feedback.

    The output stays in the graph as status "rejected" so the orchestrator
    can read the comment and re-dispatch the phase agent; the agent re-run's
    idempotent cleanup in record_phase_result replaces the whole subject.
    """
    if not comment or not comment.strip():
        raise ValueError("a rejection requires a feedback comment")
    subject = _output_subject(idea_id, phase_id)
    state = get_approval(sparql, idea_id, phase_id)
    if state is None:
        raise ApprovalConflictError(
            f"no phase output recorded for {idea_id}/{phase_id}"
        )
    if state["status"] != APPROVAL_PENDING:
        raise ApprovalConflictError(
            f"{idea_id}/{phase_id} is {state['status']!r}, not pending"
        )

    _set_review_metadata(
        ontology, subject, APPROVAL_REJECTED,
        comment=comment.strip(), reviewed_by=reviewed_by,
    )
    logger.info("reject_phase %s/%s by %s", idea_id, phase_id, reviewed_by)
    return {"ok": True, "violations": [], "status": APPROVAL_REJECTED}


def set_requires_approval(
    ontology: OntologyClient,
    phase_id: str,
    required: bool,
) -> dict[str, Any]:
    """Toggle the phase:requiresApproval flag on a phase definition.

    NOTE: the flag lives on the trig-declared phase:{phase_id} subject, so a
    future phase-content re-seed (next probe bump) restores ship defaults.
    """
    subject = f"{PHASE_NS}{phase_id}"
    ontology.remove_triples(subject, REQUIRES_APPROVAL_PRED)
    ontology.add_triple(
        subject,
        REQUIRES_APPROVAL_PRED,
        "true" if required else "false",
        is_literal=True,
    )
    return {"phase_id": phase_id, "requires_approval": required}


async def await_approval(
    sparql: SparqlClient,
    idea_id: str,
    phase_id: str,
    *,
    timeout_s: float = 50,
    poll_interval: float = 2.0,
) -> dict[str, Any]:
    """Long-poll the approval decision for a phase output.

    Returns as soon as the status is approved/rejected; "missing"
    immediately when no output subject exists (the caller should re-check
    the graph — a re-recording agent deletes and rewrites the subject);
    "pending" when timeout_s elapses.  timeout_s is clamped to 1–110 s to
    stay under request/proxy timeouts; callers loop for longer waits.
    """
    timeout_s = max(1.0, min(110.0, float(timeout_s)))
    poll_interval = max(0.1, float(poll_interval))
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s

    while True:
        state = get_approval(sparql, idea_id, phase_id)
        if state is None:
            return {"status": "missing", "comment": None}
        if state["status"] in (APPROVAL_APPROVED, APPROVAL_REJECTED):
            return {"status": state["status"], "comment": state["comment"]}
        if loop.time() >= deadline:
            return {"status": APPROVAL_PENDING, "comment": None}
        await asyncio.sleep(min(poll_interval, deadline - loop.time()))


def list_pending_approvals(sparql: SparqlClient) -> list[dict[str, Any]]:
    """All pending phase outputs across ideas, oldest first (queue order)."""
    query = (
        f"SELECT ?s ?phase_id ?idea_id ?recorded WHERE {{\n"
        f"  GRAPH <{PHASES_GRAPH}> {{\n"
        f'    ?s <{APPROVAL_STATUS_PRED}> "{_sparql_escape_literal(APPROVAL_PENDING)}" ;\n'
        f"       <{PHASE_NS}producedBy> ?phase_id ;\n"
        f"       <{PHASE_NS}forRequirement> ?idea_id .\n"
        f"    OPTIONAL {{ ?s <{RECORDED_AT_PRED}> ?recorded }}\n"
        f"  }}\n"
        f"}}\n"
        f"ORDER BY ?recorded"
    )
    result = sparql.sparql_query(query)
    bindings = result.get("results", []) if isinstance(result, dict) else []
    return [
        {
            "subject": str(b.get("s", "")),
            "phase_id": str(b.get("phase_id", "")),
            "idea_id": str(b.get("idea_id", "")),
            "recorded_at": str(b.get("recorded", "")) or None,
        }
        for b in bindings
    ]
