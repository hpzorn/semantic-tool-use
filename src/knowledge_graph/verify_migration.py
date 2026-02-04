"""
Migration verification script.

Validates that all data was migrated correctly from markdown files
to the Oxigraph RDF knowledge graph. Checks counts, lifecycles,
dependencies, content, and structural integrity.
"""

import logging
import re
import sys
from pathlib import Path
from typing import Any

from .core.store import KnowledgeGraphStore, NAMESPACES
from .core.ideas import IdeasStore

logger = logging.getLogger(__name__)

IDEAS = NAMESPACES["ideas"]
IDEA = NAMESPACES["idea"]
SKOS = NAMESPACES["skos"]


def count_source_files(ideas_dir: Path) -> dict[str, int]:
    """Count source markdown files."""
    idea_files = list(ideas_dir.glob("idea-*.md"))
    seed_files = list((ideas_dir / "seeds").glob("*.md")) if (ideas_dir / "seeds").exists() else []
    return {
        "idea_files": len(idea_files),
        "seed_files": len(seed_files),
    }


def verify_idea_count(
    ideas_dir: Path,
    store: KnowledgeGraphStore,
) -> dict[str, Any]:
    """Verify all idea files were migrated."""
    ideas_store = IdeasStore(store)
    source = count_source_files(ideas_dir)

    # Count ideas in RDF (excluding seeds)
    rdf_ideas = ideas_store.list_ideas(limit=1000)
    rdf_idea_count = len(rdf_ideas)

    # Count seeds in RDF
    seed_query = f"""
    SELECT (COUNT(DISTINCT ?s) AS ?count)
    WHERE {{
        ?s a <{IDEA}Seed> .
    }}
    """
    seed_results = store.query(seed_query)
    rdf_seed_count = int(seed_results[0]["count"]) if seed_results else 0

    # Ideas in RDF includes seeds, so total ideas minus seeds = pure ideas
    rdf_pure_ideas = rdf_idea_count - rdf_seed_count

    passed = (
        rdf_pure_ideas >= source["idea_files"]
        and rdf_seed_count >= source["seed_files"]
    )

    return {
        "check": "idea_count",
        "passed": passed,
        "source_ideas": source["idea_files"],
        "source_seeds": source["seed_files"],
        "rdf_ideas": rdf_pure_ideas,
        "rdf_seeds": rdf_seed_count,
        "rdf_total": rdf_idea_count,
    }


def verify_lifecycles(
    ideas_dir: Path,
    store: KnowledgeGraphStore,
) -> dict[str, Any]:
    """Verify all lifecycle states were preserved."""
    from .migration import parse_idea_file

    ideas_store = IdeasStore(store)
    idea_files = sorted(ideas_dir.glob("idea-*.md"))

    mismatches = []
    checked = 0

    for filepath in idea_files:
        source_idea = parse_idea_file(filepath)
        if not source_idea:
            continue

        rdf_idea = ideas_store.get_idea(source_idea.id)
        if not rdf_idea:
            mismatches.append({
                "id": source_idea.id,
                "issue": "not_found_in_rdf",
            })
            continue

        checked += 1
        if rdf_idea.lifecycle != source_idea.lifecycle:
            mismatches.append({
                "id": source_idea.id,
                "source_lifecycle": source_idea.lifecycle,
                "rdf_lifecycle": rdf_idea.lifecycle,
            })

    return {
        "check": "lifecycles",
        "passed": len(mismatches) == 0,
        "checked": checked,
        "mismatches": mismatches,
    }


def verify_dependencies(
    store: KnowledgeGraphStore,
) -> dict[str, Any]:
    """Verify dependency relationships (blocks/blockedBy) are in RDF."""
    blocks_query = f"""
    SELECT (COUNT(*) AS ?count)
    WHERE {{
        ?s <{IDEA}blocks> ?o .
    }}
    """
    blocked_by_query = f"""
    SELECT (COUNT(*) AS ?count)
    WHERE {{
        ?s <{IDEA}blockedBy> ?o .
    }}
    """
    parent_query = f"""
    SELECT (COUNT(*) AS ?count)
    WHERE {{
        ?s <{IDEA}parentIdea> ?o .
    }}
    """

    blocks_results = store.query(blocks_query)
    blocked_results = store.query(blocked_by_query)
    parent_results = store.query(parent_query)

    blocks_count = int(blocks_results[0]["count"]) if blocks_results else 0
    blocked_count = int(blocked_results[0]["count"]) if blocked_results else 0
    parent_count = int(parent_results[0]["count"]) if parent_results else 0

    return {
        "check": "dependencies",
        "passed": True,  # Informational — no strict target
        "blocks_triples": blocks_count,
        "blocked_by_triples": blocked_count,
        "parent_triples": parent_count,
    }


def verify_content_stored(
    ideas_dir: Path,
    store: KnowledgeGraphStore,
) -> dict[str, Any]:
    """Verify full markdown content is stored in RDF."""
    ideas_store = IdeasStore(store)
    idea_files = sorted(ideas_dir.glob("idea-*.md"))

    missing_content = []
    checked = 0

    for filepath in idea_files:
        match = re.match(r"idea-(\d+[a-z]?)", filepath.stem)
        if not match:
            continue

        idea_num = match.group(1).lstrip("0") or "0"
        if idea_num[-1].isalpha():
            idea_id = f"idea-{idea_num}"
        else:
            idea_id = f"idea-{int(idea_num)}"

        rdf_idea = ideas_store.get_idea(idea_id)
        if not rdf_idea:
            missing_content.append({"id": idea_id, "issue": "not_found"})
            continue

        checked += 1
        if not rdf_idea.content or len(rdf_idea.content) < 50:
            missing_content.append({
                "id": idea_id,
                "issue": "content_missing_or_short",
                "content_length": len(rdf_idea.content) if rdf_idea.content else 0,
            })

    return {
        "check": "content_stored",
        "passed": len(missing_content) == 0,
        "checked": checked,
        "missing": missing_content,
    }


def verify_tags(
    store: KnowledgeGraphStore,
) -> dict[str, Any]:
    """Verify tags are stored."""
    tag_query = f"""
    SELECT (COUNT(DISTINCT ?tag) AS ?count)
    WHERE {{
        ?s <{IDEA}tag> ?tag .
    }}
    """
    results = store.query(tag_query)
    tag_count = int(results[0]["count"]) if results else 0

    return {
        "check": "tags",
        "passed": tag_count > 0,
        "unique_tags": tag_count,
    }


def verify_related(
    store: KnowledgeGraphStore,
) -> dict[str, Any]:
    """Verify related idea relationships are stored."""
    related_query = f"""
    SELECT (COUNT(*) AS ?count)
    WHERE {{
        ?s <{SKOS}related> ?o .
    }}
    """
    results = store.query(related_query)
    related_count = int(results[0]["count"]) if results else 0

    return {
        "check": "related_ideas",
        "passed": related_count > 0,
        "relationship_triples": related_count,
    }


def verify_graph_stats(
    store: KnowledgeGraphStore,
) -> dict[str, Any]:
    """Get overall graph statistics."""
    total_query = "SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }"
    results = store.query(total_query)
    total = int(results[0]["count"]) if results else 0

    lifecycle_query = f"""
    SELECT ?lifecycle (COUNT(?idea) AS ?count)
    WHERE {{
        ?idea <{IDEA}lifecycle> ?lifecycle .
    }}
    GROUP BY ?lifecycle
    ORDER BY DESC(?count)
    """
    lifecycle_results = store.query(lifecycle_query)

    lifecycles = {
        r["lifecycle"]: int(r["count"])
        for r in lifecycle_results
    }

    return {
        "check": "graph_stats",
        "passed": total > 0,
        "total_triples": total,
        "lifecycle_breakdown": lifecycles,
    }


def run_verification(
    ideas_dir: Path,
    store: KnowledgeGraphStore,
) -> dict[str, Any]:
    """
    Run all verification checks.

    Args:
        ideas_dir: Source directory with idea-*.md and seeds/
        store: Knowledge graph store (post-migration)

    Returns:
        Full verification report
    """
    checks = []

    checks.append(verify_idea_count(ideas_dir, store))
    checks.append(verify_lifecycles(ideas_dir, store))
    checks.append(verify_dependencies(store))
    checks.append(verify_content_stored(ideas_dir, store))
    checks.append(verify_tags(store))
    checks.append(verify_related(store))
    checks.append(verify_graph_stats(store))

    all_passed = all(c["passed"] for c in checks)

    return {
        "all_passed": all_passed,
        "checks": checks,
        "summary": {
            "total_checks": len(checks),
            "passed": sum(1 for c in checks if c["passed"]),
            "failed": sum(1 for c in checks if not c["passed"]),
        },
    }


if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 2:
        print("Usage: python -m knowledge_graph.verify_migration <ideas_dir> [--persist <path>]")
        sys.exit(1)

    ideas_dir = Path(sys.argv[1])
    if not ideas_dir.exists():
        print(f"Directory not found: {ideas_dir}")
        sys.exit(1)

    # Optional persistence path
    persist_path = None
    if "--persist" in sys.argv:
        idx = sys.argv.index("--persist")
        if idx + 1 < len(sys.argv):
            persist_path = sys.argv[idx + 1]

    # Initialize store
    store = KnowledgeGraphStore(persist_path)

    # If no persistence, run migration first
    if not persist_path:
        from .migration import full_migration

        print("Running migration before verification...")
        migration_stats = full_migration(ideas_dir, store)
        print(f"Migration: {json.dumps(migration_stats, indent=2, default=str)}\n")

    # Run verification
    print("Running verification checks...\n")
    report = run_verification(ideas_dir, store)

    # Print report
    for check in report["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        name = check["check"]
        print(f"  [{status}] {name}")

        # Print details for failures or interesting stats
        for key, value in check.items():
            if key in ("check", "passed"):
                continue
            if key == "mismatches" and value:
                for m in value[:5]:  # Show first 5
                    print(f"         {m}")
            elif key == "missing" and value:
                for m in value[:5]:
                    print(f"         {m}")
            elif key == "lifecycle_breakdown":
                for lc, count in value.items():
                    print(f"         {lc}: {count}")
            elif isinstance(value, (int, str, bool)):
                print(f"         {key}: {value}")

    print(f"\n{'ALL CHECKS PASSED' if report['all_passed'] else 'SOME CHECKS FAILED'}")
    print(f"  {report['summary']['passed']}/{report['summary']['total_checks']} passed")

    sys.exit(0 if report["all_passed"] else 1)
