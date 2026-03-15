"""Tests for ontology-server Bearer token authentication.

Validates:
- StaticTokenVerifier correctly validates/rejects tokens
- get_or_create_api_key key generation, file storage, and env var resolution
- FastMCP server creation with auth wiring
- HTTP-level auth enforcement (401 for unauthenticated, 200 for authenticated)
"""

import asyncio
import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from ontology_server.auth import StaticTokenVerifier, get_or_create_api_key, KEY_FILE
from ontology_server.config import Settings
from ontology_server.core.store import OntologyStore
from ontology_server.mcp.server import create_mcp_server


# ── StaticTokenVerifier Tests ────────────────────────────────────────────────


class TestStaticTokenVerifier:
    """Tests for the StaticTokenVerifier class."""

    @pytest.fixture
    def verifier(self):
        return StaticTokenVerifier("test-secret-key")

    @pytest.mark.asyncio
    async def test_valid_token_returns_access_token(self, verifier):
        result = await verifier.verify_token("test-secret-key")
        assert result is not None
        assert result.token == "test-secret-key"
        assert result.client_id == "ontology-client"
        assert result.scopes == []
        assert result.expires_at is None

    @pytest.mark.asyncio
    async def test_invalid_token_returns_none(self, verifier):
        result = await verifier.verify_token("wrong-key")
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_token_returns_none(self, verifier):
        result = await verifier.verify_token("")
        assert result is None

    @pytest.mark.asyncio
    async def test_partial_token_returns_none(self, verifier):
        result = await verifier.verify_token("test-secret")
        assert result is None


# ── Key Management Tests ─────────────────────────────────────────────────────


class TestGetOrCreateApiKey:
    """Tests for get_or_create_api_key function."""

    def test_reads_from_env_var(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ONTOLOGY_API_KEY", "env-key-value")
        monkeypatch.setattr("ontology_server.auth.KEY_FILE", tmp_path / "nonexistent")
        key = get_or_create_api_key()
        assert key == "env-key-value"

    def test_reads_from_key_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ONTOLOGY_API_KEY", raising=False)
        key_file = tmp_path / ".ontology-server-key"
        key_file.write_text("file-key-value\n")
        monkeypatch.setattr("ontology_server.auth.KEY_FILE", key_file)
        key = get_or_create_api_key()
        assert key == "file-key-value"

    def test_auto_generates_when_no_source(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ONTOLOGY_API_KEY", raising=False)
        key_file = tmp_path / ".ontology-server-key"
        monkeypatch.setattr("ontology_server.auth.KEY_FILE", key_file)
        key = get_or_create_api_key()
        assert len(key) > 20  # secrets.token_urlsafe(32) gives ~43 chars
        assert key_file.exists()
        assert key_file.read_text().strip() == key

    def test_auto_generated_key_has_restricted_permissions(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ONTOLOGY_API_KEY", raising=False)
        key_file = tmp_path / ".ontology-server-key"
        monkeypatch.setattr("ontology_server.auth.KEY_FILE", key_file)
        get_or_create_api_key()
        mode = key_file.stat().st_mode
        assert mode & stat.S_IRWXG == 0, "Group should have no permissions"
        assert mode & stat.S_IRWXO == 0, "Others should have no permissions"

    def test_env_var_takes_precedence_over_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ONTOLOGY_API_KEY", "env-wins")
        key_file = tmp_path / ".ontology-server-key"
        key_file.write_text("file-loses\n")
        monkeypatch.setattr("ontology_server.auth.KEY_FILE", key_file)
        key = get_or_create_api_key()
        assert key == "env-wins"

    def test_empty_file_triggers_generation(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ONTOLOGY_API_KEY", raising=False)
        key_file = tmp_path / ".ontology-server-key"
        key_file.write_text("")
        monkeypatch.setattr("ontology_server.auth.KEY_FILE", key_file)
        key = get_or_create_api_key()
        assert len(key) > 20
        assert key_file.read_text().strip() == key


# ── Server Auth Wiring Tests ────────────────────────────────────────────────


class TestServerAuthWiring:
    """Tests that auth is properly wired into the MCP server."""

    def test_server_created_with_auth(self):
        settings = Settings(
            api_key="test-auth-key",
            ontology_path=Path("ontologies"),
            shapes_path=Path("ontologies/shapes"),
        )
        store = OntologyStore()
        mcp = create_mcp_server(settings, store)
        assert mcp is not None
        assert mcp.name == "ontology-server"

    def test_server_created_without_auth_when_no_key(self):
        settings = Settings(
            api_key="",
            ontology_path=Path("ontologies"),
            shapes_path=Path("ontologies/shapes"),
        )
        store = OntologyStore()
        mcp = create_mcp_server(settings, store)
        assert mcp is not None
        assert mcp.name == "ontology-server"


# ── HTTP-Level Auth Enforcement Tests ────────────────────────────────────────


class TestHTTPAuthEnforcement:
    """Tests that auth is enforced at the HTTP transport layer.

    These tests spin up a real SSE server and make HTTP requests to verify
    that unauthenticated requests receive 401 and authenticated requests
    succeed.
    """

    TEST_API_KEY = "test-http-auth-key"
    TEST_PORT = 18421

    @pytest.fixture
    def auth_server(self):
        settings = Settings(
            api_key=self.TEST_API_KEY,
            ontology_path=Path("ontologies"),
            shapes_path=Path("ontologies/shapes"),
            host="127.0.0.1",
            port=self.TEST_PORT,
        )
        store = OntologyStore()
        return create_mcp_server(settings, store)

    @pytest.mark.asyncio
    async def test_unauthenticated_request_returns_401(self, auth_server):
        import httpx
        import uvicorn

        sse_app = auth_server.sse_app()
        config = uvicorn.Config(
            sse_app, host="127.0.0.1", port=self.TEST_PORT, log_level="warning"
        )
        server = uvicorn.Server(config)
        server_task = asyncio.create_task(server.serve())

        try:
            await asyncio.sleep(1.0)

            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{self.TEST_PORT}"
            ) as client:
                resp = await client.get("/sse", timeout=5.0)
                assert resp.status_code in (401, 403), (
                    f"Expected 401/403, got {resp.status_code}"
                )
                # Check WWW-Authenticate header
                www_auth = resp.headers.get("www-authenticate", "")
                assert "bearer" in www_auth.lower(), (
                    f"Expected 'Bearer' in WWW-Authenticate, got: {www_auth}"
                )
        finally:
            server.should_exit = True
            await server_task

    @pytest.mark.asyncio
    async def test_authenticated_request_succeeds(self, auth_server):
        import httpx
        import uvicorn

        sse_app = auth_server.sse_app()
        config = uvicorn.Config(
            sse_app, host="127.0.0.1", port=self.TEST_PORT, log_level="warning"
        )
        server = uvicorn.Server(config)
        server_task = asyncio.create_task(server.serve())

        try:
            await asyncio.sleep(1.0)

            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{self.TEST_PORT}"
            ) as client:
                try:
                    resp = await client.get(
                        "/sse",
                        headers={"Authorization": f"Bearer {self.TEST_API_KEY}"},
                        timeout=3.0,
                    )
                    # SSE should return 200 with text/event-stream
                    assert resp.status_code == 200
                except httpx.ReadTimeout:
                    # SSE streams don't close — timeout is expected for a successful
                    # connection since the server keeps the stream open
                    pass
        finally:
            server.should_exit = True
            await server_task

    @pytest.mark.asyncio
    async def test_wrong_token_returns_401(self, auth_server):
        import httpx
        import uvicorn

        sse_app = auth_server.sse_app()
        config = uvicorn.Config(
            sse_app, host="127.0.0.1", port=self.TEST_PORT, log_level="warning"
        )
        server = uvicorn.Server(config)
        server_task = asyncio.create_task(server.serve())

        try:
            await asyncio.sleep(1.0)

            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{self.TEST_PORT}"
            ) as client:
                resp = await client.get(
                    "/sse",
                    headers={"Authorization": "Bearer wrong-token-value"},
                    timeout=5.0,
                )
                assert resp.status_code in (401, 403), (
                    f"Expected 401/403 for wrong token, got {resp.status_code}"
                )
        finally:
            server.should_exit = True
            await server_task
