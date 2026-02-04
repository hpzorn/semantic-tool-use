"""
Seed Store - Zero-friction idea capture.

Seeds are ideas with rdf:type idea:Seed, timestamped IDs, and full content.
They can be crystallized into full ideas.
"""

import logging
import random
import string
from datetime import datetime, timezone
from typing import Any

from .store import KnowledgeGraphStore, NAMESPACES
from .ideas import IdeasStore, Idea

logger = logging.getLogger(__name__)

IDEAS = NAMESPACES["ideas"]
IDEA = NAMESPACES["idea"]


class SeedStore:
    """Store for seeds — zero-friction idea capture."""

    def __init__(self, store: KnowledgeGraphStore, ideas_store: IdeasStore):
        self._store = store
        self._ideas = ideas_store

    @staticmethod
    def _generate_seed_id() -> str:
        """Generate a timestamped seed ID: seed-YYYYMMDD-HHMMSS-xxxx."""
        now = datetime.now(timezone.utc)
        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
        return f"seed-{now.strftime('%Y%m%d-%H%M%S')}-{suffix}"

    def capture_seed(
        self,
        content: str,
        author: str = "hpz",
        agent: str | None = None,
    ) -> dict[str, Any]:
        """
        Instant brain dump — no title, no structure.

        Creates an idea:Seed with a timestamped ID and full content.
        """
        seed_id = self._generate_seed_id()
        now = datetime.now(timezone.utc)

        # Extract a title from the first line (truncated)
        first_line = content.strip().split("\n")[0][:100]
        title = first_line if first_line else "Untitled seed"

        idea = Idea(
            id=seed_id,
            title=title,
            content=content,
            description=first_line[:200],
            author=author,
            agent=agent,
            created=now,
            lifecycle="seed",
            is_seed=True,
            captured_at=now,
        )

        try:
            self._ideas.create_idea(idea)
            return {
                "status": "captured",
                "id": seed_id,
                "preview": first_line[:80],
                "timestamp": now.isoformat(),
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def list_seeds(
        self,
        limit: int = 20,
        today_only: bool = False,
    ) -> list[dict[str, Any]]:
        """List captured seeds with timestamps and previews."""
        today_filter = ""
        if today_only:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            today_filter = f"""
            ?seed idea:capturedAt ?captured .
            FILTER(STRSTARTS(STR(?captured), "{today}"))
            """

        query = f"""
        SELECT ?seed ?title ?author ?captured ?content
        WHERE {{
            ?seed a <{IDEA}Seed> ;
                  skos:prefLabel ?title .
            OPTIONAL {{ ?seed dcterms:creator ?author }}
            OPTIONAL {{ ?seed idea:capturedAt ?captured }}
            OPTIONAL {{ ?seed idea:content ?content }}
            {today_filter}
        }}
        ORDER BY DESC(?captured)
        LIMIT {limit}
        """

        results = self._store.query(query)
        seeds = []
        for r in results:
            content = r.get("content", "")
            preview = content[:120] + "..." if len(content) > 120 else content
            seeds.append({
                "id": r["seed"].replace(IDEAS, ""),
                "title": r.get("title", ""),
                "author": r.get("author", "unknown"),
                "captured_at": r.get("captured"),
                "preview": preview,
            })
        return seeds

    def read_seed(self, seed_id: str) -> dict[str, Any]:
        """Read a specific seed by ID."""
        if not seed_id.startswith("seed-"):
            seed_id = f"seed-{seed_id}"

        idea = self._ideas.get_idea(seed_id)
        if not idea:
            return {"error": f"Seed not found: {seed_id}"}

        return {
            "id": idea.id,
            "title": idea.title,
            "content": idea.content,
            "author": idea.author,
            "agent": idea.agent,
            "captured_at": idea.captured_at.isoformat() if idea.captured_at else None,
            "lifecycle": idea.lifecycle,
        }

    def crystallize_seed(
        self,
        seed_id: str,
        title: str,
        description: str = "",
        content: str = "",
        author: str = "AI",
        lifecycle: str = "sprout",
    ) -> dict[str, Any]:
        """
        Promote a seed to a full idea.

        Creates a new idea linked via idea:crystallizedFrom.
        """
        if not seed_id.startswith("seed-"):
            seed_id = f"seed-{seed_id}"

        seed = self._ideas.get_idea(seed_id)
        if not seed:
            return {"error": f"Seed not found: {seed_id}"}

        new_id = self._ideas.get_next_id()

        # Use seed content as base if no content provided
        if not content:
            content = seed.content

        idea = Idea(
            id=new_id,
            title=title,
            description=description,
            content=content,
            author=author,
            lifecycle=lifecycle,
            crystallized_from=seed_id,
            tags=seed.tags,  # inherit tags
        )

        try:
            uri = self._ideas.create_idea(idea)
            return {
                "status": "crystallized",
                "seed_id": seed_id,
                "idea_id": new_id,
                "uri": uri,
                "title": title,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
