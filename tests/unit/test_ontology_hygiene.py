"""Ontology hygiene lint — the defect classes KG reviewers find in minutes.

Guards every shipped .ttl/.trig against the lossy-round-trip artifacts that
were present in isaqb-ontology.ttl before the tulla-pipeline merge:

1. junk numbered prefixes (``@prefix ns1: <rdf:>``),
2. scheme-CURIE IRIs (``<arch:adr-1>`` — parses as an absolute IRI with URI
   scheme "arch", silently detached from the real namespace),
3. string literals as rdf:type objects (``a "isaqb:ArchitectureDecision"``),
4. dangling references for the iSAQB ADR predicates (addresses/decisionStatus).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from rdflib import Dataset, Graph, Literal, RDF, URIRef

REPO = Path(__file__).resolve().parents[2]

TTL_FILES = sorted(
    p for p in (REPO / "ontology").rglob("*.ttl")
)
TRIG_FILES = sorted((REPO / "tulla" / "ontologies").glob("*.trig"))

CURIE_PREFIXES = ("arch", "isaqb", "prd", "phase", "trace", "idea", "code")
SCHEME_CURIE = re.compile(r"<(%s):[^/>][^>]*>" % "|".join(CURIE_PREFIXES))
JUNK_PREFIX = re.compile(r"@prefix\s+ns\d+:")


def _all_files() -> list[Path]:
    assert TTL_FILES, "no ontology .ttl files found — repo layout changed?"
    return TTL_FILES + TRIG_FILES


@pytest.mark.parametrize("path", _all_files(), ids=lambda p: str(p.relative_to(REPO)))
def test_parses(path: Path) -> None:
    if path.suffix == ".trig":
        Dataset().parse(path, format="trig")
    else:
        Graph().parse(path, format="turtle")


@pytest.mark.parametrize("path", _all_files(), ids=lambda p: str(p.relative_to(REPO)))
def test_no_junk_prefixes(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert not JUNK_PREFIX.search(text), (
        f"{path.name}: numbered junk prefix (@prefix nsN:) — lossy round-trip artifact"
    )


@pytest.mark.parametrize("path", _all_files(), ids=lambda p: str(p.relative_to(REPO)))
def test_no_scheme_curies(path: Path) -> None:
    """<arch:x> is a *valid* IRI with scheme 'arch' — and therefore silently
    disconnected from @prefix arch: <http://tulla.dev/architecture#>."""
    text = path.read_text(encoding="utf-8")
    hits = SCHEME_CURIE.findall(text)
    assert not hits, f"{path.name}: angle-bracket CURIEs (scheme-IRIs): {sorted(set(hits))}"


@pytest.mark.parametrize("path", _all_files(), ids=lambda p: str(p.relative_to(REPO)))
def test_no_literal_rdf_types(path: Path) -> None:
    if path.suffix == ".trig":
        g: Graph = Dataset(default_union=True)
        g.parse(path, format="trig")
    else:
        g = Graph()
        g.parse(path, format="turtle")
    bad = [(s, o) for s, o in g.subject_objects(RDF.type) if isinstance(o, Literal)]
    assert not bad, f"{path.name}: string literals as rdf:type objects: {bad[:5]}"


class TestIsaqbReferentialIntegrity:
    @pytest.fixture(scope="class")
    def graph(self) -> Graph:
        g = Graph()
        g.parse(REPO / "ontology" / "domain" / "tulla-pipeline" / "isaqb-ontology.ttl", format="turtle")
        return g

    @pytest.mark.parametrize("predicate", ["addresses", "decisionStatus", "embodies"])
    def test_no_dangling_objects(self, graph: Graph, predicate: str) -> None:
        pred = URIRef(f"http://tulla.dev/isaqb#{predicate}")
        declared = set(graph.subjects())
        dangling = sorted(
            str(o) for o in graph.objects(None, pred)
            if isinstance(o, URIRef) and o not in declared
        )
        assert not dangling, f"isaqb:{predicate} points at undeclared resources: {dangling}"

    def test_adrs_are_typed_resources(self, graph: Graph) -> None:
        adr_class = URIRef("http://tulla.dev/isaqb#ArchitectureDecision")
        arch_ns = "http://tulla.dev/architecture#"
        adr_subjects = [s for s in set(graph.subjects()) if str(s).startswith(arch_ns)]
        assert adr_subjects, "expected recorded ADR individuals in the arch: namespace"
        untyped = [str(s) for s in adr_subjects if (s, RDF.type, adr_class) not in graph]
        assert not untyped, f"arch: ADRs missing isaqb:ArchitectureDecision type: {untyped}"
