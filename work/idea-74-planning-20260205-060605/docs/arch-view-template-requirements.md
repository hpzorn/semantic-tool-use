# Architecture View Template Requirements

**Document for**: Template specification for `arch_detail.html`
**Depends on**: arch-view-data-requirements.md (req-74-4-3a)
**Quality Focus**: isaqb:Maintainability
**ADR Reference**: arch:adr-74-4 (hx-boost for SPA Navigation)

## Overview

This document specifies the Jinja template structure for the architecture detail view (`arch_detail.html`). The template renders quality goals, design principles, and Architecture Decision Records (ADRs) from the `arch-idea-{N}` named graph.

---

## Template Location

```
src/ontology_server/dashboard/templates/arch_detail.html
```

---

## Template Structure Overview

The `arch_detail.html` template extends `base.html` and contains three main sections:

1. **Quality Goals Table** - Displays quality attributes with priority and rationale
2. **Design Principles List** - Shows principles as expandable cards
3. **ADR Browser** - Lists Architecture Decision Records with status badges

---

## Section 1: Quality Goals Table

### Data Source

```python
# From DashboardService.get_architecture_quality_goals(idea_id)
quality_goals: list[dict] = [
    {
        "attribute": "Usability",
        "description": "seconds-not-minutes status checks, 4-5 actions to 1 page load",
        "priority": "high"  # Parsed from position or explicit marker
    },
    ...
]
```

### HTML Wireframe

```html
{# ── Quality Goals ── #}
<h2>Quality Goals</h2>
{% if quality_goals %}
<table class="property-table">
    <thead>
        <tr>
            <th>Quality Attribute</th>
            <th>Priority</th>
            <th>Rationale</th>
        </tr>
    </thead>
    <tbody>
        {% for goal in quality_goals %}
        <tr>
            <td>
                <strong>{{ goal.attribute }}</strong>
            </td>
            <td>
                <span class="priority-badge priority-{{ goal.priority | lower }}">
                    {{ goal.priority | upper }}
                </span>
            </td>
            <td>{{ goal.description }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% else %}
<p class="empty-placeholder">No quality goals defined</p>
{% endif %}
```

### Styling Notes

- Uses existing `property-table` CSS class for consistent table styling
- Uses existing `priority-badge` with `priority-p0`, `priority-p1`, `priority-p2` variants
- Priority mapping: `high` → `p0`, `medium` → `p1`, `low` → `p2`

---

## Section 2: Design Principles List

### Data Source

```python
# From DashboardService.get_architecture_principles(idea_id)
principles: list[dict] = [
    {
        "name": "Extension Over Creation",
        "description": "all features use existing service methods, routes, templates",
        "applicability": "When adding new features"  # Optional context
    },
    ...
]
```

### HTML Wireframe

```html
{# ── Design Principles ── #}
<h2>Design Principles</h2>
{% if principles %}
<div class="principles-list">
    {% for principle in principles %}
    <details class="principle-card">
        <summary class="principle-summary">
            <span class="principle-name">{{ principle.name }}</span>
            {% if principle.applicability %}
            <span class="principle-context">{{ principle.applicability }}</span>
            {% endif %}
        </summary>
        <div class="principle-body">
            <p>{{ principle.description }}</p>
        </div>
    </details>
    {% endfor %}
</div>
{% else %}
<p class="empty-placeholder">No design principles defined</p>
{% endif %}
```

### CSS Classes (New, Follows Existing Patterns)

```css
/* ── Design Principles ────────────────────────────── */
.principles-list {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    margin-bottom: 1.5rem;
}

.principle-card {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    overflow: hidden;
}

.principle-summary {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    padding: 0.75rem 1rem;
    cursor: pointer;
    user-select: none;
    list-style: none;
    transition: background 0.15s;
}

.principle-summary::-webkit-details-marker {
    display: none;
}

.principle-summary:hover {
    background: var(--color-bg);
}

.principle-name {
    font-weight: 600;
    font-size: 0.9rem;
    color: var(--color-text);
}

.principle-context {
    font-size: 0.75rem;
    color: var(--color-text-muted);
    font-style: italic;
}

.principle-body {
    padding: 0.75rem 1rem;
    background: var(--color-bg);
    border-top: 1px solid var(--color-border);
    font-size: 0.875rem;
}

.principle-body p {
    margin: 0;
}
```

### Design Notes

- Uses `<details>` element for native expandable behavior (aligns with existing `dep-section` pattern)
- Follows existing styling from `dependency-card` and `dep-summary` classes
- Principle context is optional and displayed as muted italic text

---

## Section 3: ADR Browser

### Data Source

```python
# From DashboardService.get_architecture_adrs(idea_id)
adrs: list[dict] = [
    {
        "id": "adr-74-1",
        "uri": "http://tulla.dev/arch#adr-74-1",
        "title": "Registry-Based Type Dispatch",
        "context": "URI resolver needs to map arbitrary URIs to appropriate detail views",
        "decision": "Use a Python dict registry mapping RDF type URIs to route names...",
        "status": "accepted",  # proposed | accepted | deprecated | superseded
        "date": "2026-02-05"
    },
    ...
]
```

### HTML Wireframe

```html
{# ── ADR Browser ── #}
<h2>Architecture Decision Records</h2>
{% if adrs %}
<div class="adr-browser">
    {% for adr in adrs %}
    <div class="adr-card">
        <div class="adr-header">
            <span class="adr-id">{{ adr.id }}</span>
            <h3 class="adr-title">{{ adr.title }}</h3>
            <span class="lifecycle-badge lc-{{ adr.status }}">{{ adr.status }}</span>
        </div>
        <div class="adr-context">
            <span class="adr-section-label">Context</span>
            <p>{{ adr.context }}</p>
        </div>
        <div class="adr-decision">
            <span class="adr-section-label">Decision</span>
            <p>{{ adr.decision }}</p>
        </div>
        {% if adr.date %}
        <div class="adr-footer">
            <span class="adr-date">{{ adr.date }}</span>
        </div>
        {% endif %}
    </div>
    {% endfor %}
</div>
{% else %}
<p class="empty-placeholder">No Architecture Decision Records</p>
{% endif %}
```

### CSS Classes (New, Follows Existing Patterns)

```css
/* ── ADR Browser ───────────────────────────────────── */
.adr-browser {
    display: flex;
    flex-direction: column;
    gap: 1rem;
    margin-bottom: 1.5rem;
}

.adr-card {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    overflow: hidden;
}

.adr-header {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.75rem 1rem;
    background: var(--color-bg);
    border-bottom: 1px solid var(--color-border);
    flex-wrap: wrap;
}

.adr-id {
    font-family: monospace;
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--color-primary);
    background: var(--color-surface);
    padding: 0.15em 0.4em;
    border-radius: 3px;
    border: 1px solid var(--color-border);
}

.adr-title {
    flex: 1;
    margin: 0;
    font-size: 1rem;
    font-weight: 600;
    color: var(--color-text);
}

.adr-context,
.adr-decision {
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--color-border);
}

.adr-decision {
    border-bottom: none;
}

.adr-section-label {
    display: block;
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--color-text-muted);
    margin-bottom: 0.25rem;
}

.adr-context p,
.adr-decision p {
    margin: 0;
    font-size: 0.875rem;
    line-height: 1.5;
}

.adr-footer {
    padding: 0.5rem 1rem;
    background: var(--color-bg);
    border-top: 1px solid var(--color-border);
    text-align: right;
}

.adr-date {
    font-size: 0.75rem;
    font-family: monospace;
    color: var(--color-text-muted);
}
```

### Status Badge Mapping

Uses existing `lifecycle-badge` CSS class with status-specific colors:

| Status | CSS Class | Appearance |
|--------|-----------|------------|
| proposed | `lc-backlog` | Orange background (#fff3e0), dark orange text |
| accepted | `lc-completed` | Green background (#d4edda), dark green text |
| deprecated | `lc-archived` | Gray background (#eceff1), gray text |
| superseded | `lc-rejected` | Red background (#f8d7da), dark red text |

---

## Complete Template

```html
{% extends "base.html" %}

{% block title %}Architecture — {{ idea_id }}{% endblock %}

{% block content %}
<div class="arch-detail">
    {% set parents = [
        {'title': 'Dashboard', 'url': dashboard_url(request, 'dashboard')},
        {'title': 'Ideas', 'url': dashboard_url(request, 'idea_list')},
        {'title': idea_id, 'url': dashboard_url(request, 'idea_detail', idea_id=idea_id)}
    ] %}
    {% set current_title = 'Architecture' %}
    {% include "partials/_breadcrumbs.html" %}
    <a href="{{ dashboard_url(request, 'idea_detail', idea_id=idea_id) }}" class="back-link">&larr; {{ idea_id }}</a>

    {% if error %}
    <div class="prd-error">{{ error }}</div>
    {% else %}

    <h1>Architecture: {{ idea_id }}</h1>
    <div class="req-meta">
        <code>arch-{{ idea_id }}</code>
        <span class="lifecycle-badge lc-planning">ARCHITECTURE</span>
    </div>

    {# ── Summary Cards ── #}
    <div class="summary-cards">
        <div class="card">
            <div class="card-value">{{ quality_goals | length }}</div>
            <div class="card-label">Quality Goals</div>
        </div>
        <div class="card">
            <div class="card-value">{{ principles | length }}</div>
            <div class="card-label">Principles</div>
        </div>
        <div class="card">
            <div class="card-value">{{ adrs | length }}</div>
            <div class="card-label">ADRs</div>
        </div>
    </div>

    {# ── Quality Goals ── #}
    <h2>Quality Goals</h2>
    {% if quality_goals %}
    <table class="property-table">
        <thead>
            <tr>
                <th>Quality Attribute</th>
                <th>Priority</th>
                <th>Rationale</th>
            </tr>
        </thead>
        <tbody>
            {% for goal in quality_goals %}
            <tr>
                <td><strong>{{ goal.attribute }}</strong></td>
                <td>
                    <span class="priority-badge priority-{{ goal.priority | lower }}">
                        {{ goal.priority | upper }}
                    </span>
                </td>
                <td>{{ goal.description }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    {% else %}
    <p class="empty-placeholder">No quality goals defined</p>
    {% endif %}

    {# ── Design Principles ── #}
    <h2>Design Principles</h2>
    {% if principles %}
    <div class="principles-list">
        {% for principle in principles %}
        <details class="principle-card">
            <summary class="principle-summary">
                <span class="principle-name">{{ principle.name }}</span>
                {% if principle.applicability %}
                <span class="principle-context">{{ principle.applicability }}</span>
                {% endif %}
            </summary>
            <div class="principle-body">
                <p>{{ principle.description }}</p>
            </div>
        </details>
        {% endfor %}
    </div>
    {% else %}
    <p class="empty-placeholder">No design principles defined</p>
    {% endif %}

    {# ── ADR Browser ── #}
    <h2>Architecture Decision Records</h2>
    {% if adrs %}
    <div class="adr-browser">
        {% for adr in adrs %}
        <div class="adr-card">
            <div class="adr-header">
                <span class="adr-id">{{ adr.id }}</span>
                <h3 class="adr-title">{{ adr.title }}</h3>
                <span class="lifecycle-badge lc-{{ adr.status }}">{{ adr.status }}</span>
            </div>
            <div class="adr-context">
                <span class="adr-section-label">Context</span>
                <p>{{ adr.context }}</p>
            </div>
            <div class="adr-decision">
                <span class="adr-section-label">Decision</span>
                <p>{{ adr.decision }}</p>
            </div>
            {% if adr.date %}
            <div class="adr-footer">
                <span class="adr-date">{{ adr.date }}</span>
            </div>
            {% endif %}
        </div>
        {% endfor %}
    </div>
    {% else %}
    <p class="empty-placeholder">No Architecture Decision Records</p>
    {% endif %}

    {% endif %}
</div>
{% endblock %}
```

---

## CSS Integration

The new CSS classes should be added to `src/ontology_server/dashboard/static/style.css` when the template is implemented. The classes follow existing dashboard patterns:

- Card-based layouts (`prd-card`, `dependency-card`)
- Summary cards (`summary-cards`, `card`, `card-value`, `card-label`)
- Table styling (`property-table`)
- Badge styling (`lifecycle-badge`, `priority-badge`)
- Empty states (`empty-placeholder`)
- Expandable sections (`details`, `summary` pattern from `dep-section`)

---

## Route Registration

The template requires a route in `routes.py`:

```python
@bp.route("/arch/<idea_id>")
async def arch_detail(request: Request, idea_id: str) -> HTMLResponse:
    """Architecture view for an idea."""
    # Implementation deferred until idea-42 completes
    ...
```

---

## Type Registry Entry

Add to `TYPE_REGISTRY` in routes.py:

```python
TYPE_REGISTRY = {
    # ... existing entries ...
    "http://tulla.dev/arch#ArchitectureContext": "arch_detail",
}
```

---

## hx-boost Integration

Per ADR-74-4, the template inherits `hx-boost="true"` from the `<main>` element in `base.html`. No additional HTMX attributes required for standard navigation.

---

## Related Requirements

- **req-74-4-3a**: Architecture View Data Structure Requirements (dependency)
- **idea-42**: Create architecture context data in A-Box (blocking dependency)
- **ADR-74-4**: hx-boost SPA Navigation

---

## Revision History

| Date | Version | Author | Changes |
|------|---------|--------|---------|
| 2026-02-05 | 1.0 | Implementation-Tulla | Initial specification |
