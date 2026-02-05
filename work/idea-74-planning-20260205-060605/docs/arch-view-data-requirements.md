# Architecture View Data Structure Requirements

**Document for**: Features 21-23 (Architecture View: Quality goals, Principles, ADR browser)
**Blocked on**: idea-42 (Architecture Context Data Creation)
**Quality Focus**: isaqb:Maintainability

## Overview

This document specifies the expected RDF data structure for the architecture view. The architecture view will display quality goals, design principles, and Architecture Decision Records (ADRs) for a given idea. This view is blocked until idea-42 creates the `arch-idea-N` context data in the A-Box.

---

## Namespace Prefixes

```turtle
@prefix arch: <http://impl-ralph.io/arch#> .
@prefix ideas: <http://semantic-tool-use.org/ideas/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
```

---

## Named Graph Convention

Architecture data for idea N is stored in named graph: `arch-idea-N`

Example: Architecture data for idea 74 → named graph `arch-idea-74`

---

## Data Structure for Feature 21: Quality Goals

Quality goals are stored as `arch:qualityGoal` predicates on the idea subject.

### Triple Pattern

```turtle
# In named graph: arch-idea-{N}

ideas:idea-{N} arch:qualityGoal "{quality-attribute}: {description}" .
```

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| Subject | URI | `ideas:idea-{N}` - reference to the idea |
| Predicate | URI | `arch:qualityGoal` |
| Object | Literal | String with format `"{QualityAttribute}: {Description}"` |

### Example Triples (idea-74)

```turtle
# Named graph: arch-idea-74

ideas:idea-74 arch:qualityGoal "Usability: seconds-not-minutes status checks, 4-5 actions to 1 page load" .
ideas:idea-74 arch:qualityGoal "Extensibility: new domain types render via generic fallback without code changes" .
ideas:idea-74 arch:qualityGoal "Maintainability: ~175 lines across ~8 files, incremental enhancement not new system" .
```

---

## Data Structure for Feature 22: Design Principles

Design principles are stored as `arch:designPrinciple` predicates on the idea subject.

### Triple Pattern

```turtle
# In named graph: arch-idea-{N}

ideas:idea-{N} arch:designPrinciple "{principle-name}: {description}" .
```

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| Subject | URI | `ideas:idea-{N}` - reference to the idea |
| Predicate | URI | `arch:designPrinciple` |
| Object | Literal | String with format `"{PrincipleName}: {Description}"` |

### Example Triples (idea-74)

```turtle
# Named graph: arch-idea-74

ideas:idea-74 arch:designPrinciple "Extension Over Creation: all features use existing service methods, routes, templates" .
ideas:idea-74 arch:designPrinciple "Schema-First Rendering: type dispatch registry maps RDF types to templates" .
ideas:idea-74 arch:designPrinciple "Minimize New Code: target ~175 lines, reuse DashboardService methods" .
```

---

## Data Structure for Feature 23: ADR Browser

ADRs are stored as separate subjects with the pattern `arch:adr-{idea}-{N}` with three predicates: `arch:decision`, `arch:context`, and `arch:status`.

### Triple Pattern

```turtle
# In named graph: arch-idea-{N}

arch:adr-{idea}-{ADR-number} a arch:ArchitectureDecisionRecord ;
    dcterms:title "{short-title}" ;
    arch:context "{context-description}" ;
    arch:decision "{decision-description}" ;
    arch:status "{status-value}" ;
    dcterms:date "{YYYY-MM-DD}"^^xsd:date .
```

### Required Fields

| Field | Predicate | Type | Description |
|-------|-----------|------|-------------|
| Type | `rdf:type` | URI | `arch:ArchitectureDecisionRecord` |
| Title | `dcterms:title` | Literal | Short title for the ADR |
| Context | `arch:context` | Literal | Problem context that led to the decision |
| Decision | `arch:decision` | Literal | The decision made |
| Status | `arch:status` | Literal | One of: `proposed`, `accepted`, `deprecated`, `superseded` |
| Date | `dcterms:date` | xsd:date | Date the ADR was recorded |

### Example Triples (idea-74)

```turtle
# Named graph: arch-idea-74

arch:adr-74-1 a arch:ArchitectureDecisionRecord ;
    dcterms:title "Registry-Based Type Dispatch" ;
    arch:context "URI resolver needs to map arbitrary URIs to appropriate detail views" ;
    arch:decision "Use a Python dict registry mapping RDF type URIs to route names, with iteration over types and hierarchy fallback to generic_detail" ;
    arch:status "accepted" ;
    dcterms:date "2026-02-05"^^xsd:date .

arch:adr-74-2 a arch:ArchitectureDecisionRecord ;
    dcterms:title "hx-boost SPA Navigation" ;
    arch:context "Dashboard navigation feels slow due to full page reloads" ;
    arch:decision "Add hx-boost=true to main element; override with hx-boost=false on external links" ;
    arch:status "accepted" ;
    dcterms:date "2026-02-05"^^xsd:date .

arch:adr-74-3 a arch:ArchitectureDecisionRecord ;
    dcterms:title "Context Naming Convention" ;
    arch:context "Need to discover related contexts (PRD, arch, lesson) for an idea" ;
    arch:decision "Use {type}-idea-{id} naming convention, detect via string prefix matching" ;
    arch:status "accepted" ;
    dcterms:date "2026-02-05"^^xsd:date .

arch:adr-74-4 a arch:ArchitectureDecisionRecord ;
    dcterms:title "Defer Architecture/Lesson Views" ;
    arch:context "P1 scope includes architecture and lesson views, but upstream data doesn't exist" ;
    arch:decision "Mark features 7, 8, 18, 20-23 as P3 (blocked), implement placeholder UI only when contexts exist" ;
    arch:status "accepted" ;
    dcterms:date "2026-02-05"^^xsd:date .

arch:adr-74-5 a arch:ArchitectureDecisionRecord ;
    dcterms:title "Service Layer for All Data Access" ;
    arch:context "New routes need KG queries for phase data, progress, etc" ;
    arch:decision "All data access goes through DashboardService; no direct store calls in routes" ;
    arch:status "accepted" ;
    dcterms:date "2026-02-05"^^xsd:date .
```

---

## Sample SPARQL Queries

### Query 1: Get Quality Goals for an Idea

```sparql
PREFIX arch: <http://impl-ralph.io/arch#>
PREFIX ideas: <http://semantic-tool-use.org/ideas/>

SELECT ?goal
FROM <arch-idea-74>
WHERE {
    ideas:idea-74 arch:qualityGoal ?goal .
}
ORDER BY ?goal
```

**Expected Result**:
| goal |
|------|
| "Extensibility: new domain types render via generic fallback without code changes" |
| "Maintainability: ~175 lines across ~8 files, incremental enhancement not new system" |
| "Usability: seconds-not-minutes status checks, 4-5 actions to 1 page load" |

---

### Query 2: Get Design Principles for an Idea

```sparql
PREFIX arch: <http://impl-ralph.io/arch#>
PREFIX ideas: <http://semantic-tool-use.org/ideas/>

SELECT ?principle
FROM <arch-idea-74>
WHERE {
    ideas:idea-74 arch:designPrinciple ?principle .
}
ORDER BY ?principle
```

**Expected Result**:
| principle |
|-----------|
| "Extension Over Creation: all features use existing service methods, routes, templates" |
| "Minimize New Code: target ~175 lines, reuse DashboardService methods" |
| "Schema-First Rendering: type dispatch registry maps RDF types to templates" |

---

### Query 3: Get All ADRs for an Idea

```sparql
PREFIX arch: <http://impl-ralph.io/arch#>
PREFIX dcterms: <http://purl.org/dc/terms/>

SELECT ?adr ?title ?context ?decision ?status ?date
FROM <arch-idea-74>
WHERE {
    ?adr a arch:ArchitectureDecisionRecord ;
         dcterms:title ?title ;
         arch:context ?context ;
         arch:decision ?decision ;
         arch:status ?status .
    OPTIONAL { ?adr dcterms:date ?date }
}
ORDER BY ?adr
```

**Expected Result**:
| adr | title | context | decision | status | date |
|-----|-------|---------|----------|--------|------|
| arch:adr-74-1 | Registry-Based Type Dispatch | URI resolver needs to map... | Use a Python dict registry... | accepted | 2026-02-05 |
| arch:adr-74-2 | hx-boost SPA Navigation | Dashboard navigation feels slow... | Add hx-boost=true to main... | accepted | 2026-02-05 |
| ... | ... | ... | ... | ... | ... |

---

### Query 4: Get Accepted ADRs Only

```sparql
PREFIX arch: <http://impl-ralph.io/arch#>
PREFIX dcterms: <http://purl.org/dc/terms/>

SELECT ?adr ?title ?decision
FROM <arch-idea-74>
WHERE {
    ?adr a arch:ArchitectureDecisionRecord ;
         dcterms:title ?title ;
         arch:decision ?decision ;
         arch:status "accepted" .
}
ORDER BY ?adr
```

---

### Query 5: Count Architecture Artifacts for Summary Display

```sparql
PREFIX arch: <http://impl-ralph.io/arch#>
PREFIX ideas: <http://semantic-tool-use.org/ideas/>

SELECT
    (COUNT(DISTINCT ?goal) AS ?goalCount)
    (COUNT(DISTINCT ?principle) AS ?principleCount)
    (COUNT(DISTINCT ?adr) AS ?adrCount)
FROM <arch-idea-74>
WHERE {
    {
        ideas:idea-74 arch:qualityGoal ?goal .
    } UNION {
        ideas:idea-74 arch:designPrinciple ?principle .
    } UNION {
        ?adr a arch:ArchitectureDecisionRecord .
    }
}
```

**Expected Result**:
| goalCount | principleCount | adrCount |
|-----------|----------------|----------|
| 3 | 3 | 5 |

---

### Query 6: Check if Architecture Context Exists

This query is used to determine if the architecture context link should be enabled in the idea detail view.

```sparql
PREFIX arch: <http://impl-ralph.io/arch#>
PREFIX ideas: <http://semantic-tool-use.org/ideas/>

ASK
FROM <arch-idea-74>
WHERE {
    { ideas:idea-74 arch:qualityGoal ?goal . }
    UNION
    { ideas:idea-74 arch:designPrinciple ?principle . }
    UNION
    { ?adr a arch:ArchitectureDecisionRecord . }
}
```

---

## DashboardService Methods (Future Implementation)

When idea-42 completes, these service methods will be added:

### get_architecture_quality_goals(idea_id: str) -> list[str]
Returns list of quality goal strings for the idea.

### get_architecture_principles(idea_id: str) -> list[str]
Returns list of design principle strings for the idea.

### get_architecture_adrs(idea_id: str) -> list[dict]
Returns list of ADR dictionaries with keys: `id`, `title`, `context`, `decision`, `status`, `date`.

### get_architecture_summary(idea_id: str) -> dict
Returns summary dict with keys: `goal_count`, `principle_count`, `adr_count`, `exists`.

---

## Template Requirements (arch_detail.html)

The architecture view template will have three sections:

1. **Quality Goals Section**: Displays quality attributes with descriptions
2. **Design Principles Section**: Displays principles with category and description
3. **ADR Browser Section**: Table of ADRs with title, status badge, and expandable details

See req-74-4-3b for template specification details.

---

## Related Requirements

- **req-74-4-3b**: Document Architecture View Template (depends on this document)
- **idea-42**: Create architecture context data in A-Box (blocking dependency)
- **ADR-74-4**: Defer Arch/Lesson Views decision

---

## Revision History

| Date | Version | Author | Changes |
|------|---------|--------|---------|
| 2026-02-05 | 1.0 | Implementation-Tulla | Initial specification |
