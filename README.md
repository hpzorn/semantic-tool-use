# Semantic Tool Use for Neosymbolic AI

Research project investigating whether upper ontologies can serve as an interlingua for LLM-driven tool orchestration with semantic verification.

## Quick Start

```bash
# Run full setup
./setup.sh

# Or check environment first
./setup.sh --check

# Or minimal setup (Python only, no Java/reasoners)
./setup.sh --minimal
```

## Project Structure

```
semantic-tool-use/
├── setup.sh              # Setup script
├── RESEARCH_PLAN.md      # Detailed research plan with task tracking
├── requirements.txt      # Python dependencies
├── pyproject.toml        # Python project config
├── Dockerfile            # Container build
├── docker-compose.yml    # Service orchestration
│
├── docs/                 # Research deliverables
│   ├── ontology-survey/  # WS1: Ontology evaluations
│   ├── related-work/     # WS2: Literature reviews
│   ├── domain-selection/ # WS3: Domain assessments
│   ├── decisions/        # Architecture decisions
│   ├── experiments/      # WS4: Experiment results
│   ├── evaluation/       # WS6: Evaluation results
│   └── paper/            # Publication drafts
│
├── ontology/             # OWL/Turtle files
│   ├── upper/            # Upper ontology (DOLCE/UFO/BFO)
│   ├── domain/           # Domain ontologies (FHIR/BPMN)
│   ├── tools/            # Tool definitions
│   └── alignments/       # Cross-ontology mappings
│
├── src/                  # Python source
│   ├── registry/         # Semantic Tool Registry
│   ├── reasoner/         # OWL Reasoner integration
│   ├── translation/      # LLM → Semantic Request
│   ├── feedback/         # Error feedback generation
│   └── pipeline/         # Full orchestration pipeline
│
├── tests/                # Test suite
│   ├── unit/
│   └── integration/
│
├── data/                 # Datasets
│   ├── synthetic-requests/  # WS4: Training data
│   ├── evaluation-set/      # WS6: Test data
│   └── results/             # Experiment outputs
│
├── prompts/              # LLM prompt templates
│   ├── semantic-request-generation/
│   └── feedback-templates/
│
└── tools/                # Downloaded binaries
    ├── reasoners/        # HermiT, Pellet
    └── jena/             # Apache Jena
```

## Research Plan

See [RESEARCH_PLAN.md](RESEARCH_PLAN.md) for the full research plan with:
- 38 tasks across 6 workstreams
- YAML task definitions for subagent tracking
- Dependency graph
- Parallel execution groups

## Development

### Prerequisites

- Python 3.11+
- Java 17+ (for reasoners)
- Docker (optional, for Fuseki)

### Setup

```bash
# Full setup with reasoners
./setup.sh

# Activate environment
source .venv/bin/activate

# Configure API keys
cp .env.template .env
# Edit .env with your keys

# Run tests
pytest tests/
```

### Running Services

```bash
# Start SPARQL server
docker-compose up fuseki

# Access at http://localhost:3030
```

## Key Components

### Tool Registry (`src/registry/`)
Loads semantic tool definitions from Turtle/JSON-LD and provides query interface.

### Reasoner (`src/reasoner/`)
Wraps HermiT/Pellet for consistency checking and precondition validation.

### Translator (`src/translation/`)
Uses LLMs (Claude, GPT-4) to convert natural language to semantic requests.

### Feedback Generator (`src/feedback/`)
Converts reasoner violations to structured, actionable feedback.

### Pipeline (`src/pipeline/`)
Orchestrates: translate → verify → feedback → retry loop.

## Success Criteria

1. Minimal ontology defined for tool-use verification
2. LLM produces valid semantic requests >90% of the time
3. Semantic verification catches >50% of errors JSON Schema misses
4. Feedback quality measurably improves LLM self-correction
5. Latency overhead <200ms per request

## Related Ideas

- [Idea 06: Semantic Tool Use](../idea-pool/idea-06-semantic-tool-use.md) - Original research idea
- [Idea 04: XaaC](../idea-pool/idea-04-xaac-everything-as-code.md) - Domain formal languages
- [Idea 05: Formal Proof Verification](../idea-pool/idea-05-formal-proof-for-ai-output.md) - Verification approach

## License

Research project - see LICENSE file.
