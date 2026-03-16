<p align="center">
  <h1 align="center">Semantic Tool Use</h1>
  <p align="center">
    <strong>Formal ontologies as the type system for agentic AI</strong>
  </p>
  <p align="center">
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License"></a>
    <img src="https://img.shields.io/badge/python-3.11+-brightgreen" alt="Python 3.11+">
    <img src="https://img.shields.io/badge/MCP-native-purple" alt="MCP Native">
  </p>
</p>

---
semantic-tool-use is experimental software built for research purposes. It is not meant for production use. It still has major security issues (such as prompt injection during research) that are typical for LLM based agents. It should only be used in sandbox environments without access to sensitive data/information. It is completely AI generated - mostly coded by itself. I only prompt, I did not review every line of code - which is an experiment and not recommended policy, especially it is not policy at my employer. This is a private project.

LLM tool calling today is a `dict[str, Any]` with a prayer. JSON Schema checks if you passed a string — it can't check if you passed a *valid* string, or if the operation even makes sense given the current state of the world.

**Semantic Tool Use** replaces that with OWL ontologies + SHACL constraints — a formally verifiable interface definition that agents can query, reason over, and validate against *before* execution. Think of it as **a type system for tool calling that actually catches semantic errors**, not just structural ones.

Built as the knowledge backend for **[Tulla](https://github.com/hpz/tulla)** — an autonomous software engineering agent that takes an idea seed and produces fully implemented, architecturally governed code with a complete traceability chain from commit back to requirement back to quality attribute back to persona need. Every phase of Tulla's pipeline persists its decision-critical outputs as RDF triples in *this* knowledge graph, validated against SHACL shapes, queryable via SPARQL by every downstream phase.

## The Problem Semantic Tool Use Solves

Agentic pipelines suffer from **semantic context loss at every handoff**. When a discovery agent identifies critical user personas, that insight is invisible to the planning agent. When the planning agent makes an architectural decision, the implementation agent can't query *why*. The result: code that compiles but lacks coherence.

Passing markdown between phases doesn't fix this — even with unlimited context, a 54KB architecture design document is opaque prose that another LLM must re-interpret. Lossy, expensive, unreliable.

The fix: **structured semantic persistence**. Each phase declares which output fields carry architectural intent (via `IntentField` annotations). The pipeline extracts those fields, stores them as typed RDF triples, and validates them against SHACL shapes. Downstream phases query the knowledge graph and get structured facts — not document dumps.

```python
class D3Output(BaseModel):
    value_mapping_file: Path                          # artifact path — NOT persisted
    quadrant: str = IntentField(description="...")     # decision field — persisted as RDF
    strategic_constraints: str = IntentField(...)      # scope boundary — persisted
    verdict: str = IntentField(description="...")      # go/no-go — persisted
```


## How Tulla Uses This

Tulla is a four-stage pipeline — Discovery, Research, Planning, Implementation — where each stage enriches a shared knowledge graph that all subsequent stages can query.

```
Idea Seed
  → Discovery (D1-D5)    "Who needs this? What exists? What's the gap?"
    → Research (R1-R6)    "What don't we know? What experiments resolve uncertainty?"
      → Planning (P1-P6)  "What architecture? Which patterns? What ADRs?"
        → Implementation  "Write code, verify, commit — with full traceability"

Each phase:  build prompt → call LLM → parse output → extract IntentFields
             → persist as RDF triples → validate against SHACL → checkpoint
```

The ontology server is the shared brain. Tulla's `OntologyPort` adapter makes HTTP calls to it for:

- **SPARQL queries** — `collect_upstream_facts()` retrieves all decision-critical outputs from prior phases
- **Triple persistence** — `store_fact()` writes IntentField values as typed triples with provenance
- **SHACL validation** — `validate_instance()` checks phase outputs against per-phase shapes; invalid outputs trigger rollback
- **Lifecycle management** — `set_lifecycle()` transitions ideas through 13 states (seed → backlog → researching → scoped → implementing → completed)
- **Architecture decisions** — ADRs stored as `isaqb:ArchitectureDecision` instances, queryable and enforceable

### The iSAQB Ontology: Architecture as Queryable Knowledge

Tulla's planning phase (P3: Architecture Design) doesn't just generate markdown ADRs — it produces **formal architecture knowledge** grounded in the [iSAQB](https://www.isaqb.org/) Foundation Level curriculum, modeled as an OWL ontology with 20+ core classes:

```turtle
isaqb:ArchitectureDecision a owl:Class ;
    rdfs:comment "A documented decision following ADR structure:
                  context, options, decision, consequences (LG 04-08)" .

isaqb:QualityAttribute a owl:Class ;
    rdfs:comment "Measurable system properties per ISO/IEC 25010:2023" .

isaqb:DesignPrinciple a owl:Class ;
    rdfs:comment "Abstraction, Modularization, ConceptualIntegrity,
                  ComplexityReduction, Robustness (LG 03-04)" .
```

When P3 generates ADRs, they're stored as RDF instances with explicit links:

```turtle
arch:adr-69-1 a isaqb:ArchitectureDecision ;
    rdfs:label "Use Ports-and-Adapters for LLM backend abstraction" ;
    isaqb:context "Multiple LLM backends (Claude, Codex, OpenCode) must be swappable..." ;
    isaqb:decisionStatus isaqb:Accepted ;
    isaqb:addresses isaqb:Maintainability, isaqb:Flexibility ;
    isaqb:challenges isaqb:PerformanceEfficiency .
```

The implementation phase then **queries these ADRs** before writing code. Project-level decisions propagate across ideas via `isaqb:supersedes` links. This is how architectural governance survives across agent boundaries — not as prose in a CLAUDE.md, but as **queryable, enforceable, typed triples**.

The iSAQB ontology covers the full vocabulary: quality scenarios (stimulus → environment → response → measure), architectural patterns (Layers, Pipes-and-Filter, CQRS, Ports-and-Adapters), design patterns (Adapter, Factory, Strategy), cross-cutting concerns, risks, technical debt, and arc42 documentation sections.

### Bootstrap Results

Tulla has been self-hosting since February 2026 — bootstrapping its own development:

- **166 implementation commits** across 10+ ideas in 7 days
- **1,542 passing tests**
- Complete traceability: every commit traces back through requirement → ADR → quality attribute → persona → idea seed
- Average discovery cost: $0.35–$3.56 per idea
- The system improves itself: each idea makes Tulla better for the next one

## Architecture

```
              ┌──────────────────────────────────────┐
              │       Tulla / Any Agent Client        │
              │  OntologyPort → HTTP REST adapter     │
              └──────────────┬───────────────────────┘
                             │ queries, persists, validates
                             ▼
              ┌──────────────────────────────────────┐
              │      Ontology Server (T-Box)          │
              │  OWL ontologies + SHACL shapes        │
              │  iSAQB, Visual Artifacts, Idea Pool   │
              │  SPARQL query engine (rdflib)          │
              └──────────────┬───────────────────────┘
                             │
                             ▼
              ┌──────────────────────────────────────┐
              │      Knowledge Graph (A-Box)          │
              │  Oxigraph (RocksDB-backed)            │
              │  Ideas, phase facts, ADRs, agent      │
              │  memory, Wikidata entity cache         │
              └──────────────────────────────────────┘
```

### Two-layer design

| Layer | What | How |
|-------|------|-----|
| **T-Box** (schema) | OWL ontologies defining domain models, tool interfaces, constraints | rdflib, SPARQL, SHACL |
| **A-Box** (instances) | Persistent knowledge graph — ideas, phase outputs, ADRs, agent memory, Wikidata entities | Oxigraph (RocksDB-backed) |

Both layers are exposed via **MCP** (Model Context Protocol) for native integration with Claude Code, and via **REST API** for any HTTP client.

This is not your 2005 Semantic Web. There's no Protege GUI, no enterprise middleware, no XML/RDF gatekeeping. It's a **knowledge backend that speaks MCP** — agents query it the same way they'd call any other tool.

## Ontologies

### iSAQB Architecture Ontology

The [iSAQB Foundation Level](https://www.isaqb.org/) curriculum as a formal OWL ontology. Provides the vocabulary for Tulla's planning phase to generate and enforce architectural decisions:

| Class | Purpose | iSAQB Reference |
|-------|---------|-----------------|
| `isaqb:QualityAttribute` | ISO/IEC 25010:2023 quality properties | LG 01-03, 04-06 |
| `isaqb:QualityScenario` | Testable quality scenarios (stimulus → response → measure) | LG 04-06 |
| `isaqb:ArchitectureDecision` | ADRs with context, options, consequences | LG 04-08 |
| `isaqb:ArchitecturalPattern` | Layers, Microservices, CQRS, Pipes-and-Filter, etc. | LG 03-08 |
| `isaqb:DesignPattern` | Adapter, Factory, Strategy, Observer, etc. | LG 03-09 |
| `isaqb:DesignPrinciple` | Abstraction, Modularization, Robustness, etc. | LG 03-04 |
| `isaqb:CrossCuttingConcern` | Concerns affecting multiple building blocks | LG 03-10 |
| `isaqb:Risk` / `isaqb:TechnicalDebt` | Architecture risks and documented shortcuts | LG 05-01 |

### Visual Artifacts Ontology (VAO)

A complete domain model for presentations, social media content, and diagrams. Enables LLMs to generate visual compositions they were *never explicitly trained on* — by reading formal specs of what's possible and composing from there:

- Slide types, layout system (grid, flow, absolute), typography, color palettes
- Platform constraints (LinkedIn carousel: 1080x1080, 6-10 slides)
- Diagram types mapped to rendering tools (Mermaid, Graphviz, D2, Vega-Lite)
- SHACL shapes for structural validation of generated visuals

See [ontology/domain/visual-artifacts/README.md](ontology/domain/visual-artifacts/README.md) for the full spec.

### Idea Pool Ontology

Lifecycle tracking for ideas as SKOS concepts, with a 13-state workflow, dependency tracking, and Wikidata entity grounding.

## Quick Start

```bash
# Clone and install
git clone https://github.com/hpz/semantic-tool-use.git
cd semantic-tool-use
uv sync --all-extras

# Start the server (REST API + MCP SSE + Knowledge Graph)
./start-ontology-server.sh

# Or directly
python -m ontology_server --http --port 8100 --enable-abox
```

The server exposes:
- **REST API** at `http://localhost:8100`
- **MCP SSE** at `http://localhost:8100/sse` (plug into Claude Code, Cursor, etc.)
- **Dashboard** at `http://localhost:8100/dashboard`

### Connect to Claude Code

```json
// ~/.claude/claude_code_config.json
{
  "mcpServers": {
    "ontology": {
      "command": "python3",
      "args": ["-m", "ontology_server", "--ontology-path", "/path/to/ontologies"]
    }
  }
}
```

### Load Tulla's ontologies

```bash
python -m ontology_server --http --enable-abox \
    --ontology-path ./ontology/domain/visual-artifacts \
    --ontology-path /path/to/tulla/ontologies  # isaqb, phase, prd, code ontologies
```

## MCP Tools

### Ontology (T-Box)

| Tool | Description |
|------|-------------|
| `list_ontologies` | List loaded ontologies with class/property counts |
| `get_ontology` | Retrieve full ontology as Turtle |
| `query_ontology` | Execute SPARQL queries against any ontology |
| `get_classes` / `get_properties` | Introspect schema elements |
| `add_triple` / `remove_triple` / `update_triple` | Mutate ontology graphs |
| `validate_instance` | Validate RDF data against SHACL shapes |
| `search_ontology` | Full-text search over labels and comments |
| `validate_ontology_quality` | Meta-validation of ontology best practices |

### Knowledge Graph (A-Box) — with `--enable-abox`

| Tool | Description |
|------|-------------|
| `create_idea` / `query_ideas` / `update_idea` | SKOS-based idea management |
| `set_lifecycle` | State machine transitions (seed → backlog → researching → completed) |
| `store_fact` / `recall_facts` / `forget_fact` | Agent memory with confidence scores |
| `lookup_wikidata` / `query_wikidata` | Entity grounding via Wikidata SPARQL |
| `sparql_query` | Raw SPARQL across all named graphs |

## Deployment

### As a service

```bash
# Auto-detects macOS (launchd) or Linux (systemd)
./service/install.sh

# With options
./service/install.sh --port 9000 --auth
```

### Docker

```bash
docker compose up
```

### Configuration

CLI args or environment variables (`ONTOLOGY_` prefix):

```bash
python -m ontology_server \
    --http \
    --port 8100 \
    --ontology-path ./ontology/domain/visual-artifacts \
    --ontology-path /other/project/ontologies \  # load from multiple dirs
    --enable-abox \
    --kg-persist ~/.semantic-tool-use/kg \
    --enable-search                              # semantic search (sentence-transformers)
```

## Project Structure

```
semantic-tool-use/
├── src/
│   ├── ontology_server/         # MCP + REST server (T-Box)
│   │   ├── core/                # OntologyStore, SHACL validation
│   │   ├── mcp/                 # FastMCP protocol server
│   │   ├── api/                 # FastAPI REST layer
│   │   └── dashboard/           # Web UI
│   └── knowledge_graph/         # Persistent A-Box (Oxigraph)
│       └── core/                # Ideas, memory, lifecycle, Wikidata
├── ontology/domain/
│   ├── visual-artifacts/        # VAO: presentations, social, diagrams
│   └── idea-pool/               # Idea lifecycle ontology
├── service/                     # launchd + systemd templates
├── tests/                       # pytest suite
└── archive/                     # v1 research prototype + thesis
```


## Development

```bash
pytest tests/ -x -q              # run tests
ruff check src/ tests/           # lint
mypy src/                        # type check
```

## License

[Apache License 2.0](LICENSE)
