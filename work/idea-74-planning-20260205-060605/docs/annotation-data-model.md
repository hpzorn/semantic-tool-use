# Annotation Data Model Requirements

**Document for**: Feature 20 (Requirement Detail: Annotation coverage)
**Blocked on**: Annotation persistence implementation in the pipeline
**Quality Focus**: isaqb:Maintainability

## Overview

This document specifies the expected RDF data model for implementation annotations. Annotations link requirements to their implementing source code, enabling traceability from requirements through to specific file locations and line ranges. This view is blocked until the annotation persistence system is implemented in the pipeline.

---

## Namespace Prefixes

```turtle
@prefix trace: <http://impl-ralph.io/trace#> .
@prefix prd: <http://impl-ralph.io/prd#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
```

### Namespace Definitions

| Prefix | IRI | Description |
|--------|-----|-------------|
| `trace:` | `http://impl-ralph.io/trace#` | Traceability vocabulary for implementation annotations |
| `prd:` | `http://impl-ralph.io/prd#` | PRD vocabulary for requirements |
| `xsd:` | `http://www.w3.org/2001/XMLSchema#` | XML Schema datatypes |

---

## Named Graph Convention

Annotation data is stored in the same named graph as the PRD context it annotates: `prd-idea-{N}`

Example: Annotations for idea 74 requirements → named graph `prd-idea-74`

---

## Data Structure: Annotation Instances

Annotations are stored as `trace:Annotation` instances with predicates linking them to requirements, source files, line ranges, and annotation text.

### Triple Pattern

```turtle
# In named graph: prd-idea-{N}

trace:annotation-{uuid} a trace:Annotation ;
    trace:implements prd:req-{idea}-{task} ;
    trace:sourceFile "{relative/path/to/file.py}" ;
    trace:startLine {start-line}^^xsd:integer ;
    trace:endLine {end-line}^^xsd:integer ;
    trace:annotationText "{original annotation text}" .
```

### Required Fields

| Field | Predicate | Type | Description |
|-------|-----------|------|-------------|
| Type | `rdf:type` | URI | `trace:Annotation` |
| Implements | `trace:implements` | URI | Reference to the requirement being implemented (e.g., `prd:req-74-1-1`) |
| Source File | `trace:sourceFile` | Literal | Relative file path from project root (e.g., `src/ontology_server/dashboard/routes.py`) |
| Start Line | `trace:startLine` | xsd:integer | First line number of the annotated code block (1-indexed) |
| End Line | `trace:endLine` | xsd:integer | Last line number of the annotated code block (inclusive, 1-indexed) |
| Annotation Text | `trace:annotationText` | Literal | Original annotation comment text as found in source code |

### Optional Fields

| Field | Predicate | Type | Description |
|-------|-----------|------|-------------|
| Created | `trace:createdAt` | xsd:dateTime | Timestamp when annotation was persisted |
| Commit | `trace:commitSha` | Literal | Git commit SHA where annotation was added |

---

## Example Triples (idea-74)

The following example shows a complete annotation linking requirement `prd:req-74-1-1` (Expand Namespace Prefix Registry) to its implementation in the dashboard `__init__.py` file.

```turtle
# Named graph: prd-idea-74

# Annotation linking requirement to implementation
trace:annotation-a1b2c3d4-e5f6-7890-abcd-ef1234567890 a trace:Annotation ;
    trace:implements prd:req-74-1-1 ;
    trace:sourceFile "src/ontology_server/dashboard/__init__.py" ;
    trace:startLine 45^^xsd:integer ;
    trace:endLine 58^^xsd:integer ;
    trace:annotationText "impl(prd:req-74-1-1): Expand Namespace Prefix Registry" .

# Another annotation for the same requirement (multi-location implementation)
trace:annotation-b2c3d4e5-f6a7-8901-bcde-f23456789012 a trace:Annotation ;
    trace:implements prd:req-74-1-1 ;
    trace:sourceFile "src/ontology_server/dashboard/__init__.py" ;
    trace:startLine 62^^xsd:integer ;
    trace:endLine 65^^xsd:integer ;
    trace:annotationText "impl(prd:req-74-1-1): Additional prefix for visual artifacts" .

# Annotation for a different requirement
trace:annotation-c3d4e5f6-a7b8-9012-cdef-345678901234 a trace:Annotation ;
    trace:implements prd:req-74-1-4 ;
    trace:sourceFile "src/ontology_server/dashboard/routes.py" ;
    trace:startLine 127^^xsd:integer ;
    trace:endLine 142^^xsd:integer ;
    trace:annotationText "impl(prd:req-74-1-4): Add PRD Progress Bar to Idea Detail Page" .

# Annotation spanning multiple files (same requirement, different file)
trace:annotation-d4e5f6a7-b8c9-0123-defa-456789012345 a trace:Annotation ;
    trace:implements prd:req-74-1-4 ;
    trace:sourceFile "src/ontology_server/dashboard/templates/idea_detail.html" ;
    trace:startLine 85^^xsd:integer ;
    trace:endLine 98^^xsd:integer ;
    trace:annotationText "impl(prd:req-74-1-4): Progress bar template section" .
```

---

## Annotation Pattern in Source Code

Annotations in source code follow the pattern `impl(prd:req-{idea}-{task})` in comments:

### Python Example

```python
# impl(prd:req-74-1-1): Expand Namespace Prefix Registry
_SHORT_URI_PREFIXES = [
    ("http://impl-ralph.io/phase#", "phase:"),
    ("http://impl-ralph.io/prd#", "prd:"),
    ("http://impl-ralph.io/trace#", "trace:"),
    ("http://semantic-tool-use.org/ontology/tool-use#", "stu:"),
    # ... additional prefixes
]
```

### HTML/Jinja Example

```html
{# impl(prd:req-74-1-4): Progress bar template section #}
<div class="progress-container">
    <div class="progress-bar" style="width: {{ progress.percentage }}%"></div>
    <span class="progress-label">{{ progress.completed }}/{{ progress.total }}</span>
</div>
```

### CSS Example

```css
/* impl(prd:req-74-2-3): Phase trail badge styling */
.phase-badge {
    display: inline-block;
    padding: 0.25rem 0.5rem;
    border-radius: 4px;
    font-size: 0.875rem;
}
```

---

## Annotation Lifecycle

### 1. Creation (Pipeline Phase)

When the implementation agent adds an `impl(prd:req-X-Y)` annotation to source code:

1. Parser scans modified files for `impl(prd:req-...)` patterns
2. Extracts requirement URI, file path, line range, and annotation text
3. Generates UUID for new annotation
4. Persists annotation triples to A-Box in the appropriate named graph

### 2. Update (Code Modification)

When annotated code is modified:

1. Parser detects line number changes for existing annotations
2. Updates `trace:startLine` and `trace:endLine` values
3. Preserves annotation UUID and other metadata

### 3. Deletion (Code Removal)

When annotated code is removed:

1. Parser detects missing annotation in source
2. Removes annotation triples from A-Box
3. Or: marks annotation as orphaned (implementation choice)

---

## Schema Definition (T-Box)

The trace vocabulary defines the following classes and properties:

```turtle
# T-Box definitions for trace vocabulary

trace:Annotation a rdfs:Class ;
    rdfs:label "Implementation Annotation" ;
    rdfs:comment "Links a requirement to its implementing code location" .

trace:implements a rdf:Property ;
    rdfs:label "implements" ;
    rdfs:domain trace:Annotation ;
    rdfs:range prd:Requirement ;
    rdfs:comment "The requirement that this annotation implements" .

trace:sourceFile a rdf:Property ;
    rdfs:label "source file" ;
    rdfs:domain trace:Annotation ;
    rdfs:range xsd:string ;
    rdfs:comment "Relative path to the source file containing the annotation" .

trace:startLine a rdf:Property ;
    rdfs:label "start line" ;
    rdfs:domain trace:Annotation ;
    rdfs:range xsd:integer ;
    rdfs:comment "First line number of the annotated code block (1-indexed)" .

trace:endLine a rdf:Property ;
    rdfs:label "end line" ;
    rdfs:domain trace:Annotation ;
    rdfs:range xsd:integer ;
    rdfs:comment "Last line number of the annotated code block (1-indexed, inclusive)" .

trace:annotationText a rdf:Property ;
    rdfs:label "annotation text" ;
    rdfs:domain trace:Annotation ;
    rdfs:range xsd:string ;
    rdfs:comment "Original annotation comment text as found in source code" .
```

---

## Validation Rules

### SHACL Shape for Annotation Validation

```turtle
@prefix sh: <http://www.w3.org/ns/shacl#> .

trace:AnnotationShape a sh:NodeShape ;
    sh:targetClass trace:Annotation ;
    sh:property [
        sh:path trace:implements ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:nodeKind sh:IRI ;
        sh:message "Annotation must implement exactly one requirement" ;
    ] ;
    sh:property [
        sh:path trace:sourceFile ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:datatype xsd:string ;
        sh:pattern "^[^/].*" ;
        sh:message "Source file must be a relative path (no leading slash)" ;
    ] ;
    sh:property [
        sh:path trace:startLine ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:datatype xsd:integer ;
        sh:minInclusive 1 ;
        sh:message "Start line must be a positive integer" ;
    ] ;
    sh:property [
        sh:path trace:endLine ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:datatype xsd:integer ;
        sh:minInclusive 1 ;
        sh:message "End line must be a positive integer" ;
    ] ;
    sh:property [
        sh:path trace:annotationText ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:datatype xsd:string ;
        sh:message "Annotation text is required" ;
    ] ;
    sh:sparql [
        sh:message "End line must be >= start line" ;
        sh:select """
            SELECT $this
            WHERE {
                $this trace:startLine ?start ;
                      trace:endLine ?end .
                FILTER (?end < ?start)
            }
        """ ;
    ] .
```

---

## Related Requirements

- **req-74-4-4b**: Document Annotation Coverage Queries (depends on this document)
- **Feature 20**: Requirement Detail: Annotation coverage (blocked on annotation persistence)
- **ADR-74-4**: Defer Architecture/Lesson Views decision

---

## DashboardService Methods (Future Implementation)

When annotation persistence is implemented, these service methods will be added:

### get_requirement_annotations(requirement_uri: str) -> list[dict]
Returns list of annotation dictionaries with keys: `id`, `source_file`, `start_line`, `end_line`, `text`.

### get_requirement_annotation_coverage(requirement_uri: str) -> dict
Returns coverage summary dict with keys:
- `total_annotations`: Count of all annotations for this requirement
- `files`: List of file coverage dicts with `path`, `line_count`, `annotated_lines`, `percentage`
- `overall_percentage`: Weighted average coverage across all files

### has_annotations(requirement_uri: str) -> bool
Returns True if at least one annotation exists for the requirement.

---

## Revision History

| Date | Version | Author | Changes |
|------|---------|--------|---------|
| 2026-02-05 | 1.0 | Implementation-Tulla | Initial specification |
