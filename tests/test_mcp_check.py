"""Tests for mcp_check CLI — no live server required."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from mcp_check.mcp_check import ToolResult, _run_tools, _wait_for_health, cli


# ---------------------------------------------------------------------------
# Unit: _run_tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pass():
    session = MagicMock()
    mock_result = MagicMock()
    mock_result.isError = False
    session.call_tool = AsyncMock(return_value=mock_result)

    results = await _run_tools(session, ("my_tool",))

    assert len(results) == 1
    assert results[0].status == "PASS"
    assert results[0].name == "my_tool"
    assert results[0].error_msg is None


@pytest.mark.asyncio
async def test_fail_is_error():
    session = MagicMock()
    mock_result = MagicMock()
    mock_result.isError = True
    mock_result.content = "tool not found"
    session.call_tool = AsyncMock(return_value=mock_result)

    results = await _run_tools(session, ("bad_tool",))

    assert results[0].status == "FAIL"
    assert "tool not found" in results[0].error_msg


@pytest.mark.asyncio
async def test_fail_timeout():
    from mcp.shared.exceptions import McpError
    from mcp.types import ErrorData

    session = MagicMock()
    error = McpError(ErrorData(code=408, message="Request timeout"))
    session.call_tool = AsyncMock(side_effect=error)

    results = await _run_tools(session, ("slow_tool",))

    assert results[0].status == "FAIL"
    assert results[0].error_msg == "Timeout"


# ---------------------------------------------------------------------------
# Unit: _wait_for_health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_success():
    call_count = 0

    async def fake_get(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.ConnectError("refused")
        resp = MagicMock()
        resp.status_code = 200
        return resp

    with patch("mcp_check.mcp_check.httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.get = fake_get
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        result = await _wait_for_health("http://localhost:8100/health", timeout=5)

    assert result is True


@pytest.mark.asyncio
async def test_wait_timeout():
    async def fake_get(url, **kwargs):
        raise httpx.ConnectError("always refused")

    with patch("mcp_check.mcp_check.httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.get = fake_get
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        result = await _wait_for_health("http://localhost:8100/health", timeout=1)

    assert result is False


# ---------------------------------------------------------------------------
# CLI integration via CliRunner
# ---------------------------------------------------------------------------


def _make_sse_patch(tool_results: list[ToolResult]):
    """Return a context manager mock that drives _async_main to return tool_results."""

    async def fake_async_main(url, tools, wait, json_out):
        return tool_results

    return patch("mcp_check.mcp_check._async_main", side_effect=fake_async_main)


def test_fail_connect_error():
    runner = CliRunner()

    async def raise_connect(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    with patch("mcp_check.mcp_check._async_main", side_effect=raise_connect):
        result = runner.invoke(cli, ["--url", "http://localhost:9999/sse", "--tool", "x"])

    assert result.exit_code == 1


def test_json_output():
    runner = CliRunner()
    fake_results = [ToolResult("get_graph_stats", "PASS", 42.5, None)]

    with _make_sse_patch(fake_results):
        result = runner.invoke(
            cli,
            ["--url", "http://localhost:8100/sse", "--tool", "get_graph_stats", "--json"],
        )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert data[0]["tool"] == "get_graph_stats"
    assert data[0]["status"] == "PASS"
    assert "elapsed_ms" in data[0]
    assert "error" in data[0]


def test_exit_code_zero():
    runner = CliRunner()
    fake_results = [
        ToolResult("tool_a", "PASS", 10.0, None),
        ToolResult("tool_b", "PASS", 20.0, None),
    ]

    with _make_sse_patch(fake_results):
        result = runner.invoke(
            cli,
            ["--url", "http://localhost:8100/sse", "--tool", "tool_a", "--tool", "tool_b"],
        )

    assert result.exit_code == 0


def test_exit_code_nonzero():
    runner = CliRunner()
    fake_results = [
        ToolResult("tool_a", "PASS", 10.0, None),
        ToolResult("tool_b", "FAIL", 20.0, "some error"),
    ]

    with _make_sse_patch(fake_results):
        result = runner.invoke(
            cli,
            ["--url", "http://localhost:8100/sse", "--tool", "tool_a", "--tool", "tool_b"],
        )

    assert result.exit_code == 1
