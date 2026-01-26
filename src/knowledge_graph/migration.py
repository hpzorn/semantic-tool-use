"""
Migration script for importing ideas from markdown files to the knowledge graph.

Reads idea-*.md files with YAML frontmatter and creates RDF representations
using the SKOS+DC ontology.
"""

import re
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from .core.store import KnowledgeGraphStore
from .core.ideas import IdeasStore, Idea

logger = logging.getLogger(__name__)


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """
    Parse YAML frontmatter from markdown content.

    Args:
        content: Raw markdown content

    Returns:
        Tuple of (frontmatter dict, body content)
    """
    lines = content.strip().split('\n')

    if not lines or lines[0].strip() != '---':
        return {}, content

    frontmatter_lines = []
    body_start = 1

    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == '---':
            body_start = i + 1
            break
        frontmatter_lines.append(line)

    # Simple YAML parsing (key: value)
    frontmatter = {}
    for line in frontmatter_lines:
        if ':' in line:
            key, _, value = line.partition(':')
            key = key.strip()
            value = value.strip()
            # Handle simple lists [a, b, c]
            if value.startswith('[') and value.endswith(']'):
                value = [v.strip().strip('"\'') for v in value[1:-1].split(',') if v.strip()]
            frontmatter[key] = value

    body = '\n'.join(lines[body_start:]).strip()
    return frontmatter, body


def extract_title(body: str) -> str:
    """Extract title from markdown body (first H1 heading)."""
    for line in body.split('\n'):
        if line.startswith('# '):
            return line[2:].strip()
    return "Untitled"


def extract_description(body: str) -> str:
    """Extract description from markdown body (first paragraph after title)."""
    lines = body.split('\n')
    in_header = False
    description_lines = []

    for line in lines:
        if line.startswith('# '):
            in_header = True
            continue
        if in_header:
            if line.strip() == '':
                if description_lines:
                    break
                continue
            if line.startswith('#'):
                break
            description_lines.append(line.strip())

    return ' '.join(description_lines)[:500]  # Limit description length


def extract_tags(body: str, frontmatter: dict) -> list[str]:
    """Extract tags from frontmatter or markdown content."""
    tags = []

    # From frontmatter
    if 'tags' in frontmatter:
        fm_tags = frontmatter['tags']
        if isinstance(fm_tags, list):
            tags.extend(fm_tags)
        elif isinstance(fm_tags, str):
            tags.extend([t.strip() for t in fm_tags.split(',')])

    # From markdown (look for Tags: or ## Tags section)
    for line in body.split('\n'):
        if line.lower().startswith('tags:'):
            tag_str = line.split(':', 1)[1]
            tags.extend([t.strip().strip('`') for t in tag_str.split(',') if t.strip()])
            break
        if '## tags' in line.lower():
            # Look at next lines for bullet points
            pass

    return list(set(tags))  # Deduplicate


def extract_related_ideas(body: str, frontmatter: dict) -> list[str]:
    """Extract related idea IDs from frontmatter or markdown links."""
    related = []

    # From frontmatter
    if 'related' in frontmatter:
        fm_related = frontmatter['related']
        if isinstance(fm_related, list):
            related.extend(fm_related)
        elif isinstance(fm_related, str):
            related.extend([r.strip() for r in fm_related.split(',') if r.strip()])

    # From markdown links [Idea X](idea-X-*.md) or [idea-X]
    pattern = r'\[(?:Idea\s+)?(\d+[a-z]?)\]|\(idea-(\d+[a-z]?)[^)]*\.md\)'
    for match in re.finditer(pattern, body, re.IGNORECASE):
        idea_num = match.group(1) or match.group(2)
        if idea_num:
            related.append(f"idea-{idea_num}")

    # Also look for explicit Related Ideas section
    related_section = re.search(r'## Related Ideas?\s*\n(.*?)(?=\n##|\Z)', body, re.DOTALL | re.IGNORECASE)
    if related_section:
        section_text = related_section.group(1)
        for match in re.finditer(r'idea-(\d+[a-z]?)', section_text, re.IGNORECASE):
            related.append(f"idea-{match.group(1)}")

    return list(set(related))  # Deduplicate


def extract_wikidata_refs(body: str) -> list[str]:
    """Extract Wikidata Q-numbers from markdown content."""
    refs = []

    # Match Q followed by numbers (Q42, Q1234567)
    pattern = r'\bQ(\d+)\b'
    for match in re.finditer(pattern, body):
        refs.append(f"Q{match.group(1)}")

    # Also look for wikidata.org URLs
    url_pattern = r'wikidata\.org/(?:wiki|entity)/(Q\d+)'
    for match in re.finditer(url_pattern, body):
        refs.append(match.group(1))

    return list(set(refs))  # Deduplicate


def parse_idea_file(filepath: Path) -> Idea | None:
    """
    Parse an idea markdown file into an Idea object.

    Args:
        filepath: Path to the idea-*.md file

    Returns:
        Idea object or None if parsing fails
    """
    try:
        content = filepath.read_text(encoding='utf-8')
    except Exception as e:
        logger.error(f"Failed to read {filepath}: {e}")
        return None

    frontmatter, body = parse_frontmatter(content)

    # Extract idea ID from filename (idea-01-foo.md -> idea-1)
    match = re.match(r'idea-(\d+[a-z]?)', filepath.stem)
    if not match:
        logger.warning(f"Cannot extract idea ID from {filepath.name}")
        return None

    idea_num = match.group(1).lstrip('0') or '0'
    # Handle sub-ideas like idea-17a
    if idea_num[-1].isalpha():
        idea_id = f"idea-{idea_num}"
    else:
        idea_id = f"idea-{int(idea_num)}"

    # Extract fields
    title = extract_title(body)
    description = extract_description(body)
    tags = extract_tags(body, frontmatter)
    related = extract_related_ideas(body, frontmatter)
    wikidata_refs = extract_wikidata_refs(body)

    # Get author and lifecycle from frontmatter
    author = frontmatter.get('author', 'unknown')
    agent = frontmatter.get('agent')
    lifecycle = frontmatter.get('lifecycle', 'seed')

    # Parse created date
    created = datetime.now(timezone.utc)
    if 'created' in frontmatter:
        try:
            created_str = frontmatter['created']
            if isinstance(created_str, str):
                created = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            pass

    # Handle parent-child relationships
    parent = frontmatter.get('parent')
    if parent and isinstance(parent, str):
        parent = parent.strip()
        if not parent.startswith('idea-'):
            parent = f"idea-{parent}"

    children = []
    if 'children' in frontmatter:
        fm_children = frontmatter['children']
        if isinstance(fm_children, list):
            children = [c.strip() if c.startswith('idea-') else f"idea-{c.strip()}" for c in fm_children]
        elif isinstance(fm_children, str):
            children = [c.strip() if c.startswith('idea-') else f"idea-{c.strip()}"
                       for c in fm_children.split(',') if c.strip()]

    return Idea(
        id=idea_id,
        title=title,
        description=description,
        author=author,
        agent=agent,
        created=created,
        lifecycle=lifecycle,
        tags=tags,
        related=related,
        wikidata_refs=wikidata_refs,
        parent=parent,
        children=children,
    )


def migrate_ideas(
    ideas_dir: Path,
    store: KnowledgeGraphStore,
    dry_run: bool = False
) -> dict[str, Any]:
    """
    Migrate all idea files from a directory to the knowledge graph.

    Args:
        ideas_dir: Directory containing idea-*.md files
        store: Knowledge graph store
        dry_run: If True, only parse and report without storing

    Returns:
        Migration statistics
    """
    ideas_store = IdeasStore(store)

    # Find all idea files
    idea_files = sorted(ideas_dir.glob("idea-*.md"))
    logger.info(f"Found {len(idea_files)} idea files in {ideas_dir}")

    stats = {
        "total_files": len(idea_files),
        "parsed": 0,
        "created": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
    }

    for filepath in idea_files:
        logger.debug(f"Processing {filepath.name}")

        idea = parse_idea_file(filepath)
        if not idea:
            stats["failed"] += 1
            stats["errors"].append(f"Failed to parse: {filepath.name}")
            continue

        stats["parsed"] += 1

        if dry_run:
            logger.info(f"[DRY RUN] Would create: {idea.id} - {idea.title}")
            continue

        # Check if already exists
        existing = ideas_store.get_idea(idea.id)
        if existing:
            logger.debug(f"Idea {idea.id} already exists, skipping")
            stats["skipped"] += 1
            continue

        # Create the idea
        try:
            ideas_store.create_idea(idea)
            stats["created"] += 1
            logger.info(f"Created: {idea.id} - {idea.title}")
        except Exception as e:
            stats["failed"] += 1
            stats["errors"].append(f"Failed to create {idea.id}: {e}")
            logger.error(f"Failed to create {idea.id}: {e}")

    logger.info(f"Migration complete: {stats['created']} created, {stats['skipped']} skipped, {stats['failed']} failed")
    return stats


def sync_ideas(
    ideas_dir: Path,
    store: KnowledgeGraphStore
) -> dict[str, Any]:
    """
    Sync ideas from markdown files, updating existing ones.

    Args:
        ideas_dir: Directory containing idea-*.md files
        store: Knowledge graph store

    Returns:
        Sync statistics
    """
    ideas_store = IdeasStore(store)
    idea_files = sorted(ideas_dir.glob("idea-*.md"))

    stats = {
        "total_files": len(idea_files),
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "failed": 0,
    }

    for filepath in idea_files:
        idea = parse_idea_file(filepath)
        if not idea:
            stats["failed"] += 1
            continue

        existing = ideas_store.get_idea(idea.id)
        if not existing:
            # Create new
            try:
                ideas_store.create_idea(idea)
                stats["created"] += 1
            except Exception as e:
                logger.error(f"Failed to create {idea.id}: {e}")
                stats["failed"] += 1
        else:
            # Check if update needed (compare key fields)
            if (existing.title != idea.title or
                existing.lifecycle != idea.lifecycle or
                set(existing.tags) != set(idea.tags) or
                set(existing.related) != set(idea.related)):
                try:
                    ideas_store.update_idea(idea)
                    stats["updated"] += 1
                except Exception as e:
                    logger.error(f"Failed to update {idea.id}: {e}")
                    stats["failed"] += 1
            else:
                stats["unchanged"] += 1

    return stats


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 2:
        print("Usage: python -m knowledge_graph.migration <ideas_dir> [--dry-run]")
        sys.exit(1)

    ideas_dir = Path(sys.argv[1])
    dry_run = "--dry-run" in sys.argv

    if not ideas_dir.exists():
        print(f"Directory not found: {ideas_dir}")
        sys.exit(1)

    # Use in-memory store for testing
    store = KnowledgeGraphStore()
    stats = migrate_ideas(ideas_dir, store, dry_run=dry_run)

    print("\nMigration Statistics:")
    for key, value in stats.items():
        if key != "errors":
            print(f"  {key}: {value}")

    if stats["errors"]:
        print("\nErrors:")
        for error in stats["errors"]:
            print(f"  - {error}")
