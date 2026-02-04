"""
LLM Analysis - AI-powered idea analysis tools.

Requires ANTHROPIC_API_KEY environment variable.
Uses Claude for novelty checking, related idea discovery,
category extraction, idea merging, and TODO extraction.
"""

import os
import re
import logging
from typing import Any

from .store import KnowledgeGraphStore, NAMESPACES
from .ideas import IdeasStore, Idea

logger = logging.getLogger(__name__)

IDEAS = NAMESPACES["ideas"]
IDEA = NAMESPACES["idea"]
SKOS = NAMESPACES["skos"]


class LlmAnalysis:
    """AI-powered idea analysis using Claude."""

    def __init__(self, store: KnowledgeGraphStore, ideas_store: IdeasStore):
        self._store = store
        self._ideas = ideas_store
        self._client = None

    def _get_client(self):
        """Lazy-load Anthropic client."""
        if self._client is None:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "ANTHROPIC_API_KEY not set. "
                    "LLM analysis tools require an API key."
                )
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=api_key)
            except ImportError:
                raise RuntimeError(
                    "anthropic package not installed. "
                    "Install with: pip install anthropic"
                )
        return self._client

    def _get_all_ideas_summary(self) -> str:
        """Get a summary of all existing ideas for context."""
        ideas = self._ideas.list_ideas(limit=200)
        lines = []
        for i in ideas:
            idea = self._ideas.get_idea(i["id"])
            if idea:
                desc = idea.description[:200] if idea.description else ""
                lines.append(f"- [{idea.id}] {idea.title} ({idea.lifecycle}): {desc}")
        return "\n".join(lines)

    def check_novelty(self, title: str, description: str) -> dict[str, Any]:
        """Check if a proposed idea is novel or overlaps with existing ideas."""
        client = self._get_client()

        existing = self._get_all_ideas_summary()

        prompt = f"""Analyze whether this proposed idea is novel compared to existing ideas.

EXISTING IDEAS:
{existing}

PROPOSED IDEA:
Title: {title}
Description: {description}

Respond with:
1. VERDICT: "novel", "overlaps", or "duplicate"
2. OVERLAPPING_IDEAS: List any idea IDs that share concepts (empty if novel)
3. EXPLANATION: Brief explanation of your assessment
4. RECOMMENDATION: "create_new", "merge_with_existing", or "note_as_variant"

Format as structured text."""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = message.content[0].text

        return {
            "title": title,
            "analysis": response_text,
            "model": "claude-sonnet-4-20250514",
        }

    def find_related_ideas(
        self,
        idea_id: str,
        refresh: bool = False,
    ) -> dict[str, Any]:
        """Find and explain relationships between ideas using LLM."""
        if not idea_id.startswith("idea-"):
            idea_id = f"idea-{idea_id}"

        idea = self._ideas.get_idea(idea_id)
        if not idea:
            return {"error": f"Idea not found: {idea_id}"}

        # Check existing relations unless refresh requested
        if not refresh and idea.related:
            return {
                "id": idea_id,
                "related": idea.related,
                "source": "cached",
            }

        client = self._get_client()
        existing = self._get_all_ideas_summary()

        prompt = f"""Given this idea and all existing ideas, identify the most related ones.

TARGET IDEA:
- ID: {idea.id}
- Title: {idea.title}
- Description: {idea.description}
- Content: {(idea.content or "")[:2000]}

ALL IDEAS:
{existing}

List up to 5 most related ideas with:
1. IDEA_ID (e.g., idea-3)
2. RELATIONSHIP_TYPE: one of "extends", "enables", "contradicts", "complements", "prerequisite", "alternative"
3. EXPLANATION: One sentence explaining the relationship

Format each as: IDEA_ID | TYPE | EXPLANATION"""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = message.content[0].text

        # Parse relationships and persist as RDF triples
        new_related = []
        for line in response_text.strip().split("\n"):
            parts = line.split("|")
            if len(parts) >= 2:
                related_id = parts[0].strip()
                match = re.match(r"idea-\d+[a-z]?", related_id)
                if match:
                    related_id = match.group(0)
                    self._store.add_triple(
                        f"{IDEAS}{idea_id}",
                        f"{SKOS}related",
                        f"{IDEAS}{related_id}",
                    )
                    new_related.append(related_id)

        self._store.flush()

        return {
            "id": idea_id,
            "related": new_related,
            "analysis": response_text,
            "source": "llm",
        }

    def discover_categories(self, refresh: bool = False) -> dict[str, Any]:
        """AI discovers emergent categories from idea content."""
        client = self._get_client()
        existing = self._get_all_ideas_summary()

        prompt = f"""Analyze these ideas and discover natural categories/themes.

IDEAS:
{existing}

Group the ideas into 5-10 emergent categories. For each category:
1. CATEGORY_NAME: Short, descriptive name
2. DESCRIPTION: What ideas in this category have in common
3. IDEA_IDS: List of idea IDs that belong (e.g., idea-1, idea-5)

Format each as:
CATEGORY: name
DESCRIPTION: description
IDEAS: id1, id2, id3"""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = message.content[0].text

        return {
            "categories": response_text,
            "source": "llm",
            "model": "claude-sonnet-4-20250514",
        }

    def merge_ideas(
        self,
        idea_ids: list[str],
        new_title: str,
        author: str = "AI",
    ) -> dict[str, Any]:
        """Merge multiple ideas into a single synthesized idea."""
        # Normalize IDs
        idea_ids = [
            f"idea-{i}" if not i.startswith("idea-") else i
            for i in idea_ids
        ]

        # Read all ideas
        ideas = []
        for idea_id in idea_ids:
            idea = self._ideas.get_idea(idea_id)
            if idea:
                ideas.append(idea)

        if len(ideas) < 2:
            return {"error": "Need at least 2 valid ideas to merge"}

        client = self._get_client()

        ideas_text = "\n\n".join(
            f"## {idea.id}: {idea.title}\n{idea.content or idea.description}"
            for idea in ideas
        )

        prompt = f"""Synthesize these ideas into a single coherent idea.

IDEAS TO MERGE:
{ideas_text}

NEW TITLE: {new_title}

Create a comprehensive merged description that:
1. Captures the key insights from each original idea
2. Resolves any contradictions
3. Identifies synergies
4. Provides a unified vision

Write the merged content in markdown format."""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}],
        )

        merged_content = message.content[0].text

        # Create new idea
        new_id = self._ideas.get_next_id()
        merged_idea = Idea(
            id=new_id,
            title=new_title,
            description=merged_content[:500],
            content=merged_content,
            author=author,
            lifecycle="backlog",
            related=idea_ids,
        )

        try:
            uri = self._ideas.create_idea(merged_idea)

            # Mark originals as related to merged
            for idea_id in idea_ids:
                self._store.add_triple(
                    f"{IDEAS}{idea_id}",
                    f"{SKOS}related",
                    f"{IDEAS}{new_id}",
                )
            self._store.flush()

            return {
                "status": "merged",
                "new_id": new_id,
                "uri": uri,
                "merged_from": idea_ids,
                "title": new_title,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def extract_todos(self, idea_id: str | None = None) -> dict[str, Any]:
        """Extract TODO items from idea content (markdown checkboxes)."""
        if idea_id:
            if not idea_id.startswith("idea-"):
                idea_id = f"idea-{idea_id}"
            idea = self._ideas.get_idea(idea_id)
            if not idea:
                return {"error": f"Idea not found: {idea_id}"}
            ideas = [idea]
        else:
            # All ideas
            all_ideas = self._ideas.list_ideas(limit=1000)
            ideas = []
            for i in all_ideas:
                idea = self._ideas.get_idea(i["id"])
                if idea:
                    ideas.append(idea)

        todos: list[dict[str, Any]] = []
        for idea in ideas:
            content = idea.content or ""
            # Match markdown checkboxes
            for match in re.finditer(r"^[\s]*[-*]\s*\[([ xX])\]\s*(.+)$", content, re.MULTILINE):
                checked = match.group(1).lower() == "x"
                text = match.group(2).strip()
                todos.append({
                    "idea_id": idea.id,
                    "idea_title": idea.title,
                    "text": text,
                    "done": checked,
                })

        done_count = sum(1 for t in todos if t["done"])
        return {
            "total": len(todos),
            "done": done_count,
            "pending": len(todos) - done_count,
            "todos": todos,
        }

    def list_by_author(
        self,
        author: str | None = None,
        agent: str | None = None,
        include_seeds: bool = True,
    ) -> list[dict[str, Any]]:
        """List ideas filtered by author and/or agent."""
        filters = []
        if author:
            filters.append(f'FILTER(?author = "{author}")')
        if agent:
            filters.append(f'FILTER(?agent = "{agent}")')
        if not include_seeds:
            filters.append(f"FILTER NOT EXISTS {{ ?idea a <{IDEA}Seed> }}")

        filter_clause = "\n".join(filters)

        query = f"""
        SELECT DISTINCT ?idea ?title ?lifecycle ?author ?agent ?created
        WHERE {{
            ?idea a skos:Concept ;
                  skos:inScheme <{IDEA}IdeaPool> ;
                  skos:prefLabel ?title .
            OPTIONAL {{ ?idea idea:lifecycle ?lifecycle }}
            OPTIONAL {{ ?idea dcterms:creator ?author }}
            OPTIONAL {{ ?idea idea:agent ?agent }}
            OPTIONAL {{ ?idea dcterms:created ?created }}
            {filter_clause}
        }}
        ORDER BY DESC(?created)
        """

        results = self._store.query(query)
        return [
            {
                "id": r["idea"].replace(IDEAS, ""),
                "title": r.get("title", ""),
                "lifecycle": r.get("lifecycle", "seed"),
                "author": r.get("author", "unknown"),
                "agent": r.get("agent"),
                "created": r.get("created"),
            }
            for r in results
        ]
