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
    shapes_path: Path = Path("ontologies/shapes")

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8420

    # MCP settings
    mcp_name: str = "ontology-server"
    mcp_version: str = "0.1.0"

    # Logging
    log_level: str = "INFO"

    # Feature flags
    enable_rest_api: bool = True
    enable_websocket: bool = False  # Phase 5

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
