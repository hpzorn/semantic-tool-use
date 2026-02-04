"""
Lifecycle Manager - Ralph workflow state machine.

Manages the 12+1 lifecycle states and valid transitions for ideas:
  seed → backlog → researching → researched → scoped → implementing → completed
                       ↓            ↓                       ↓
                  invalidated    parked                  blocked/failed

Also supports sprout state (crystallized seed).
"""

import logging
from datetime import datetime, timezone
from typing import Any

from .store import KnowledgeGraphStore, NAMESPACES
from .ideas import IdeasStore, Idea

logger = logging.getLogger(__name__)

IDEAS = NAMESPACES["ideas"]
IDEA = NAMESPACES["idea"]

# Ralph Lifecycle States
RALPH_LIFECYCLES = [
    "seed",         # Raw captured thought (in seeds/)
    "sprout",       # Crystallized seed, basic idea
    "backlog",      # Queued, ready for Ralph to pick
    "researching",  # Academic groundwork in progress
    "researched",   # Research complete, ready for breakdown
    "invalidated",  # Dead end (prior art, flawed premise)
    "parked",       # Paused, needs human input
    "decomposing",  # Breaking into sub-ideas
    "scoped",       # PRD created, ready for implementation
    "implementing", # Ralph loop active
    "blocked",      # Implementation stuck, needs resolution
    "completed",    # Successfully implemented
    "failed",       # Implementation failed after retries
]

# Valid lifecycle transitions
LIFECYCLE_TRANSITIONS: dict[str, list[str]] = {
    "seed": ["backlog", "sprout"],
    "sprout": ["backlog"],
    "backlog": ["researching"],
    "researching": ["researched", "invalidated", "parked"],
    "researched": ["decomposing", "scoped"],
    "invalidated": [],  # Terminal
    "parked": ["backlog", "researching"],
    "decomposing": ["scoped"],  # Also spawns children to backlog
    "scoped": ["implementing"],
    "implementing": ["completed", "failed", "blocked"],
    "blocked": ["backlog", "implementing"],
    "completed": [],  # Terminal (but can reopen)
    "failed": ["backlog"],  # Can retry
}


class LifecycleManager:
    """Manages lifecycle state transitions for ideas."""

    def __init__(self, store: KnowledgeGraphStore, ideas_store: IdeasStore):
        self._store = store
        self._ideas = ideas_store

    def set_lifecycle(
        self,
        idea_id: str,
        new_state: str,
        reason: str = "",
    ) -> dict[str, Any]:
        """
        Transition an idea to a new lifecycle state.

        Validates that the transition is allowed.
        """
        if not idea_id.startswith("idea-") and not idea_id.startswith("seed-"):
            idea_id = f"idea-{idea_id}"

        idea = self._ideas.get_idea(idea_id)
        if not idea:
            return {"error": f"Idea not found: {idea_id}"}

        current = idea.lifecycle
        if new_state not in RALPH_LIFECYCLES:
            return {
                "error": f"Invalid state: {new_state}",
                "valid_states": RALPH_LIFECYCLES,
            }

        allowed = LIFECYCLE_TRANSITIONS.get(current, [])
        if new_state not in allowed:
            return {
                "error": f"Cannot transition from '{current}' to '{new_state}'",
                "allowed_transitions": allowed,
                "current_state": current,
            }

        idea.lifecycle = new_state
        idea.lifecycle_updated = datetime.now(timezone.utc)
        idea.lifecycle_reason = reason

        self._ideas.update_idea(idea)

        return {
            "status": "updated",
            "id": idea_id,
            "previous_state": current,
            "new_state": new_state,
            "reason": reason,
        }

    def get_workable_ideas(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get ideas in backlog that are not blocked."""
        query = f"""
        SELECT DISTINCT ?idea ?title ?priority ?created
        WHERE {{
            ?idea a skos:Concept ;
                  skos:inScheme <{IDEA}IdeaPool> ;
                  skos:prefLabel ?title ;
                  idea:lifecycle "backlog" .
            OPTIONAL {{ ?idea idea:priority ?priority }}
            OPTIONAL {{ ?idea dcterms:created ?created }}
            FILTER NOT EXISTS {{ ?idea idea:blockedBy ?blocker }}
        }}
        ORDER BY ASC(?priority) DESC(?created)
        LIMIT {limit}
        """
        results = self._store.query(query)
        return [
            {
                "id": r["idea"].replace(IDEAS, ""),
                "title": r.get("title", ""),
                "priority": r.get("priority"),
                "created": r.get("created"),
            }
            for r in results
        ]

    def get_ralph_status(self) -> dict[str, Any]:
        """Get overall workflow status dashboard."""
        counts: dict[str, int] = {}
        for state in RALPH_LIFECYCLES:
            counts[state] = self._ideas.count_ideas(lifecycle=state)

        total = sum(counts.values())

        # Get blocked ideas details
        blocked_query = f"""
        SELECT ?idea ?title ?blocker ?blockerTitle
        WHERE {{
            ?idea idea:lifecycle "blocked" ;
                  skos:prefLabel ?title .
            OPTIONAL {{
                ?idea idea:blockedBy ?blocker .
                ?blocker skos:prefLabel ?blockerTitle .
            }}
        }}
        """
        blocked_results = self._store.query(blocked_query)
        blocked_details = [
            {
                "id": r["idea"].replace(IDEAS, ""),
                "title": r.get("title", ""),
                "blocked_by": r.get("blocker", "").replace(IDEAS, "") if r.get("blocker") else None,
                "blocker_title": r.get("blockerTitle"),
            }
            for r in blocked_results
        ]

        return {
            "total_ideas": total,
            "by_lifecycle": counts,
            "active": counts.get("researching", 0) + counts.get("implementing", 0) + counts.get("decomposing", 0),
            "ready": counts.get("backlog", 0),
            "blocked_count": counts.get("blocked", 0),
            "blocked_details": blocked_details,
            "completed": counts.get("completed", 0),
            "terminal": counts.get("invalidated", 0) + counts.get("completed", 0),
        }

    def get_ideas_by_lifecycle(self, lifecycle: str) -> list[dict[str, Any]]:
        """List ideas in a specific lifecycle state."""
        if lifecycle not in RALPH_LIFECYCLES:
            return [{"error": f"Invalid lifecycle: {lifecycle}", "valid": RALPH_LIFECYCLES}]
        return self._ideas.get_ideas_by_lifecycle(lifecycle)

    def move_to_backlog(self, idea_id: str, priority: int | None = None) -> dict[str, Any]:
        """Promote an idea to backlog with optional priority."""
        if not idea_id.startswith("idea-") and not idea_id.startswith("seed-"):
            idea_id = f"idea-{idea_id}"

        idea = self._ideas.get_idea(idea_id)
        if not idea:
            return {"error": f"Idea not found: {idea_id}"}

        current = idea.lifecycle
        allowed = LIFECYCLE_TRANSITIONS.get(current, [])
        if "backlog" not in allowed:
            return {
                "error": f"Cannot move to backlog from '{current}'",
                "allowed_transitions": allowed,
            }

        idea.lifecycle = "backlog"
        idea.lifecycle_updated = datetime.now(timezone.utc)
        idea.lifecycle_reason = "Moved to backlog"
        if priority is not None:
            idea.priority = priority

        self._ideas.update_idea(idea)

        return {
            "status": "moved_to_backlog",
            "id": idea_id,
            "priority": priority,
        }

    def check_parent_completion(self, idea_id: str) -> dict[str, Any]:
        """Check if all children of an idea are completed/invalidated."""
        if not idea_id.startswith("idea-"):
            idea_id = f"idea-{idea_id}"

        idea = self._ideas.get_idea(idea_id)
        if not idea:
            return {"error": f"Idea not found: {idea_id}"}

        if not idea.children:
            return {
                "id": idea_id,
                "has_children": False,
                "can_complete": True,
                "message": "No children — parent can be completed",
            }

        children_status = []
        all_done = True
        for child_id in idea.children:
            child = self._ideas.get_idea(child_id)
            if child:
                done = child.lifecycle in ("completed", "invalidated")
                children_status.append({
                    "id": child_id,
                    "title": child.title,
                    "lifecycle": child.lifecycle,
                    "done": done,
                })
                if not done:
                    all_done = False

        return {
            "id": idea_id,
            "has_children": True,
            "children_count": len(idea.children),
            "children": children_status,
            "all_children_done": all_done,
            "can_complete": all_done,
        }

    def add_dependency(
        self,
        idea_id: str,
        blocks: str | None = None,
        blocked_by: str | None = None,
    ) -> dict[str, Any]:
        """Add dependency relationships between ideas."""
        if not idea_id.startswith("idea-"):
            idea_id = f"idea-{idea_id}"

        idea = self._ideas.get_idea(idea_id)
        if not idea:
            return {"error": f"Idea not found: {idea_id}"}

        uri = idea.uri
        added = []

        if blocks:
            for bid in [b.strip() for b in blocks.split(",")]:
                if not bid.startswith("idea-"):
                    bid = f"idea-{bid}"
                # Add blocks triple
                self._store.add_triple(uri, f"{IDEA}blocks", f"{IDEAS}{bid}")
                # Add inverse blockedBy
                self._store.add_triple(f"{IDEAS}{bid}", f"{IDEA}blockedBy", uri)
                added.append(f"{idea_id} blocks {bid}")

        if blocked_by:
            for bid in [b.strip() for b in blocked_by.split(",")]:
                if not bid.startswith("idea-"):
                    bid = f"idea-{bid}"
                self._store.add_triple(uri, f"{IDEA}blockedBy", f"{IDEAS}{bid}")
                self._store.add_triple(f"{IDEAS}{bid}", f"{IDEA}blocks", uri)
                added.append(f"{idea_id} blocked by {bid}")

        self._store.flush()

        return {
            "status": "dependencies_added",
            "id": idea_id,
            "added": added,
        }

    def remove_dependency(
        self,
        idea_id: str,
        blocks: str | None = None,
        blocked_by: str | None = None,
    ) -> dict[str, Any]:
        """Remove dependency relationships between ideas."""
        if not idea_id.startswith("idea-"):
            idea_id = f"idea-{idea_id}"

        uri = f"{IDEAS}{idea_id}"
        removed = []

        if blocks:
            for bid in [b.strip() for b in blocks.split(",")]:
                if not bid.startswith("idea-"):
                    bid = f"idea-{bid}"
                self._store.remove_triple(uri, f"{IDEA}blocks", f"{IDEAS}{bid}")
                self._store.remove_triple(f"{IDEAS}{bid}", f"{IDEA}blockedBy", uri)
                removed.append(f"{idea_id} no longer blocks {bid}")

        if blocked_by:
            for bid in [b.strip() for b in blocked_by.split(",")]:
                if not bid.startswith("idea-"):
                    bid = f"idea-{bid}"
                self._store.remove_triple(uri, f"{IDEA}blockedBy", f"{IDEAS}{bid}")
                self._store.remove_triple(f"{IDEAS}{bid}", f"{IDEA}blocks", uri)
                removed.append(f"{idea_id} no longer blocked by {bid}")

        self._store.flush()

        return {
            "status": "dependencies_removed",
            "id": idea_id,
            "removed": removed,
        }

    def get_idea_dependencies(self, idea_id: str) -> dict[str, Any]:
        """Get all dependency relationships for an idea."""
        if not idea_id.startswith("idea-"):
            idea_id = f"idea-{idea_id}"

        idea = self._ideas.get_idea(idea_id)
        if not idea:
            return {"error": f"Idea not found: {idea_id}"}

        return {
            "id": idea_id,
            "title": idea.title,
            "lifecycle": idea.lifecycle,
            "parent": idea.parent,
            "children": idea.children,
            "blocks": idea.blocks,
            "blocked_by": idea.blocked_by,
            "related": idea.related,
        }

    def create_sub_idea(
        self,
        parent_id: str,
        title: str,
        description: str = "",
        content: str = "",
        author: str = "AI",
    ) -> dict[str, Any]:
        """Create a child idea linked to a parent."""
        if not parent_id.startswith("idea-"):
            parent_id = f"idea-{parent_id}"

        parent = self._ideas.get_idea(parent_id)
        if not parent:
            return {"error": f"Parent idea not found: {parent_id}"}

        new_id = self._ideas.get_next_id()

        child = Idea(
            id=new_id,
            title=title,
            description=description,
            content=content,
            author=author,
            lifecycle="backlog",
            parent=parent_id,
        )

        try:
            uri = self._ideas.create_idea(child)
            return {
                "status": "created",
                "id": new_id,
                "parent": parent_id,
                "uri": uri,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
