#!/usr/bin/env python3
"""Idempotent seed script for Tulla phase definitions.

Loads phase-content.trig into the live KG via the /kg/update REST endpoint.
Safe to run on every server start — skipped if phase:d1 already exists.
"""

import argparse
import sys
import uuid
from pathlib import Path

import httpx
from rdflib import ConjunctiveGraph, URIRef, Literal, BNode

PHASES_GRAPH = "http://semantic-tool-use.org/graphs/phases"
IDEMPOTENCY_ASK = (
    f"ASK WHERE {{ GRAPH <{PHASES_GRAPH}> "
    "{ <http://tulla.dev/phase#d1> a <http://tulla.dev/phase#Phase> } }"
)


def skolemize_bnode(bnode: BNode, bnode_map: dict) -> URIRef:
    if bnode not in bnode_map:
        bnode_map[bnode] = URIRef(f"urn:bnode:{uuid.uuid4()}")
    return bnode_map[bnode]


def term_to_nt(term, bnode_map: dict) -> str:
    if isinstance(term, URIRef):
        escaped = str(term).replace("\\", "\\\\").replace(">", "\\>")
        return f"<{escaped}>"
    if isinstance(term, BNode):
        return term_to_nt(skolemize_bnode(term, bnode_map), bnode_map)
    if isinstance(term, Literal):
        lex = str(term)
        lex = lex.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
        if term.language:
            return f'"{lex}"@{term.language}'
        if term.datatype:
            dt = str(term.datatype).replace("\\", "\\\\").replace(">", "\\>")
            return f'"{lex}"^^<{dt}>'
        return f'"{lex}"'
    raise ValueError(f"Unknown term type: {type(term)}")


def build_insert(triples: list) -> str:
    bnode_map: dict = {}
    lines = []
    for s, p, o in triples:
        lines.append(
            f"    {term_to_nt(s, bnode_map)} {term_to_nt(p, bnode_map)} {term_to_nt(o, bnode_map)} ."
        )
    body = "\n".join(lines)
    return f"INSERT DATA {{\n  GRAPH <{PHASES_GRAPH}> {{\n{body}\n  }}\n}}"


def main():
    script_dir = Path(__file__).resolve().parent
    default_trig = script_dir.parent / "tulla" / "ontologies" / "phase-content.trig"

    parser = argparse.ArgumentParser(description="Seed Tulla phase definitions into the KG.")
    parser.add_argument("--url", default="http://localhost:8100", help="Base URL of the ontology server")
    parser.add_argument("--trig-file", default=str(default_trig), help="Path to phase-content.trig")
    parser.add_argument("--force", action="store_true", help="Re-seed even if already seeded (clears existing data first)")
    args = parser.parse_args()

    # DEPRECATED: the server seeds phase content in-process at startup
    # (ontology_server.mcp.phase_tools.seed_phase_content). This script
    # skolemizes SHACL blank nodes to urn:bnode: URIs, which corrupts gate
    # shapes with dangling sh:property references. Kept only for manual
    # emergency use against a server that cannot restart.
    if not args.force:
        print(
            "DEPRECATED: phase content is seeded in-process at server "
            "startup; this script skolemizes SHACL blank nodes and corrupts "
            "gate shapes. Run with --force only if you know what you are "
            "doing.",
            file=sys.stderr,
        )
        sys.exit(0)

    base_url = args.url.rstrip("/")
    trig_path = Path(args.trig_file)

    if not trig_path.exists():
        print(f"ERROR: TriG file not found: {trig_path}", file=sys.stderr)
        sys.exit(1)

    # Idempotency check (skip when --force)
    if not args.force:
        try:
            resp = httpx.post(f"{base_url}/kg/sparql", params={"query": IDEMPOTENCY_ASK}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            already_seeded = data.get("result") is True or data.get("boolean") is True
            if already_seeded:
                print("Phase definitions already seeded — skipping.")
                sys.exit(0)
        except httpx.HTTPError as exc:
            print(f"ERROR: Idempotency check failed: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        print("--force: skipping idempotency check, re-seeding.")

    # Parse TriG
    g = ConjunctiveGraph()
    g.parse(str(trig_path), format="trig")

    phases_uri = URIRef(PHASES_GRAPH)

    # Collect triples: named graph triples + default graph triples
    triples = []
    for ctx in g.contexts():
        if isinstance(ctx.identifier, URIRef) and str(ctx.identifier) == PHASES_GRAPH:
            triples.extend(ctx.triples((None, None, None)))
        elif isinstance(ctx.identifier, URIRef) and str(ctx.identifier) == "urn:x-rdflib:default":
            # Default graph triples (e.g. the phase:Phase class declaration)
            triples.extend(ctx.triples((None, None, None)))
        elif not isinstance(ctx.identifier, URIRef):
            # Blank-node default graph
            triples.extend(ctx.triples((None, None, None)))

    if not triples:
        print("ERROR: No triples found in TriG file.", file=sys.stderr)
        sys.exit(1)

    sparql = build_insert(triples)

    # POST to /kg/update
    try:
        resp = httpx.post(
            f"{base_url}/kg/update",
            json={"query": sparql},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
    except httpx.HTTPError as exc:
        print(f"ERROR: INSERT failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Inserted {len(triples)} triples into <{PHASES_GRAPH}>.")
    print(f"Server response: {result.get('status', 'unknown')} — {result.get('message', '')}")
    sys.exit(0)


if __name__ == "__main__":
    main()
