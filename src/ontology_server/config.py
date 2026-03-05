"""Configuration settings for the Ontology Server."""

from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Server configuration with environment variable support.

    All settings can be overridden via environment variables prefixed with ONTOLOGY_.
    For example: ONTOLOGY_PORT=9000 or ONTOLOGY_ONTOLOGY_PATH=/custom/path
    """

    model_config = SettingsConfigDict(
        env_prefix="ONTOLOGY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Paths
    ontology_path: Path = Path("ontologies")
    ontology_paths: list[Path] = []  # Additional ontology directories
    shapes_path: Path = Path("ontology/shapes")

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8420

    # MCP settings
    mcp_name: str = "ontology-server"
    mcp_version: str = "0.1.0"

    # Authentication
    api_key: str = ""  # Set via ONTOLOGY_API_KEY env var; auto-generated if empty

    # Logging
    log_level: str = "INFO"

    # Feature flags
    enable_rest_api: bool = True
    enable_websocket: bool = False  # Phase 5
    enable_llm: bool = False  # LLM analysis tools (requires ANTHROPIC_API_KEY)
    enable_search: bool = False  # Semantic search tools (requires sentence-transformers)

    def get_ontology_path(self) -> Path:
        """Get resolved ontology path."""
        return self.ontology_path.resolve()

    def get_shapes_path(self) -> Path:
        """Get resolved shapes path."""
        return self.shapes_path.resolve()


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Default settings instance for direct import
settings = get_settings()
