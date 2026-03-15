"""
Migration script for importing ideas from markdown files to the knowledge graph.

Reads idea-*.md files with YAML frontmatter and creates RDF representations
using the SKOS+DC ontology. Also migrates seeds and JSON graph relationships.
"""

import re
import json
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


def extract_full_content(body: str) -> str:
    """Extract the full markdown content (everything after frontmatter)."""
    return body


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
    full_content = extract_full_content(body)
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

    # Handle blocks/blocked_by
    blocks = []
    if 'blocks' in frontmatter:
        fm_blocks = frontmatter['blocks']
        if isinstance(fm_blocks, list):
            blocks = [b.strip() if b.startswith('idea-') else f"idea-{b.strip()}" for b in fm_blocks]
        elif isinstance(fm_blocks, str):
            blocks = [b.strip() if b.startswith('idea-') else f"idea-{b.strip()}"
                     for b in fm_blocks.split(',') if b.strip()]

    blocked_by = []
    if 'blocked_by' in frontmatter:
        fm_blocked = frontmatter['blocked_by']
        if isinstance(fm_blocked, list):
            blocked_by = [b.strip() if b.startswith('idea-') else f"idea-{b.strip()}" for b in fm_blocked]
        elif isinstance(fm_blocked, str):
            blocked_by = [b.strip() if b.startswith('idea-') else f"idea-{b.strip()}"
                         for b in fm_blocked.split(',') if b.strip()]

    # Lifecycle metadata
    lifecycle_reason = frontmatter.get('lifecycle_reason', '')
    lifecycle_updated = None
    if 'lifecycle_updated' in frontmatter:
        try:
            lu_str = frontmatter['lifecycle_updated']
            if isinstance(lu_str, str):
                lifecycle_updated = datetime.fromisoformat(lu_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            pass

    # Crystallized from
    crystallized_from = frontmatter.get('crystallized_from')
    if crystallized_from and isinstance(crystallized_from, str):
        crystallized_from = crystallized_from.strip()

    # Priority
    priority = None
    if 'priority' in frontmatter:
        try:
            priority = int(frontmatter['priority'])
        except (ValueError, TypeError):
            pass

    return Idea(
        id=idea_id,
        title=title,
        description=description,
        content=full_content,
        author=author,
        agent=agent,
        created=created,
        lifecycle=lifecycle,
        lifecycle_updated=lifecycle_updated,
        lifecycle_reason=lifecycle_reason if isinstance(lifecycle_reason, str) else '',
        tags=tags,
        related=related,
        wikidata_refs=wikidata_refs,
        parent=parent,
        children=children,
        blocks=blocks,
        blocked_by=blocked_by,
        crystallized_from=crystallized_from,
        priority=priority,
    )


def parse_seed_file(filepath: Path) -> Idea | None:
    """
    Parse a seed markdown file into an Idea (seed type).

    Args:
        filepath: Path to a seeds/*.md file

    Returns:
        Idea object with is_seed=True, or None if parsing fails
    """
    try:
        content = filepath.read_text(encoding='utf-8')
    except Exception as e:
        logger.error(f"Failed to read seed {filepath}: {e}")
        return None

    frontmatter, body = parse_frontmatter(content)

    # Seed ID from filename (e.g., 20260126-161907-auk4.md → seed-20260126-161907-auk4)
    seed_id = f"seed-{filepath.stem}"

    # Extract title from first line
    first_line = body.strip().split('\n')[0][:100] if body.strip() else "Untitled seed"
    title = first_line if first_line else "Untitled seed"

    author = frontmatter.get('author', 'anonymous')
    agent = frontmatter.get('agent')

    # Parse captured_at from frontmatter or filename
    captured_at = datetime.now(timezone.utc)
    if 'captured' in frontmatter:
        try:
            captured_at = datetime.fromisoformat(frontmatter['captured'].replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            pass
    else:
        # Try to parse from filename: YYYYMMDD-HHMMSS-xxxx.md
        ts_match = re.match(r'(\d{8})-(\d{6})', filepath.stem)
        if ts_match:
            try:
                captured_at = datetime.strptime(
                    f"{ts_match.group(1)}{ts_match.group(2)}",
                    "%Y%m%d%H%M%S"
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                pass

    return Idea(
        id=seed_id,
        title=title,
        description=first_line[:200],
        content=body,
        author=author,
        agent=agent,
        created=captured_at,
        lifecycle="seed",
        is_seed=True,
        captured_at=captured_at,
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


def migrate_seeds(
    seeds_dir: Path,
    store: KnowledgeGraphStore,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Migrate seed files from seeds/ directory.

    Args:
        seeds_dir: Directory containing seed markdown files
        store: Knowledge graph store
        dry_run: If True, only parse and report

    Returns:
        Migration statistics
    """
    ideas_store = IdeasStore(store)
    seed_files = sorted(seeds_dir.glob("*.md"))
    logger.info(f"Found {len(seed_files)} seed files in {seeds_dir}")

    stats = {
        "total_files": len(seed_files),
        "created": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
    }

    for filepath in seed_files:
        seed = parse_seed_file(filepath)
        if not seed:
            stats["failed"] += 1
            stats["errors"].append(f"Failed to parse seed: {filepath.name}")
            continue

        if dry_run:
            logger.info(f"[DRY RUN] Would create seed: {seed.id}")
            continue

        existing = ideas_store.get_idea(seed.id)
        if existing:
            stats["skipped"] += 1
            continue

        try:
            ideas_store.create_idea(seed)
            stats["created"] += 1
            logger.info(f"Created seed: {seed.id}")
        except Exception as e:
            stats["failed"] += 1
            stats["errors"].append(f"Failed to create seed {seed.id}: {e}")

    return stats


def migrate_json_graph(
    graph_path: Path,
    store: KnowledgeGraphStore,
) -> dict[str, Any]:
    """
    Migrate relationships from .graph/knowledge_graph.json.

    Reads the JSON graph and creates RDF relationship triples.

    Args:
        graph_path: Path to knowledge_graph.json
        store: Knowledge graph store

    Returns:
        Migration statistics
    """
    from .core.ideas import IDEA, IDEAS, SKOS

    if not graph_path.exists():
        return {"error": f"Graph file not found: {graph_path}"}

    try:
        data = json.loads(graph_path.read_text(encoding='utf-8'))
    except Exception as e:
        return {"error": f"Failed to read graph: {e}"}

    stats = {
        "relationships_added": 0,
        "categories_added": 0,
        "errors": [],
    }

    # Process relationships
    relationships = data.get("relationships", [])
    for rel in relationships:
        source = rel.get("source", "")
        target = rel.get("target", "")
        rel_type = rel.get("type", "related")

        if not source or not target:
            continue

        # Normalize IDs
        if not source.startswith("idea-"):
            source = f"idea-{source}"
        if not target.startswith("idea-"):
            target = f"idea-{target}"

        try:
            store.add_triple(
                f"{IDEAS}{source}",
                f"{SKOS}related",
                f"{IDEAS}{target}",
            )
            stats["relationships_added"] += 1
        except Exception as e:
            stats["errors"].append(f"Failed to add relationship {source}->{target}: {e}")

    # Process categories
    categories = data.get("categories", [])
    for cat in categories:
        name = cat.get("name", "")
        idea_ids = cat.get("ideas", [])

        if not name:
            continue

        tag_uri = f"{IDEA}tag/{name.lower().replace(' ', '-')}"
        store.add_triple(tag_uri, f"{NAMESPACES['rdf']}type", f"{SKOS}Concept")
        store.add_triple(tag_uri, f"{NAMESPACES['skos']}prefLabel", name, is_literal=True)

        for idea_id in idea_ids:
            if not idea_id.startswith("idea-"):
                idea_id = f"idea-{idea_id}"
            store.add_triple(
                f"{IDEAS}{idea_id}",
                f"{NAMESPACES['dcterms']}subject",
                tag_uri,
            )
        stats["categories_added"] += 1

    store.flush()
    return stats


# Import NAMESPACES for migrate_json_graph
from .core.store import NAMESPACES


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


def full_migration(
    ideas_dir: Path,
    store: KnowledgeGraphStore,
    compute_embeddings: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Run full migration: ideas + seeds + JSON graph + optional embeddings.

    Args:
        ideas_dir: Root directory (contains idea-*.md, seeds/, .graph/)
        store: Knowledge graph store
        compute_embeddings: If True, compute embeddings after migration
        dry_run: If True, only report

    Returns:
        Combined migration statistics
    """
    results = {}

    # 1. Migrate ideas
    results["ideas"] = migrate_ideas(ideas_dir, store, dry_run)

    # 2. Migrate seeds
    seeds_dir = ideas_dir / "seeds"
    if seeds_dir.exists():
        results["seeds"] = migrate_seeds(seeds_dir, store, dry_run)
    else:
        results["seeds"] = {"skipped": True, "reason": "seeds/ directory not found"}

    # 3. Migrate JSON graph relationships
    graph_path = ideas_dir / ".graph" / "knowledge_graph.json"
    if graph_path.exists() and not dry_run:
        results["graph"] = migrate_json_graph(graph_path, store)
    else:
        results["graph"] = {"skipped": True, "reason": "graph file not found or dry_run"}

    # 4. Optionally compute embeddings
    if compute_embeddings and not dry_run:
        try:
            from .core.search import SemanticSearch
            ideas_store = IdeasStore(store)
            search = SemanticSearch(store, ideas_store)
            results["embeddings"] = search.ensure_embeddings()
        except Exception as e:
            results["embeddings"] = {"error": str(e)}
    else:
        results["embeddings"] = {"skipped": True}

    return results


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 2:
        print("Usage: python -m knowledge_graph.migration <ideas_dir> [--dry-run] [--compute-embeddings] [--full]")
        sys.exit(1)

    ideas_dir = Path(sys.argv[1])
    dry_run = "--dry-run" in sys.argv
    compute_embeddings = "--compute-embeddings" in sys.argv
    full = "--full" in sys.argv

    if not ideas_dir.exists():
        print(f"Directory not found: {ideas_dir}")
        sys.exit(1)

    # Use in-memory store for testing
    store = KnowledgeGraphStore()

    if full:
        stats = full_migration(ideas_dir, store, compute_embeddings, dry_run)
    else:
        stats = migrate_ideas(ideas_dir, store, dry_run=dry_run)

    print("\nMigration Statistics:")
    if isinstance(stats, dict) and "ideas" in stats:
        for section, section_stats in stats.items():
            print(f"\n{section}:")
            if isinstance(section_stats, dict):
                for key, value in section_stats.items():
                    if key != "errors":
                        print(f"  {key}: {value}")
    else:
        for key, value in stats.items():
            if key != "errors":
                print(f"  {key}: {value}")

    errors = stats.get("errors", [])
    if errors:
        print("\nErrors:")
        for error in errors:
            print(f"  - {error}")
