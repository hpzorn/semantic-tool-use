# Annotation Coverage Query Requirements

**Document for**: Feature 20 (Requirement Detail: Annotation coverage)
**Depends on**: Annotation Data Model (req-74-4-4a)
**Quality Focus**: isaqb:Maintainability

## Overview

This document specifies the SPARQL query patterns for calculating annotation coverage for requirements. Coverage is calculated as the ratio of annotated line ranges to total implementation lines, grouped by source file. These queries enable the `requirement_detail.html` template to render a file-by-file breakdown of implementation coverage.

---

## Namespace Prefixes

```sparql
PREFIX trace: <http://impl-ralph.io/trace#>
PREFIX prd: <http://impl-ralph.io/prd#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
```

---

## Query 1: Find All Annotations for a Requirement

**Purpose**: Retrieve all `trace:Annotation` instances that implement a given requirement URI.

**Use Case**: Display list of all code locations implementing this requirement.

### SPARQL Pattern

```sparql
PREFIX trace: <http://impl-ralph.io/trace#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

SELECT ?annotation ?sourceFile ?startLine ?endLine ?annotationText
WHERE {
    ?annotation a trace:Annotation ;
                trace:implements <{requirement_uri}> ;
                trace:sourceFile ?sourceFile ;
                trace:startLine ?startLine ;
                trace:endLine ?endLine ;
                trace:annotationText ?annotationText .
}
ORDER BY ?sourceFile ?startLine
```

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `{requirement_uri}` | URI | Full URI of the requirement (e.g., `http://impl-ralph.io/prd#req-74-1-1` or compact `prd:req-74-1-1`) |

### Result Shape

| Column | Type | Description |
|--------|------|-------------|
| `annotation` | URI | The annotation instance URI (e.g., `trace:annotation-a1b2c3d4-...`) |
| `sourceFile` | xsd:string | Relative path to source file (e.g., `src/ontology_server/dashboard/__init__.py`) |
| `startLine` | xsd:integer | First line number (1-indexed) |
| `endLine` | xsd:integer | Last line number (1-indexed, inclusive) |
| `annotationText` | xsd:string | Original annotation comment text |

### Example Result

| annotation | sourceFile | startLine | endLine | annotationText |
|------------|------------|-----------|---------|----------------|
| trace:annotation-a1b2... | src/ontology_server/dashboard/__init__.py | 45 | 58 | impl(prd:req-74-1-1): Expand Namespace Prefix Registry |
| trace:annotation-b2c3... | src/ontology_server/dashboard/__init__.py | 62 | 65 | impl(prd:req-74-1-1): Additional prefix for visual artifacts |

---

## Query 2: Group Annotations by Source File

**Purpose**: Aggregate annotation counts and line ranges per source file for a given requirement.

**Use Case**: Build file-by-file coverage summary for rendering in the template.

### SPARQL Pattern

```sparql
PREFIX trace: <http://impl-ralph.io/trace#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

SELECT ?sourceFile
       (COUNT(?annotation) AS ?annotationCount)
       (SUM(?endLine - ?startLine + 1) AS ?annotatedLines)
       (GROUP_CONCAT(?startLine; separator=",") AS ?startLines)
       (GROUP_CONCAT(?endLine; separator=",") AS ?endLines)
WHERE {
    ?annotation a trace:Annotation ;
                trace:implements <{requirement_uri}> ;
                trace:sourceFile ?sourceFile ;
                trace:startLine ?startLine ;
                trace:endLine ?endLine .
}
GROUP BY ?sourceFile
ORDER BY ?sourceFile
```

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `{requirement_uri}` | URI | Full URI of the requirement |

### Result Shape

| Column | Type | Description |
|--------|------|-------------|
| `sourceFile` | xsd:string | Relative path to source file |
| `annotationCount` | xsd:integer | Number of annotations in this file |
| `annotatedLines` | xsd:integer | Total annotated lines (sum of all ranges) |
| `startLines` | xsd:string | Comma-separated start line numbers |
| `endLines` | xsd:string | Comma-separated end line numbers |

### Example Result

| sourceFile | annotationCount | annotatedLines | startLines | endLines |
|------------|-----------------|----------------|------------|----------|
| src/ontology_server/dashboard/__init__.py | 2 | 18 | 45,62 | 58,65 |
| src/ontology_server/dashboard/routes.py | 1 | 16 | 127 | 142 |

---

## Query 3: Count Total Annotations for a Requirement

**Purpose**: Quick check for whether any annotations exist (for conditional rendering).

**Use Case**: `has_annotations()` method to decide whether to show coverage section.

### SPARQL Pattern

```sparql
PREFIX trace: <http://impl-ralph.io/trace#>

SELECT (COUNT(?annotation) AS ?totalAnnotations)
WHERE {
    ?annotation a trace:Annotation ;
                trace:implements <{requirement_uri}> .
}
```

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `{requirement_uri}` | URI | Full URI of the requirement |

### Result Shape

| Column | Type | Description |
|--------|------|-------------|
| `totalAnnotations` | xsd:integer | Total count of annotations |

---

## Coverage Percentage Calculation

### Algorithm

Coverage percentage is calculated per-file as the ratio of annotated lines to total file lines:

```
coverage_percentage = (annotated_lines / total_file_lines) * 100
```

**Note**: `total_file_lines` must be obtained from the filesystem, not the RDF store. The DashboardService method should:

1. Execute Query 2 to get `annotatedLines` per file
2. For each `sourceFile`, read the file from disk to count total lines
3. Calculate percentage: `(annotatedLines / totalLines) * 100`
4. Handle missing files gracefully (file deleted but annotation remains)

### Edge Cases

| Scenario | Handling |
|----------|----------|
| File not found on disk | Mark as "File Missing", show annotated lines only |
| Overlapping line ranges | Count each line only once (merge ranges before summing) |
| Zero total lines | Return 0% coverage |
| No annotations | Return empty coverage (don't show section) |

---

## DashboardService Method Signatures

### get_requirement_annotations(requirement_uri: str) -> list[dict]

Executes Query 1 and returns annotation details.

**Returns**: List of dicts with keys:
- `id`: Annotation URI (string)
- `source_file`: Relative file path (string)
- `start_line`: First line number (int)
- `end_line`: Last line number (int)
- `text`: Annotation comment text (string)

### get_requirement_annotation_coverage(requirement_uri: str) -> dict

Executes Query 2 and calculates coverage statistics.

**Returns**: Dict with keys:
- `total_annotations`: Count of all annotations (int)
- `files`: List of file coverage dicts (see below)
- `overall_percentage`: Weighted average coverage (float)

**File coverage dict keys**:
- `path`: Relative file path (string)
- `annotation_count`: Number of annotations in file (int)
- `annotated_lines`: Count of lines covered by annotations (int)
- `total_lines`: Total lines in file (int, or None if file missing)
- `percentage`: Coverage percentage (float, or None if file missing)
- `line_ranges`: List of `{"start": int, "end": int}` dicts

### has_annotations(requirement_uri: str) -> bool

Executes Query 3 and returns `True` if `totalAnnotations > 0`.

---

## Template Rendering Specification

### requirement_detail.html Coverage Section

The annotation coverage section renders as a file-by-file breakdown showing:
- Filename (clickable to expand/collapse)
- Line count (annotated / total)
- Percentage bar visualization

### HTML Structure

```html
{# ── Annotation Coverage ── #}
{% if annotation_coverage and annotation_coverage.total_annotations > 0 %}
<h2>Implementation Coverage</h2>
<div class="coverage-summary">
    <span class="coverage-count">{{ annotation_coverage.total_annotations }} annotation(s)</span>
    <span class="coverage-overall">{{ "%.1f"|format(annotation_coverage.overall_percentage) }}% overall</span>
</div>

<div class="coverage-files">
    {% for file in annotation_coverage.files %}
    <div class="coverage-file">
        <div class="coverage-file-header">
            <code class="coverage-filename">{{ file.path }}</code>
            <span class="coverage-stats">
                {{ file.annotated_lines }}{% if file.total_lines %}/{{ file.total_lines }}{% endif %} lines
            </span>
        </div>
        {% if file.percentage is not none %}
        <div class="coverage-bar-container">
            <div class="coverage-bar" style="width: {{ file.percentage }}%"></div>
            <span class="coverage-percentage">{{ "%.1f"|format(file.percentage) }}%</span>
        </div>
        {% else %}
        <div class="coverage-missing">File not found</div>
        {% endif %}
        <div class="coverage-ranges">
            {% for range in file.line_ranges %}
            <span class="coverage-range">L{{ range.start }}{% if range.start != range.end %}-{{ range.end }}{% endif %}</span>
            {% endfor %}
        </div>
    </div>
    {% endfor %}
</div>
{% else %}
<h2>Implementation Coverage</h2>
<p class="text-muted">No implementation annotations found. Annotations are added when the pipeline persists implementation markers.</p>
{% endif %}
```

### CSS Styling

```css
/* ── Annotation Coverage ────────────────────────────── */
.coverage-summary {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.75rem 1rem;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius);
    margin-bottom: 1rem;
}

.coverage-count {
    font-weight: 600;
    color: var(--color-text);
}

.coverage-overall {
    font-weight: 500;
    color: var(--color-primary);
}

.coverage-files {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
}

.coverage-file {
    padding: 0.75rem;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius);
}

.coverage-file-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.5rem;
}

.coverage-filename {
    font-size: 0.875rem;
    font-weight: 500;
    color: var(--color-text);
    word-break: break-all;
}

.coverage-stats {
    font-size: 0.8rem;
    color: var(--color-text-muted);
    white-space: nowrap;
    margin-left: 1rem;
}

.coverage-bar-container {
    position: relative;
    height: 1.25rem;
    background: var(--color-bg);
    border-radius: 4px;
    overflow: hidden;
    margin-bottom: 0.5rem;
}

.coverage-bar {
    height: 100%;
    background: linear-gradient(90deg, #198754, #20c997);
    border-radius: 4px;
    transition: width 0.3s ease;
}

.coverage-percentage {
    position: absolute;
    right: 0.5rem;
    top: 50%;
    transform: translateY(-50%);
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--color-text);
}

.coverage-missing {
    padding: 0.25rem 0.5rem;
    background: #fff3cd;
    color: #856404;
    font-size: 0.8rem;
    border-radius: 4px;
    margin-bottom: 0.5rem;
}

.coverage-ranges {
    display: flex;
    flex-wrap: wrap;
    gap: 0.375rem;
}

.coverage-range {
    padding: 0.15rem 0.4rem;
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: 3px;
    font-size: 0.7rem;
    font-family: monospace;
    color: var(--color-text-muted);
}
```

---

## Integration with Existing Architecture

### Route Handler Updates

The `requirement_detail` route in `routes.py` should:

1. Call `service.has_annotations(subject)` to check for annotations
2. If annotations exist, call `service.get_requirement_annotation_coverage(subject)`
3. Pass `annotation_coverage` dict to template context

### Minimal Code Changes

Following the "Extension Over Creation" principle:

```python
# In routes.py requirement_detail route
annotation_coverage = None
if service.has_annotations(subject):
    annotation_coverage = service.get_requirement_annotation_coverage(subject)

# Add to template context
context["annotation_coverage"] = annotation_coverage
```

---

## Query Execution Context

### Named Graph Targeting

All queries should target the appropriate named graph for the PRD context:

```sparql
# For requirement prd:req-74-1-1, use named graph prd-idea-74
FROM NAMED <prd-idea-74>
```

Alternatively, using the agent memory recall pattern with `context="prd-idea-74"`.

### Memory Store Integration

When using the existing `AgentMemory.recall()` pattern (as seen in `DashboardService`):

```python
# Pattern for finding annotations via recall
annotations = self._agent_memory.recall(
    context=context,  # e.g., "prd-idea-74"
    predicate="trace:implements",
    object=requirement_uri,  # e.g., "prd:req-74-1-1"
    limit=10000,
)
```

Then for each annotation subject, recall all its properties:

```python
for ann in annotations:
    ann_facts = self._agent_memory.recall(
        subject=ann["subject"],
        context=context,
        limit=100,
    )
    # Build annotation dict from facts
```

---

## Related Requirements

- **req-74-4-4a**: Annotation Data Model (dependency - defines the data structure)
- **Feature 20**: Requirement Detail: Annotation coverage (blocked on annotation persistence)
- **ADR-74-4**: hx-boost for SPA Navigation

---

## Revision History

| Date | Version | Author | Changes |
|------|---------|--------|---------|
| 2026-02-05 | 1.0 | Implementation-Tulla | Initial specification |
