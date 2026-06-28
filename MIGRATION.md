# Ontology MCP — Tool Surface Consolidation & Transport Migration

Status: **design spec — not yet implemented.**
Scope: slim the ontology-server tool surface (63 → 34 + a separate 4-tool
wikidata-server), unify the three transports (MCP / REST / dashboard) onto one
shared store core, and do it **without regressing python-tulla**.

Confirmed decisions (this revision):
1. **REST API stays** — it is python-tulla's transport. It is a first-class,
   regression-protected consumer, not a legacy/dead surface.
2. **Dashboard is read-only today**, moving to **HITL** soon. Human write
   actions arrive later as narrow, named, auth-gated POSTs (never raw graph
   mutation over the cookie session).
3. **No Wikidata in the dashboard.** Wikidata extracts to its own server,
   mounted by no pipeline agent and exposed in no dashboard view.
4. **Fold everything** — every capability is defined **once** in the
   `knowledge_graph` store/service core; MCP tools, REST routes, and
   `DashboardService` become thin adapters over it.
5. **`capture_seed` is consolidated** into `create_idea(lifecycle="seed")`.

---

## 0. Target topology

| Server | Tools | Mounted by |
|--------|------:|-----------|
| `ontology-server` (slimmed) | 27 core + 7 optional onto-eng = **34** | Tulla agents (per allow-list) + python-tulla (REST) |
| `wikidata-server` (new) | **4** | nothing in the pipeline; ad-hoc only |

Surfaces inside `ontology-server`: `LIFECYCLE`(6) · `QUERY`(8) · `GRAPH`(4) ·
`PIPELINE`(5) · `MEMORY`(3) · `STATS`(1) · `ONTO-ENG`(7, optional).

**One core, three adapters.** Each capability lives once in
`src/knowledge_graph/core/*` and `phase_tools.py`; the three transports are
~3-line adapters:

```
                      ┌─────────────── MCP tools (agents; allow-listed)
knowledge_graph core ─┼─────────────── REST/JSON routes (python-tulla; Bearer)
  + phase_tools.py    └─────────────── DashboardService (humans; read-only → HITL)
```

---

## 1. Old → new tool mapping (all 63 dispositioned)

### KEEP (18) — unchanged
`add_dependency`, `remove_dependency`, `get_idea_dependencies`,
`get_workable_ideas`, `extract_todos`, `get_all_tags`, `check_parent_completion`¹,
`add_triple`, `remove_triple`, `sparql_query`, `sparql_update`,
`list_pipeline_tool`, `next_phase_tool`, `collect_upstream_facts_tool`,
`record_phase_result_tool`, `delete_idea`, `append_to_idea`, plus onto-eng
keeps (`list_ontologies`, `get_ontology`, `search_ontology`, `validate_instance`,
`list_quality_shapes`).

¹ `check_parent_completion` retained pending I-loop confirmation.

### KEEP+ (7) — absorbs params
| Tool | Change | Absorbs |
|------|--------|---------|
| `create_idea` | `parent?`, `lifecycle?` canonical | `create_sub_idea`, **`capture_seed`** |
| `get_idea` | `+ format: json\|markdown` | `export_idea_markdown`, `read_seed` |
| `update_idea` | **remove `lifecycle` field** | — |
| `set_lifecycle` | `+ priority?` | `move_to_backlog`, `crystallize_seed` |
| `query_ideas` | **drop `sparql` mode**; `+ wikidata?` | `get_ideas_by_lifecycle`, `list_by_author`, `get_ideas_by_wikidata`, `list_seeds` |
| `query_ontology` | structured introspection entry | `get_classes`, `get_properties` |
| `validate_ontology_quality` | `+ summary?` | `get_quality_summary` |

### MERGE (15 → 4)
| New tool | Replaces | Disambiguator |
|----------|----------|---------------|
| `store_facts` | `store_fact`, `store_facts_bulk` | always a list (1..n) |
| `recall_facts` | `recall_facts`, `recall_recent_facts` | `+ since?/hours?` |
| `forget_facts` | `forget_fact`, `forget_by_context` | `fact_id?` **xor** `context?` |
| `render_phase_spec` | `render_gates_tool`, `render_input_contract_tool`, `render_methodology_tool`, `render_output_contract_tool`, `render_phase_prompt_tool`, `render_tools_tool` | `section: gates\|input\|methodology\|output\|tools\|prompt\|all` |
| `get_stats` | `get_graph_stats`, `get_memory_stats`, `get_ralph_status` | `scope: graph\|memory\|ralph` |

> **Load-bearing constraint (see §3):** `render_phase_spec` and the merged
> memory/stats tools are consolidations of the **MCP wrapper layer only**. The
> underlying `phase_tools.py` functions (`render_gates`, `render_methodology`,
> …) and core store methods **must remain importable**, because python-tulla
> calls them in-process. Consolidate the menu, not the implementations.

### DROP (12) — pure subset/alias → redirect
`create_sub_idea`→`create_idea(parent=)` · `crystallize_seed`→`set_lifecycle`(+`update_idea`)
· `capture_seed`→`create_idea(lifecycle="seed")` · `read_seed`→`get_idea` ·
`export_idea_markdown`→`get_idea(format="markdown")` ·
`move_to_backlog`→`set_lifecycle("backlog", priority=)` ·
`list_seeds`/`get_ideas_by_lifecycle`/`list_by_author`/`get_ideas_by_wikidata`→`query_ideas(...)`
· `get_related_ideas`→`get_idea_dependencies` ·
`get_classes`/`get_properties`→`query_ontology` ·
`update_triple`→`remove_triple`+`add_triple` ·
`get_quality_summary`→`validate_ontology_quality(summary=true)`.

### MOVE (5 → 4) — to `wikidata-server`
`lookup_wikidata`→`lookup` · `query_wikidata`→`query` ·
`search_wikidata_cache`→`search_cache` · `get_wikidata_stats`→`stats`.
`get_ideas_by_wikidata` **stays** on ontology-server as `query_ideas(wikidata=)`
(it is an idea query, not a Wikidata call). **No dashboard view.**

---

## 2. Per-agent mount matrix (new names)

| Agent | Allow-list | Count |
|-------|-----------|------:|
| orchestrator (static routing) | `sparql_query` | 1 |
| orchestrator (dynamic `tulla-orchestrate`) | `sparql_query`, `list_pipeline_tool`, `next_phase_tool`, `collect_upstream_facts_tool`, `render_phase_spec` | 5 |
| D1 | `collect_upstream_facts_tool`, `record_phase_result_tool`, `get_idea`, `query_ideas` | 4 |
| D2, D3, P1, P2, P5, R1–R6 | `collect_upstream_facts_tool`, `record_phase_result_tool` | 2 |
| D4, P3 | + `query_ontology` | 3 |
| D5 | + `get_idea`, `append_to_idea` | 4 |
| P4 | + `store_facts` | 3 |
| P6 | + `recall_facts`, `store_facts` | 4 |
| I1_coding | + `recall_facts`, `store_facts`, `forget_facts`, `set_lifecycle` | 6 |
| claude_code (nested) | *(no ontology MCP)* | 0 |

Net vs today: identical capabilities; `store_fact`+`store_facts_bulk`→`store_facts`
trims P4/P6/I1 by one slot each; all other changes are 1:1 renames.

---

## 3. python-tulla regression analysis (the critical surface)

python-tulla couples to the ontology-server through **two** distinct
mechanisms — REST **and** direct in-process Python imports. Both must survive.

### 3a. REST calls (`adapters/ontology_mcp.py` → `OntologyMCPAdapter`)

| python-tulla method | HTTP call | Consolidation verdict |
|---------------------|-----------|-----------------------|
| `recall_facts` | `GET /facts` | ✅ keep route+params; `since` is additive |
| `store_fact` | `POST /facts` (single object) | ⚠️ **REST `/facts` POST must keep accepting a single-fact object.** The `store_facts`(list) merge is an MCP-layer change; do not make the REST body list-only, or add a list-or-object union. |
| `forget_fact` | `DELETE /facts/{fact_id}` | ⚠️ **keep the by-id DELETE route.** `forget_by_context` is done client-side (recall+loop), so no server context-delete endpoint is needed. |
| `query_ideas` | `GET /ideas` (lifecycle/author/tag/search/limit) | ✅ adapter never sends `sparql`; dropping sparql-mode is safe |
| `get_idea` | `GET /ideas/{id}` | ✅ default `format=json` must stay the default |
| `update_idea` | `POST /ideas/{id}/update` | ⛔ **PRE-EXISTING BUG — route does not exist on the server** (only `/ideas/{id}` GET and `/ideas/{id}/lifecycle` POST). This is broken today, independent of consolidation. Removing `lifecycle` from `update_idea` is therefore moot until the route is added. **Flag, don't blame the migration.** |
| `set_lifecycle` | `POST /ideas/{id}/lifecycle` ({new_state, reason}) | ✅ keep route + body; `priority` additive |
| `add_triple` | `POST /abox/triples` | ✅ keep |
| `remove_triples_by_subject` | `POST /abox/triples/remove` | ✅ keep (remove-by-subject must survive `update_triple` drop) |
| `sparql_query` | `POST /kg/sparql?query=` (query as query-param) | ✅ keep; server reads `query` as a query parameter |
| `sparql_update` | `POST /kg/update` ({query}) | ✅ keep |
| `collect_upstream_facts` | `GET /phases/upstream-facts/{id}` | ✅ keep |
| `validate_instance` | `POST /validate` ({instance_uri, shape_uri, ontology?}) | ✅ keep |

python-tulla does **not** use the REST `/phase/render-*`, `/phase/list-pipeline`,
`/phase/next-phase`, `/phase/record-phase-result`, `/sparql`, `/facts/stats`,
`/ideas/tags`, or `/ontologies*` routes — it reaches that functionality via
in-process imports (3b) or implements it client-side. Those REST routes may be
other consumers' or dead; **verify before pruning** under "fold everything".

### 3b. Direct in-process imports (`ports/ontology.py`) — HIGHEST RISK

`OntologyPort` imports underlying functions from `ontology_server.mcp.phase_tools`:

```
list_pipeline, render_gates, render_input_contract, render_output_contract,
render_methodology, render_tools, render_phase_prompt
```

and implements `record_phase_result` **client-side** via the port's own
abstract methods (`remove_triples_by_subject`, `add_triple`, `sparql_query`,
`validate_instance`).

Implications:
- The 6→1 `render_phase_spec` merge **must not delete** the six underlying
  `render_*(sparql, phase_id)` functions in `phase_tools.py`. They are imported
  by name. `render_phase_spec` becomes a dispatcher over them. **Prefer
  instead the §3d fix** (decouple python-tulla onto the REST render routes),
  which removes this constraint entirely.
- `list_pipeline(sparql, agent_family)` must remain importable by name.
- `record_phase_result`'s correctness depends on `add_triple`,
  `remove_triples_by_subject`, `sparql_query`, `validate_instance` keeping
  stable signatures + REST behavior (all KEEP) — safe.
- python-tulla requires `ontology_server` to be **importable as a package** in
  its environment. The Wikidata extraction must not move/break
  `ontology_server.mcp.phase_tools`'s import path.

### 3c. Regression checklist (gate for the implementation PR)
- [ ] REST `POST /facts` still accepts a single-fact object body.
- [ ] REST `DELETE /facts/{fact_id}` still present.
- [ ] REST `GET /ideas`, `GET /ideas/{id}` (json default), `POST /ideas/{id}/lifecycle`,
      `POST /abox/triples`, `POST /abox/triples/remove`, `POST /kg/sparql` (query-param),
      `POST /kg/update`, `GET /phases/upstream-facts/{id}`, `POST /validate` all unchanged.
- [ ] `phase_tools.render_{gates,input_contract,output_contract,methodology,tools,phase_prompt}`
      and `list_pipeline`, `next_phase`, `record_phase_result`, `collect_upstream_facts`
      remain importable with current signatures.
- [ ] `ontology_server.mcp.phase_tools` import path preserved after wikidata split.
- [ ] `python -c "import tulla.ports.ontology"` succeeds against the slimmed server.
- [ ] One full python-tulla pipeline run reaches `lifecycle: completed`.
- [ ] (separate ticket) decide whether to add the missing `POST /ideas/{id}/update`
      route or remove the dead `update_idea` HTTP path.

---

### 3d. Design debt — port → server import inversion (root cause of 3b)

`tulla/ports/ontology.py` is a **hexagonal port**: its job is to isolate
python-tulla from the ontology-server's implementation. The dependency rule
says arrows point inward — adapters depend on the port; the port depends on
nothing concrete. Today it violates that:

```python
# in the PORT base class:
from ontology_server.mcp.phase_tools import render_gates, render_methodology, \
    render_input_contract, render_output_contract, render_tools, \
    render_phase_prompt, list_pipeline
```

The port reaches into a **concrete server package's internal module**, so
`import tulla.ports.ontology` now requires `ontology_server` installed in
python-tulla's environment — for operations that otherwise speak pure HTTP.
This is the *sole* reason the §3b render-merge is risky.

**Inconsistency is the tell.** All of these operations *also* exist as REST
routes, yet the codebase uses three different strategies for one problem domain:

| Operation | Strategy today | Should be |
|-----------|----------------|-----------|
| `collect_upstream_facts` | REST `GET /phases/upstream-facts/{id}` ✅ | REST (already correct) |
| `render_*`, `list_pipeline` | **in-process import of server internals** ⛔ | REST `/phase/render-*`, `/phase/list-pipeline` |
| `record_phase_result` | client-side template method (reimplements the 8 steps the server also offers at `/phase/record-phase-result`) ⚠️ | pick one — see below |

**Severity split (do not lump these together):**
- The `render_*`/`list_pipeline` **imports are the bad part** — a layering
  violation + import-time cross-repo coupling + breaks on any rename/move of
  `phase_tools` (i.e. this migration).
- `record_phase_result` as a **template method is defensible** — it is expressed
  purely via the port's own abstract primitives (`add_triple`, `sparql_query`,
  `validate_instance`, `remove_triples_by_subject`), no external import. The
  only smell is that the same 8-step algorithm now exists twice (port +
  `phase_tools.record_phase_result`) and can drift.

**Likely origin (steelman):** `render_*` are pure `(sparql_client, phase_id) ->
str` helpers; `self` satisfies the client protocol, so reusing the server's
canonical impl (DRY, no network round-trip) was tempting — and the imports
probably predate the `/phase/render-*` REST routes and were never migrated.

### Recommended fix — decouple via REST (preferred over the 3b guardrail)
1. Make `render_*`, `list_pipeline`, `next_phase` **abstract** on the port and
   implement them in `OntologyMCPAdapter` over the existing REST routes, exactly
   as `collect_upstream_facts` already does. **Delete the `ontology_server`
   imports** → python-tulla gains zero import-dependency on the server package.
2. Pick **one** home for `record_phase_result`: keep the port template method
   and drop the unused REST route, *or* call `/phase/record-phase-result` and
   drop the port copy. Do not maintain both.
3. If in-process rendering with no network is genuinely wanted, the correct
   vehicle is a **small shared library** both repos depend on — never an import
   of the server's private MCP module.

**Why this beats the §3b guardrail:** once python-tulla renders over REST like
everything else, the 6→1 `render_phase_spec` MCP merge cannot affect it, and the
six `/phase/render-*` routes can themselves collapse into one
`/phase/render-spec?section=` on the shared core. The §3b "keep the six
underlying functions importable by name" constraint then **disappears** — we fix
the coupling instead of pinning function names to work around it. Prefer this
path; fall back to the §3b guardrail only if the decouple work is deferred.

---

## 4. Transport / exposure matrix (consolidated tool → adapter)

✅ expose · ⚠️ auth/admin-gated · ◦ optional · – do not expose

| Capability | MCP (agents) | REST (python-tulla) | Dashboard (read→HITL) |
|---|:--:|:--:|:--:|
| `create_idea` | ✅ | – | – (HITL: ⚠️ later) |
| `get_idea(format=)` | ✅ | ✅ | ✅ |
| `update_idea` | ✅ | ✅¹ | – |
| `append_to_idea` | ✅ | ◦ | – |
| `delete_idea` | ✅ | ⚠️ | – |
| `set_lifecycle(priority?)` | ✅ | ✅ | ⚠️ HITL action |
| `query_ideas` | ✅ | ✅ | ✅ |
| `get_idea_dependencies` | ✅ | ◦ | ✅ |
| `add_/remove_dependency` | ✅ | – | – |
| `get_workable_ideas` | ✅ | – | – |
| `extract_todos` | ✅ | – | ◦ |
| `get_all_tags` | ✅ | ◦ | ✅ |
| `sparql_query` | ✅ | ✅ | – |
| `sparql_update` | ✅ | ✅⚠️ | – |
| `add_/remove_triple` | ✅ | ✅⚠️ | – |
| `collect_upstream_facts_tool` | ✅ | ✅ | – |
| `record_phase_result_tool` | ✅ | (in-proc) | – |
| `list_pipeline`/`next_phase` | ✅ | (in-proc) | – |
| `render_phase_spec(section=)` | ✅ | (in-proc) | ✅ |
| `store_facts` | ✅ | ✅⚠️ | – |
| `recall_facts(since?)` | ✅ | ✅ | ✅ |
| `forget_facts` | ✅ | ⚠️ | – |
| `get_stats(scope=)` | ◦ | ✅ | ✅ |
| onto-eng reads (`list_ontologies`,`get_ontology`,`query_ontology`,`search_ontology`) | ✅ (D4/P3) | ✅ | ✅ |
| `validate_instance`/`validate_ontology_quality` | ✅ | ✅ | ◦ |

¹ blocked today — see §3a (`/ideas/{id}/update` route missing).

**Dashboard-only (HTML; never promote to MCP):** all `DashboardService`
projections/aggregations — `get_dashboard_summary`, idea/phase/PRD/requirement
views, `resolve_uri`, partials, login/logout, `/health`, static assets. These
read the same `prd:*`/phase facts agents write (flow: agent→MCP→store→dashboard).
HITL adds a *small* set of named, auth-gated write actions (e.g. `set_lifecycle`,
retry-requirement) — not raw graph mutation.

**Wikidata:** MCP on the new server only; no dashboard view; REST optional.

---

## 5. Rollout (regression-safe ordering)

1. **P0 Add** new/merged MCP tools + KEEP+ params **alongside** old ones; keep
   all underlying functions + REST routes. Existing tests stay green.
2. **P1 Flip** agent allow-lists + orchestrator to new names (tulla-agent repo).
   Immediate token savings; no python-tulla impact (it bypasses the menu).
3. **P2 Shim** removed/renamed MCP tools as thin delegating aliases carrying
   `_deprecated`; not in any allow-list. **Do not touch §3 functions/routes.**
4. **Wikidata split** stand up `wikidata-server`; keep `ontology_server.mcp.phase_tools`
   import path intact; ontology-server keeps announce-and-fail shims for the 4
   moved tools.
5. **Fold** collapse MCP/REST/Dashboard duplicate handlers onto the shared
   `knowledge_graph` core (esp. ideas/facts paths and the 3-way phase render),
   honoring the §3c checklist throughout.
6. **P3 Remove** shims after the deprecation window; final `git grep` for old
   names across ontology-server, tulla-agent, and python-tulla.

**Acceptance:** ontology-server exposes 34 tools; wikidata-server 4; no agent
context shows a deprecated name; §3c checklist all green; one python-tulla run
and one agent-fleet run both reach `lifecycle: completed`.

---

## 6. Open decisions
1. Missing `POST /ideas/{id}/update` — add the route, or delete the dead HTTP path?
2. `check_parent_completion` — keep or fold into `get_idea_dependencies` + lifecycle check?
3. Wikidata cache graph ownership — move `graphs/wikidata` to the new server, or keep shared + read cross-server?
4. Are the unused REST `/phase/*`, `/sparql`, `/facts/stats`, `/ideas/tags` routes live for any non-python-tulla caller, or prunable?
5. Deprecation window length (fixed date vs N release cycles).

---

## 7. Implementation status (executed)

Landed across three repos on feature branches (not pushed). Test results from a
clean-env run of each project venv.

| Workstream | Status | Where | Tests |
|------------|--------|-------|-------|
| §3d port→REST decouple | ✅ done | tulla `feat/decouple-port-rest` (`ec606e9`) | 1840 pass (+10) |
| P0 consolidated MCP tools (store_facts/forget_facts/get_stats/render_phase_spec/recall since_hours/set_lifecycle priority) | ✅ done (additive; old tools kept) | semantic-tool-use `feat/tool-consolidation` (`d35b6a0`) | 274 pass (+9) |
| Wikidata extraction → standalone server | ✅ done (new `wikidata_server` pkg; ontology-server tools kept as deprecated dupes) | semantic-tool-use (`1d4ae6e`) | 278 pass (+4) |
| §3a `/ideas/{id}/update` regression fix | ✅ done | semantic-tool-use (`02f6a4c`) | 281 pass (+3) |
| P1 allow-list + prompt flip to canonical names | ✅ done | tulla-agent `feat/consolidated-tool-allowlists` (`43047d8`) | 19/19 YAML valid |
| "Fold everything" onto shared core | ✅ satisfied at logic layer | all transports already delegate to knowledge_graph core + phase_tools; new tools reuse it | n/a |

### Intentionally deferred (per rollout design, not skipped)
- **P3 removals**: old tools (`store_fact`, `store_facts_bulk`, `forget_fact`,
  `forget_by_context`, `recall_recent_facts`, `move_to_backlog`,
  `crystallize_seed`, `create_sub_idea`, `read_seed`, `export_idea_markdown`,
  `get_*_stats`, `get_related_ideas`, `update_triple`, `get_classes/properties`,
  6× `render_*_tool`, 4× ontology-server wikidata tools) remain registered as
  P0/P2 duplicates. Remove after the deprecation window once external callers
  migrate. Removal is what shrinks the surface to 34; today both names coexist.
- **KEEP+ params `get_idea(format=)` and `query_ideas(wikidata=)`**: deferred to
  the removal pass (not needed for the allow-list flip; old tools still serve).
- **Adapter-surface dedup**: MCP closures and REST routes are thin parallel
  adapters over the same core; collapsing them further is cosmetic cleanup.
- **`capture_seed` consolidation**: documented mapping in place; the old tool
  remains until P3 (no agent uses it).

### Regression-checklist (§3c) outcome
All green: REST `/facts` POST still single-object; `DELETE /facts/{fact_id}`
intact; `/ideas`, `/ideas/{id}`, `/ideas/{id}/lifecycle`, `/abox/triples(+/remove)`,
`/kg/sparql`, `/kg/update`, `/phases/upstream-facts/{id}`, `/validate` unchanged;
`/ideas/{id}/update` now present; `phase_tools` render/list/next/record functions
remain importable; `python -c "import tulla.ports.ontology"` succeeds with
ontology_server ABSENT (decouple verified); python-tulla full suite green.
