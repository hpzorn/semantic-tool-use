# mcp-check — MCP Server Health & Tool Verification CLI

Lightweight CLI that connects to any MCP server via SSE transport, calls
user-supplied tools, reports PASS/FAIL with timing, and exits non-zero on
failure.

---

## 1. Installation

```bash
# Activate the project virtualenv first
source .venv/bin/activate

# Install in editable mode (includes mcp-check entry-point)
pip install -e .

# Verify
mcp-check --help
```

---

## 2. Usage

### Flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--url` | string | *required* | MCP server SSE endpoint, e.g. `http://localhost:8100/sse` |
| `--tool` | string (repeatable) | — | Tool name to invoke; repeat for multiple tools |
| `--wait` | int (seconds) | `0` | Poll `GET /health` up to N seconds before running tools |
| `--json` | flag | off | Emit machine-readable JSON array to stdout |

### Invocation examples

```bash
# Check a single tool (human output)
mcp-check --url http://localhost:8100/sse --tool get_graph_stats

# Check multiple tools and emit JSON
mcp-check --url http://localhost:8100/sse \
  --tool get_graph_stats \
  --tool list_ontologies \
  --json

# Wait up to 60 s for the server to start, then check
mcp-check --url http://localhost:8100/sse \
  --wait 60 \
  --tool get_graph_stats
```

### Human output format

```
[PASS]   get_graph_stats                          38ms
[FAIL]   missing_tool                             2ms   McpError -32601: Unknown tool
```

Exit code `0` if all tools PASS; `1` if any tool FAILs or the server is
unreachable.

---

## 3. PYTHONPATH Warning

If you run `mcp-check` while a `PYTHONPATH` is set (common in some CI
environments or conda setups), imports from the wrong site-packages may
shadow the installed package.

**Fix:**

```bash
# Ensure the venv is active — that is the safest approach
source .venv/bin/activate
mcp-check --url ...

# Or explicitly clear PYTHONPATH
PYTHONPATH="" mcp-check --url ...
```

**In GitHub Actions / CI:**

```yaml
- name: Run mcp-check
  env:
    PYTHONPATH: ""
  run: mcp-check --url http://localhost:8100/sse --tool get_graph_stats --json
```

---

## 4. Sample GitHub Actions Workflow

```yaml
name: MCP Server Health Check

on: [push, pull_request]

jobs:
  health-check:
    runs-on: ubuntu-latest

    services:
      ontology-server:
        image: ghcr.io/your-org/semantic-tool-use:latest
        ports:
          - 8100:8100

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install package
        run: pip install -e .

      - name: Run mcp-check
        env:
          PYTHONPATH: ""
        run: |
          mcp-check \
            --url http://localhost:8100/sse \
            --wait 60 \
            --tool get_graph_stats \
            --tool list_ontologies \
            --json
```

---

## 5. v2 Roadmap

**Planned: `--tool NAME ARGS` (nargs=2, non-breaking)**

In v2, each `--tool` option will accept an optional JSON-encoded arguments
string as a second value:

```bash
# v2 (planned)
mcp-check --url http://localhost:8100/sse \
  --tool get_idea '{"uri": "http://semantic-tool-use.org/ideas/idea-9"}'
```

Implementation sketch:

```python
# Click nargs=2 variant — non-breaking because the second element
# defaults to '{}' when omitted by the caller
@click.option("--tool", "tools", type=(str, str), multiple=True,
              default=[], help="NAME JSON_ARGS")
```

Existing `--tool NAME` callers would migrate by appending `'{}'`, or the
entry-point could auto-detect single-value vs. two-value form.
