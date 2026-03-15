"""Authentication for the Ontology Server.

Provides Bearer token authentication using the MCP SDK's native TokenVerifier
protocol. A static pre-shared API key is validated at the Starlette middleware
layer — no per-tool-handler changes required.
"""

import logging
import os
import secrets
from pathlib import Path

from mcp.server.auth.provider import AccessToken

logger = logging.getLogger(__name__)

KEY_FILE = Path.home() / ".ontology-server-key"


class StaticTokenVerifier:
    """Validates Bearer tokens against a pre-shared static API key.

    Implements the MCP SDK's TokenVerifier protocol for use with
    FastMCP's native auth infrastructure.
    """

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def verify_token(self, token: str) -> AccessToken | None:
        if token == self._api_key:
            return AccessToken(
                token=token,
                client_id="ontology-client",
                scopes=[],
                expires_at=None,
            )
        return None


def get_or_create_api_key() -> str:
    """Get the API key from environment, key file, or generate a new one.

    Resolution order:
    1. ONTOLOGY_API_KEY environment variable
    2. ~/.ontology-server-key file
    3. Auto-generate and write to ~/.ontology-server-key

    Returns:
        The API key string.
    """
    # 1. Check environment variable
    if key := os.environ.get("ONTOLOGY_API_KEY"):
        logger.debug("Using API key from ONTOLOGY_API_KEY environment variable")
        return key

    # 2. Check key file
    if KEY_FILE.exists():
        key = KEY_FILE.read_text().strip()
        if key:
            logger.debug("Using API key from %s", KEY_FILE)
            return key

    # 3. Auto-generate
    key = secrets.token_urlsafe(32)
    KEY_FILE.write_text(key + "\n")
    KEY_FILE.chmod(0o600)
    logger.info("Generated new API key and saved to %s", KEY_FILE)
    return key
