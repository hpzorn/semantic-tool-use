#!/usr/bin/env python3
"""Setup script for ontology-server Bearer token authentication.

This script:
1. Generates or reads the API key from ~/.ontology-server-key
2. Prints shell export command for ONTOLOGY_API_KEY
3. Shows the headers config to add to ~/.claude.json
4. Optionally patches ~/.claude.json automatically

Usage:
    python -m ontology_server.setup_auth          # Show instructions
    python -m ontology_server.setup_auth --apply   # Apply changes automatically
"""

import argparse
import json
import sys
from pathlib import Path

from .auth import get_or_create_api_key, KEY_FILE


def get_shell_profile() -> Path:
    """Detect the user's shell profile file."""
    shell = Path.home() / ".zshrc"
    if shell.exists():
        return shell
    shell = Path.home() / ".bashrc"
    if shell.exists():
        return shell
    return Path.home() / ".profile"


EXPORT_LINE = 'export ONTOLOGY_API_KEY="$(cat ~/.ontology-server-key)"'


def check_shell_profile(profile: Path) -> bool:
    """Check if the shell profile already has the ONTOLOGY_API_KEY export."""
    if not profile.exists():
        return False
    return "ONTOLOGY_API_KEY" in profile.read_text()


def patch_claude_json(api_key: str) -> bool:
    """Add Authorization header to ontology-server entry in ~/.claude.json.

    Returns True if the file was modified, False if already configured or not found.
    """
    claude_json = Path.home() / ".claude.json"
    if not claude_json.exists():
        return False

    data = json.loads(claude_json.read_text())

    # Look for ontology-server in mcpServers
    mcp_servers = data.get("mcpServers", {})
    if "ontology-server" not in mcp_servers:
        return False

    server_config = mcp_servers["ontology-server"]

    # Check if headers already configured
    existing_headers = server_config.get("headers", {})
    if "Authorization" in existing_headers:
        return False

    # Add headers with env var expansion
    server_config["headers"] = {
        **existing_headers,
        "Authorization": "Bearer ${ONTOLOGY_API_KEY}",
    }

    claude_json.write_text(json.dumps(data, indent=2) + "\n")
    return True


def main():
    parser = argparse.ArgumentParser(description="Setup ontology-server authentication")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Automatically apply changes to shell profile and ~/.claude.json",
    )
    args = parser.parse_args()

    # Step 1: Ensure API key exists
    api_key = get_or_create_api_key()
    print(f"API key file: {KEY_FILE}")
    print(f"API key: {api_key[:8]}...{api_key[-4:]}")
    print()

    # Step 2: Shell profile
    profile = get_shell_profile()
    has_export = check_shell_profile(profile)

    if has_export:
        print(f"[OK] Shell profile ({profile}) already exports ONTOLOGY_API_KEY")
    elif args.apply:
        with open(profile, "a") as f:
            f.write(f"\n# Ontology Server API Key\n{EXPORT_LINE}\n")
        print(f"[APPLIED] Added ONTOLOGY_API_KEY export to {profile}")
    else:
        print(f"Add to {profile}:")
        print(f"  {EXPORT_LINE}")
    print()

    # Step 3: Claude JSON config
    claude_json = Path.home() / ".claude.json"
    if not claude_json.exists():
        print(f"[SKIP] {claude_json} not found")
    elif args.apply:
        if patch_claude_json(api_key):
            print(f"[APPLIED] Added Authorization header to {claude_json}")
        else:
            print(f"[OK] {claude_json} already configured (or ontology-server entry not found)")
    else:
        print(f"Add to ontology-server entry in {claude_json}:")
        print('  "headers": {')
        print('    "Authorization": "Bearer ${ONTOLOGY_API_KEY}"')
        print("  }")
    print()

    if not args.apply:
        print("Run with --apply to make these changes automatically.")


if __name__ == "__main__":
    main()
