from __future__ import annotations

import dataclasses
import json
import logging
import sys
import time
from typing import Optional

import anyio
import click
import httpx
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.shared.exceptions import McpError

log = logging.getLogger(__name__)


@dataclasses.dataclass
class ToolResult:
    name: str
    status: str  # "PASS" or "FAIL"
    elapsed_ms: float
    error_msg: Optional[str]


async def _wait_for_health(health_url: str, timeout: int) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(health_url)
                if resp.status_code == 200:
                    return True
        except httpx.ConnectError:
            pass
        await anyio.sleep(1.0)
    return False


async def _run_tools(
    session: ClientSession, tools: tuple[str, ...]
) -> list[ToolResult]:
    results: list[ToolResult] = []
    for name in tools:
        t0 = time.perf_counter()
        try:
            result = await session.call_tool(name, arguments={})
            elapsed_ms = (time.perf_counter() - t0) * 1000
            if result.isError:
                results.append(
                    ToolResult(name, "FAIL", elapsed_ms, str(result.content))
                )
            else:
                results.append(ToolResult(name, "PASS", elapsed_ms, None))
        except McpError as e:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            if e.error.code == 408:
                results.append(ToolResult(name, "FAIL", elapsed_ms, "Timeout"))
            else:
                results.append(
                    ToolResult(
                        name,
                        "FAIL",
                        elapsed_ms,
                        f"McpError {e.error.code}: {e.error.message}",
                    )
                )
    return results


class Reporter:
    @staticmethod
    def human(results: list[ToolResult]) -> None:
        for r in results:
            status_str = f"[{r.status}]"
            line = f"{status_str:<8} {r.name:<40} {r.elapsed_ms:.0f}ms"
            if r.error_msg:
                line += f"  {r.error_msg}"
            click.echo(line)

    @staticmethod
    def json_out(results: list[ToolResult]) -> None:
        data = [
            {
                "tool": r.name,
                "status": r.status,
                "elapsed_ms": round(r.elapsed_ms, 2),
                "error": r.error_msg,
            }
            for r in results
        ]
        click.echo(json.dumps(data, indent=2))


async def _async_main(
    url: str, tools: tuple[str, ...], wait: int, json_out: bool
) -> list[ToolResult]:
    if wait > 0:
        health_url = url.rsplit("/sse", 1)[0] + "/health"
        ok = await _wait_for_health(health_url, wait)
        if not ok:
            click.echo(
                f"ERROR: server at {health_url} did not become healthy within {wait}s",
                err=True,
            )
            raise SystemExit(1)

    async with sse_client(url, timeout=5, sse_read_timeout=30) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            return await _run_tools(session, tools)


@click.command()
@click.option("--url", required=True, help="MCP server SSE endpoint URL")
@click.option("--tool", "tools", multiple=True, help="Tool name to invoke (repeatable)")
@click.option("--wait", default=0, help="Poll GET /health for up to SECONDS before running tools")
@click.option("--json", "json_out", is_flag=True, default=False, help="Emit machine-readable JSON")
def cli(url: str, tools: tuple[str, ...], wait: int, json_out: bool) -> None:
    """Check MCP server tools via SSE transport."""
    try:
        results: list[ToolResult] = anyio.run(
            _async_main, url, tools, wait, json_out, backend="asyncio"
        )
    except httpx.ConnectError as e:
        click.echo(f"ERROR: Cannot connect to {url}: {e}", err=True)
        sys.exit(1)

    if json_out:
        Reporter.json_out(results)
    else:
        Reporter.human(results)

    if any(r.status == "FAIL" for r in results):
        sys.exit(1)
    else:
        sys.exit(0)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
